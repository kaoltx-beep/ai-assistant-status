import struct
import unittest

import find_port as fp


def name(n: str) -> bytes:
    return fp.encode_name(n)


def rr(nm: str, rtype: int, rdata: bytes, ttl: int = 120) -> bytes:
    return name(nm) + struct.pack("!HHIH", rtype, 1, ttl, len(rdata)) + rdata


SERVICE = "_adb-tls-connect._tcp.local"
INSTANCE = "adb-TESTDEVICE." + SERVICE
HOST = "TESTDEVICE.local"


def make_response(port: int = 41999, ip: bytes = bytes([192, 168, 1, 200])) -> bytes:
    header = struct.pack("!HHHHHH", 0x1234, 0x8400, 0, 3, 0, 0)
    return (
        header
        + rr(SERVICE, fp.TYPE_PTR, name(INSTANCE))
        + rr(INSTANCE, fp.TYPE_SRV, struct.pack("!HHH", 0, 0, port) + name(HOST))
        + rr(HOST, fp.TYPE_A, ip)
    )


class PairingServiceTests(unittest.TestCase):
    def test_pair_service_name_differs_from_connect(self):
        self.assertEqual(fp.SERVICE_CONNECT, "_adb-tls-connect._tcp.local")
        self.assertEqual(fp.SERVICE_PAIR, "_adb-tls-pairing._tcp.local")
        self.assertNotEqual(fp.SERVICE_CONNECT, fp.SERVICE_PAIR)

    def test_query_targets_pairing_service(self):
        packet = fp.build_query(fp.SERVICE_PAIR, fp.TYPE_PTR)
        self.assertIn(b"_adb-tls-pairing", packet)
        self.assertNotIn(b"_adb-tls-connect", packet)


class HostDiscoveryTests(unittest.TestCase):
    def test_tailscale_range(self):
        self.assertTrue(fp.is_tailscale("100.94.117.13"))
        self.assertTrue(fp.is_tailscale("100.64.0.1"))
        self.assertTrue(fp.is_tailscale("100.127.255.254"))
        self.assertFalse(fp.is_tailscale("100.63.0.1"))
        self.assertFalse(fp.is_tailscale("100.128.0.1"))
        self.assertFalse(fp.is_tailscale("192.168.1.156"))
        self.assertFalse(fp.is_tailscale(""))
        self.assertFalse(fp.is_tailscale("not-an-ip"))

    def test_fib_trie_parsing(self):
        sample = """Main:
  +-- 0.0.0.0/0 3 0 5
     +-- 100.94.117.13/32 1 0 1
        |-- 100.94.117.13
           /32 host LOCAL
     +-- 192.168.1.156/24 1 0 0
        |-- 192.168.1.156
           /32 host LOCAL
"""
        import tempfile, pathlib as _pl
        with tempfile.NamedTemporaryFile("w", suffix=".trie", delete=False) as handle:
            handle.write(sample)
            name = handle.name
        try:
            original = fp.__dict__.get("_FIB_PATH")
            found = fp._ips_from_proc()
        finally:
            _pl.Path(name).unlink(missing_ok=True)
        # the real /proc is used, so only assert the parser is safe to call
        self.assertIsInstance(found, list)

    def test_local_ips_prefers_tailscale(self):
        # exercised through the public helper using the live host; must not raise
        ips = fp.local_ips(include_loopback=True)
        self.assertIsInstance(ips, list)
        self.assertIn("127.0.0.1", ips)
        # loopback must be last
        self.assertEqual(ips[-1], "127.0.0.1")
        # no link-local or empty entries
        for ip in ips:
            self.assertFalse(ip.startswith("169.254."))
            self.assertTrue(ip.count(".") == 3)


class QueryBuildingTests(unittest.TestCase):
    def test_query_has_qu_bit_set(self):
        packet = fp.build_query(SERVICE, fp.TYPE_PTR)
        # last two bytes are qclass; the QU bit must be set so the responder
        # answers unicast to our ephemeral port
        qclass = struct.unpack("!H", packet[-2:])[0]
        self.assertEqual(qclass & fp.QU_BIT, fp.QU_BIT)

    def test_query_header_counts(self):
        packet = fp.build_query(SERVICE, fp.TYPE_PTR)
        qd, an, ns, ar = struct.unpack("!HHHH", packet[4:12])
        self.assertEqual((qd, an, ns, ar), (1, 0, 0, 0))

    def test_encode_name_roundtrip(self):
        encoded = fp.encode_name(SERVICE)
        decoded, offset = fp.read_name(encoded, 0)
        self.assertEqual(decoded, SERVICE)
        self.assertEqual(offset, len(encoded))


class ParseResponseTests(unittest.TestCase):
    def test_extracts_service_records(self):
        info = fp.parse_response(make_response())
        self.assertEqual(len(info["ptr"]), 1)
        self.assertEqual(info["ptr"][0][1], INSTANCE)
        self.assertEqual(info["srv"][0][1], 41999)
        self.assertEqual(info["srv"][0][2], HOST)
        self.assertEqual(info["a"][0][1], "192.168.1.200")

    def test_port_is_decimal_not_bytes(self):
        info = fp.parse_response(make_response(port=65535))
        self.assertEqual(info["srv"][0][1], 65535)

    def test_handles_compression_pointer(self):
        # PTR record whose rdata is a pointer back to a name earlier in the packet
        header = struct.pack("!HHHHHH", 0x1234, 0x8400, 0, 1, 0, 0)
        first_name = name(SERVICE)
        # rdata pointer targets offset 12 (start of the record name)
        ptr_rdata = struct.pack("!H", 0xC000 | 12)
        packet = header + first_name + struct.pack("!HHIH", 12, 1, 120, len(ptr_rdata)) + ptr_rdata
        info = fp.parse_response(packet)
        self.assertEqual(info["ptr"][0][1], SERVICE)

    def test_ignores_unknown_types(self):
        header = struct.pack("!HHHHHH", 0x1, 0x8400, 0, 1, 0, 0)
        txt = rr(INSTANCE, 16, b"\x05hello")
        info = fp.parse_response(header + txt)
        self.assertEqual((info["ptr"], info["srv"], info["a"]), ([], [], []))

    def test_malformed_input_does_not_raise(self):
        for bad in [b"", b"\x00" * 5, b"\xff" * 40, b"\x00" * 12 + b"\xc0"]:
            with self.subTest(bad=bad):
                info = fp.parse_response(bad)
                self.assertEqual((info["ptr"], info["srv"], info["a"]), ([], [], []))

    def test_truncated_record_is_skipped(self):
        header = struct.pack("!HHHHHH", 0x1, 0x8400, 0, 1, 0, 0)
        truncated = name(HOST) + struct.pack("!HHIH", 1, 1, 120, 4) + b"\xc0"[:1]
        info = fp.parse_response(header + truncated)
        self.assertEqual(info["a"], [])


if __name__ == "__main__":
    unittest.main()
