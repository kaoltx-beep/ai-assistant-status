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
import random
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
def local_ips() -> list[str]:
    ips: list[str] = []
    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                ip = parts[parts.index("inet") + 1].split("/")[0]
                if not ip.startswith("127."):
                    ips.append(ip)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    if not ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("1.1.1.1", 53))
            ips.append(sock.getsockname()[0])
            sock.close()
        except OSError:
            pass
    return ips


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


def try_connect(hosts: list[str], port: int) -> tuple[bool, str]:
    """Try adb connect for each host; return (ok, last_output)."""
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
        if "connected" in lowered and "failed" not in lowered and "cannot" not in lowered:
            if device_is_online(adb_devices()):
                return True, last
        if "unauthorized" in lowered:
            print("  → ดูหน้าจอมือถือ กด Allow")
        if "refused" in lowered:
            print("  → พอร์ตนี้ไม่มีอะไรรอรับ (อาจเก่าไปแล้ว)")
    return False, last


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
    parser.add_argument("--timeout", type=float, default=2.5)
    args = parser.parse_args(argv)

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
        print("ไม่พบ (mDNS อาจถูกบล็อก/ไม่ทำงานบนเครื่องนี้)", file=sys.stderr)
        return 1

    print(fmt_pairs(pairs))

    if not args.connect:
        return 0

    # Termux runs on the phone itself: the loopback route often works when the
    # LAN route does not (and vice versa), so try both for every discovered port.
    for ip, port in pairs:
        hosts = ["127.0.0.1", ip] if ip != "127.0.0.1" else ["127.0.0.1"]
        ok, _ = try_connect(hosts, port)
        if ok:
            print("\n✓ เชื่อมต่อสำเร็จ")
            print(adb_devices().strip())
            return 0

    print("\n✗ เชื่อมต่อไม่สำเร็จทุกพอร์ตที่เจอ", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
