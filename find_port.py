#!/usr/bin/env python3
"""find_port.py — หาพอร์ต ADB ไร้สายผ่าน mDNS/DNS-SD โดยใช้ stdlib ล้วน

ทำไมต้องมี: `adb mdns services` ใช้ไม่ได้บน Termux หลายเวอร์ชัน
(`mdns is not supported by this version of adb`) แต่ Android ยังประกาศ
บริการ `_adb-tls-connect._tcp` ผ่าน mDNS อยู่ — เราเลยถามเองด้วย UDP

วิธีใช้:
    python find_port.py            # หาแล้วพิมพ์ IP:PORT
    python find_port.py --connect  # หาแล้วสั่ง adb connect ให้เลย
"""

from __future__ import annotations

import argparse
import os
import random
import re
import socket
import struct
import subprocess
import sys
import time

SERVICE_CONNECT = "_adb-tls-connect._tcp.local"
SERVICE_PAIR = "_adb-tls-pairing._tcp.local"
SERVICE = SERVICE_CONNECT  # back-compat for tests/importers
MDNS_ADDR = "224.0.0.251"
MDNS_PORT = 5353

TYPE_A = 1
TYPE_PTR = 12
TYPE_TXT = 16
TYPE_SRV = 33

QU_BIT = 0x8000  # "unicast response requested" — จำเป็นเพราะเราฟังบน ephemeral port


# ---------------------------------------------------------------------------
# DNS wire format
# ---------------------------------------------------------------------------
def encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        if not label:
            continue
        raw = label.encode("utf-8")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def build_query(name: str, qtype: int) -> bytes:
    header = struct.pack("!HHHHHH", random.randint(0, 0xFFFF), 0x0000, 1, 0, 0, 0)
    question = encode_name(name) + struct.pack("!HH", qtype, 0x0001 | QU_BIT)
    return header + question


def read_name(data: bytes, offset: int, depth: int = 0) -> tuple[str, int]:
    """Decode a (possibly compressed) DNS name. Returns (name, next_offset)."""
    if depth > 8:
        return "", offset

    labels: list[str] = []
    cursor = offset
    while True:
        if cursor >= len(data):
            return ".".join(labels), cursor
        length = data[cursor]
        if length == 0:
            cursor += 1
            break
        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(data):
                return ".".join(labels), cursor + 1
            pointer = ((length & 0x3F) << 8) | data[cursor + 1]
            suffix, _ = read_name(data, pointer, depth + 1)
            if suffix:
                labels.append(suffix)
            return ".".join(labels), cursor + 2
        labels.append(data[cursor + 1 : cursor + 1 + length].decode("utf-8", "replace"))
        cursor += 1 + length
    return ".".join(labels), cursor


def parse_response(data: bytes) -> dict:
    """Return {'ptr': [...], 'srv': [...], 'a': [...]}."""
    result: dict[str, list] = {"ptr": [], "srv": [], "a": []}
    if len(data) < 12:
        return result

    qd, an, ns, ar = struct.unpack("!HHHH", data[4:12])
    offset = 12

    for _ in range(qd):
        _, offset = read_name(data, offset)
        offset += 4  # qtype + qclass

    for _ in range(an + ns + ar):
        if offset >= len(data):
            break
        name, offset = read_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        rstart = offset
        offset += rdlength

        try:
            if rtype == TYPE_PTR:
                target, _ = read_name(data, rstart)
                result["ptr"].append((name, target))
            elif rtype == TYPE_SRV and len(rdata) >= 6:
                port = struct.unpack("!H", rdata[4:6])[0]
                target, _ = read_name(data, rstart + 6)
                result["srv"].append((name, port, target))
            elif rtype == TYPE_A and len(rdata) == 4:
                result["a"].append((name, ".".join(str(b) for b in rdata)))
        except (struct.error, IndexError):
            continue

    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
TAILSCALE_CIDR = ("100.64.", "100.65.", "100.66.", "100.67.", "100.68.",
                  "100.69.", "100.70.", "100.71.", "100.72.", "100.73.",
                  "100.74.", "100.75.", "100.76.", "100.77.", "100.78.",
                  "100.79.", "100.80.", "100.81.", "100.82.", "100.83.",
                  "100.84.", "100.85.", "100.86.", "100.87.", "100.88.",
                  "100.89.", "100.90.", "100.91.", "100.92.", "100.93.",
                  "100.94.", "100.95.", "100.96.", "100.97.", "100.98.",
                  "100.99.", "100.100.", "100.101.", "100.102.", "100.103.",
                  "100.104.", "100.105.", "100.106.", "100.107.", "100.108.",
                  "100.109.", "100.110.", "100.111.", "100.112.", "100.113.",
                  "100.114.", "100.115.", "100.116.", "100.117.", "100.118.",
                  "100.119.", "100.120.", "100.121.", "100.122.", "100.123.",
                  "100.124.", "100.125.", "100.126.", "100.127.")


def is_tailscale(ip: str) -> bool:
    """Tailscale hands out addresses from the 100.64.0.0/10 CGNAT range."""
    try:
        first, second, *_ = (int(part) for part in ip.split("."))
    except ValueError:
        return False
    return first == 100 and 64 <= second <= 127


def _ips_from_proc() -> list[str]:
    """Read local addresses from /proc/net/fib_trie.

    Works on Android where `ip` and `ifconfig` are often missing.
    """
    try:
        with open("/proc/net/fib_trie", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return []

    found: list[str] = []
    previous = ""
    pattern = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
    for line in lines:
        if line.strip().endswith("host LOCAL"):
            match = pattern.search(previous)
            if match:
                found.append(match.group(1))
        previous = line
    return found


def local_ips(include_loopback: bool = False) -> list[str]:
    """All usable IPv4 addresses of this device, best first.

    Order: Tailscale, then Wi-Fi/LAN, then loopback (when asked). Termux runs
    on the phone itself, so Tailscale and loopback both reach the same adbd —
    trying them all is much more reliable than guessing one.
    """
    raw: list[str] = []

    raw.extend(_ips_from_proc())

    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                raw.append(parts[parts.index("inet") + 1].split("/")[0])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    try:
        out = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            parts = line.replace("addr:", "").split()
            if "inet" in parts:
                raw.append(parts[parts.index("inet") + 1])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    if not raw:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("1.1.1.1", 53))
            raw.append(sock.getsockname()[0])
            sock.close()
        except OSError:
            pass

    usable = []
    for ip in raw:
        if ip.startswith(("127.", "0.", "169.254.")):
            continue
        if ip not in usable:
            usable.append(ip)

    tailscale = [ip for ip in usable if is_tailscale(ip)]
    others = [ip for ip in usable if not is_tailscale(ip)]
    ordered = tailscale + others
    if include_loopback:
        ordered.append("127.0.0.1")
    return ordered


def query_once(
    targets: list[str],
    timeout: float = 2.5,
    service: str = SERVICE_CONNECT,
) -> list[tuple[str, int]]:
    """Ask mDNS for one ADB service; return [(ip, port), ...]."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(timeout)
        packet = build_query(service, TYPE_PTR)
        for target in targets:
            try:
                sock.sendto(packet, (target, MDNS_PORT))
            except OSError:
                continue

        found: list[tuple[str, int]] = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(9000)
            except socket.timeout:
                break
            except OSError:
                break
            info = parse_response(data)
            sender_ip = addr[0] if addr else ""

            srv_by_name = {name.rstrip("."): (port, target) for name, port, target in info["srv"]}
            a_by_name = {name.rstrip("."): ip for name, ip in info["a"]}

            for _name, instance in info["ptr"]:
                inst = instance.rstrip(".")
                if service.rstrip(".") not in inst:
                    continue
                srv = srv_by_name.get(inst)
                if not srv:
                    continue
                port, host = srv
                ip = a_by_name.get(host.rstrip("."), "")
                if not ip:
                    # Fall back to any A record, then to whoever answered us —
                    # the mDNS responder lives on the phone itself.
                    ip = next(iter(a_by_name.values()), "") or sender_ip
                if ip and (ip, port) not in found:
                    found.append((ip, port))
        return found
    finally:
        sock.close()


def discover(service: str = SERVICE_CONNECT, attempts: int = 3) -> list[tuple[str, int]]:
    targets = [MDNS_ADDR, "127.0.0.1", *local_ips()]
    # de-dupe while keeping order
    seen: set[str] = set()
    ordered = [t for t in targets if not (t in seen or seen.add(t))]

    for attempt in range(attempts):
        found = query_once(ordered, timeout=2.5, service=service)
        if found:
            return found
        if attempt < attempts - 1:
            time.sleep(1)
    return []


def scan_open_ports(
    ip: str,
    start: int = 30000,
    end: int = 50000,
    workers: int = 512,
    timeout: float = 0.2,
) -> list[int]:
    """Return ports on `ip` that accept a TCP connection.

    Used when the pairing service is not advertised over mDNS: while the
    pairing dialog is open, adbd listens on a fresh high port. The scan has
    to finish well inside the pairing code's lifetime, hence the wide
    thread pool and short timeout (closed ports answer with RST at once).
    """
    import concurrent.futures

    def probe(port: int) -> int | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            if sock.connect_ex((ip, port)) == 0:
                return port
        except OSError:
            return None
        finally:
            sock.close()
        return None

    open_ports: list[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(probe, range(start, end + 1), chunksize=64):
            if result is not None:
                open_ports.append(result)
    return sorted(open_ports)


# ---------------------------------------------------------------------------
def adb_devices() -> str:
    try:
        proc = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=20)
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def device_is_online(text: str) -> bool:
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return True
    return False


def transport_state(target: str) -> str:
    """State adb reports for one transport: device / offline / unauthorized / ''."""
    for line in adb_devices().splitlines():
        parts = line.replace("\r", "").split()
        if len(parts) >= 2 and parts[0] == target and parts[0] != "List":
            return parts[1]
    return ""


def disconnect(target: str) -> None:
    try:
        subprocess.run(
            ["adb", "disconnect", target], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        pass


def try_connect(hosts: list[str], port: int, wait: float = 4.0) -> tuple[bool, str]:
    """Try adb connect for each host and wait until the transport is really 'device'.

    adb prints "connected to X" before the TLS handshake finishes, so the
    message proves nothing. A transport that never leaves 'offline' is a ghost
    (usually some other app's socket, or a stale port) and is dropped at once:
    leaving them behind makes every later attempt worse.
    """
    last = ""
    for host in hosts:
        target = f"{host}:{port}"
        print(f"ลอง {target} ...", flush=True)
        try:
            proc = subprocess.run(
                ["adb", "connect", target], capture_output=True, text=True, timeout=25
            )
        except (OSError, subprocess.SubprocessError) as exc:
            last = str(exc)
            print(f"  {last}")
            continue

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        last = out or err
        if last:
            print(f"  {last}")

        lowered = last.lower()
        if "unauthorized" in lowered:
            print("  → ดูหน้าจอมือถือ กด Allow")
        if any(word in lowered for word in ("refused", "failed", "cannot", "unable")):
            print("  → พอร์ตนี้ไม่มีอะไรรอรับ (อาจเก่าไปแล้ว)")
            disconnect(target)
            continue

        deadline = time.time() + wait
        state = ""
        while time.time() < deadline:
            state = transport_state(target)
            if state == "device":
                return True, last
            if state == "unauthorized":
                print("  → รอการอนุญาตบนมือถือ (Allow USB debugging)")
            time.sleep(0.4)

        print(f"  → ค้างที่ '{state or 'unknown'}' — ตัดทิ้ง")
        disconnect(target)
    return False, last


def scan_candidates(exclude: set[int], limit: int = 40) -> list[tuple[str, int]]:
    """TCP-probe the wireless-debugging port range on addresses of this device.

    Probing only says "somebody listens here"; try_connect() decides whether it
    is really adbd. Loopback goes first because it answers instantly.
    """
    hosts = local_ips(include_loopback=False)
    loopback = [ip for ip in local_ips(include_loopback=True) if ip.startswith("127.")]

    found: list[tuple[str, int]] = []
    for ip in hosts:
        print(f"  สแกน {ip} ...", flush=True)
        try:
            ports = scan_open_ports(ip, 30000, 50000)
        except (OSError, subprocess.SubprocessError):
            continue
        found.extend((ip, port) for port in ports if port not in exclude)
        if found:
            return found[:limit]

    # Loopback only when no real interface answered: every app on the phone has
    # a socket here, so it is the slowest and noisiest place to look.
    for ip in loopback:
        print(f"  สแกน {ip} ...", flush=True)
        try:
            ports = scan_open_ports(ip, 30000, 50000)
        except (OSError, subprocess.SubprocessError):
            continue
        found.extend((ip, port) for port in ports if port not in exclude)
        if found:
            break
    return found[:limit]


def fmt_pairs(pairs: list[tuple[str, int]]) -> str:
    return "\n".join(f"{ip}:{port}" for ip, port in pairs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="หา ADB wireless port ผ่าน mDNS")
    parser.add_argument("--connect", action="store_true", help="สั่ง adb connect ให้เลย")
    parser.add_argument(
        "--pair",
        action="store_true",
        help="หาพอร์ตสำหรับ adb pair (ใช้ตอนเปิดกล่อง 'จับคู่กับอุปกรณ์')",
    )
    parser.add_argument("--ip", default="", help="ระบุ IP เอง (ปกติตรวจอัตโนมัติ)")
    parser.add_argument(
        "--scan-pair",
        action="store_true",
        help="สแกนหาพอร์ต pair (ใช้เมื่อ mDNS ไม่ประกาศ)",
    )
    parser.add_argument("--port-start", type=int, default=30000)
    parser.add_argument("--port-end", type=int, default=50000)
    parser.add_argument("--exclude", default="", help="พอร์ตที่ไม่ต้องลอง (เช่น พอร์ต connect)")
    parser.add_argument(
        "--hosts",
        action="store_true",
        help="พิมพ์ IP ทั้งหมดของเครื่องนี้ (Tailscale ก่อน แล้ว Wi-Fi แล้ว loopback)",
    )
    parser.add_argument("--timeout", type=float, default=2.5)
    args = parser.parse_args(argv)

    if args.hosts:
        explicit = os.environ.get("ADB_HOST", "").strip()
        listed = local_ips(include_loopback=True)
        if explicit and explicit not in listed:
            listed.insert(0, explicit)
        for ip in listed:
            print(ip)
        return 0

    if args.scan_pair:
        ip = args.ip or (local_ips() or ["127.0.0.1"])[0]
        print(f"กำลังสแกนพอร์ต {args.port_start}-{args.port_end} บน {ip} ...", flush=True)
        exclude = {int(x) for x in args.exclude.replace(",", " ").split() if x.isdigit()}
        ports = [
            p
            for p in scan_open_ports(ip, args.port_start, args.port_end)
            if p not in exclude
        ]
        for port in ports:
            print(f"{ip}:{port}")
        return 0 if ports else 1

    if args.pair:
        # The pairing service only exists while the pairing dialog is open.
        print("กำลังค้นหาพอร์ต pair ผ่าน mDNS ...", flush=True)
        pairs = discover(SERVICE_PAIR, attempts=2)
        if not pairs:
            print("ไม่พบพอร์ต pair (กล่องจับคู่อาจปิดอยู่)", file=sys.stderr)
            return 1
        print(fmt_pairs(pairs))
        return 0

    print("กำลังค้นหาผ่าน mDNS ...", flush=True)
    pairs = discover()

    if not pairs:
        print("ไม่พบผ่าน mDNS (อาจถูกบล็อก/ไม่ทำงานบนเครื่องนี้)", file=sys.stderr)
        if not args.connect:
            return 1
    else:
        print(fmt_pairs(pairs))

    if not args.connect:
        return 0

    tried: set[int] = set()

    # Termux runs on the phone itself: the loopback route often works when the
    # LAN route does not (and vice versa), so try both for every discovered port.
    for ip, port in pairs:
        tried.add(port)
        hosts = ["127.0.0.1", ip] if ip != "127.0.0.1" else ["127.0.0.1"]
        ok, _ = try_connect(hosts, port)
        if ok:
            print("\n✓ เชื่อมต่อสำเร็จ")
            print(adb_devices().strip())
            return 0

    # mDNS on Android is unreliable (stale records, blocked multicast), so fall
    # back to probing the port range and letting adb itself decide.
    print("\nmDNS ไม่ได้ผล — สแกนพอร์ตแทน", flush=True)
    candidates = scan_candidates(tried)
    if not candidates:
        print("ไม่พบพอร์ตที่เปิดอยู่เลย", file=sys.stderr)
        return 1

    for ip, port in candidates:
        hosts = ["127.0.0.1", ip] if ip != "127.0.0.1" else ["127.0.0.1"]
        ok, _ = try_connect(hosts, port, wait=2.5)
        if ok:
            print("\n✓ เชื่อมต่อสำเร็จ")
            print(adb_devices().strip())
            return 0

    print("\n✗ เชื่อมต่อไม่สำเร็จทุกพอร์ตที่เจอ", file=sys.stderr)
    print("   ลองอ่านพอร์ตจากหน้า Wireless debugging แล้วสั่งเอง:", file=sys.stderr)
    print("     adb connect localhost:<พอร์ต>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
