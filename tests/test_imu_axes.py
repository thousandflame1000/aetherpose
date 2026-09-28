import binascii
import math
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from imu_axes import FrameDecoder, LiveState, PACKET, unit_quaternion


def frame(quat=(0, 0, 0, 1), gyro=(0.1, 0.2, 0.3), sequence=42):
    payload = PACKET.pack(4, 76, sequence, *gyro, 0, 0, 9.81, 80,
                          20, 5, -40, 1/119, *quat)
    return b"\xaa\x55\x3d" + payload + struct.pack("<H", binascii.crc_hqx(payload, 0xFFFF))


class DecoderTests(unittest.TestCase):
    def test_packet_layout_and_axes(self):
        self.assertEqual(PACKET.size, 61)
        packet = FrameDecoder().feed(frame())[0]
        self.assertEqual(packet["id"], 76)
        self.assertEqual(packet["sequence"], 42)
        self.assertEqual(packet["quat"], [0, 0, 0, 1])
        self.assertEqual(packet["mag"], (20, 5, -40))
        self.assertAlmostEqual(packet["accel"][2], 9.81, places=5)
        self.assertAlmostEqual(packet["dt"], 1/119, places=7)

    def test_every_possible_split(self):
        raw = frame()
        for split in range(1, len(raw)):
            decoder = FrameDecoder()
            self.assertEqual(decoder.feed(raw[:split]), [])
            self.assertEqual(len(decoder.feed(raw[split:])), 1)

    def test_noise_crc_recovery_and_coalescing(self):
        broken = bytearray(frame())
        broken[12] ^= 0xFF
        decoder = FrameDecoder()
        packets = decoder.feed(b"noise\xaa" + broken + frame() + frame(sequence=43))
        self.assertEqual([p["sequence"] for p in packets], [42, 43])
        self.assertEqual(decoder.errors, 1)

    def test_invalid_sensor_or_quaternion_rejected(self):
        for raw in [frame(quat=(math.nan, 0, 0, 1)), frame(quat=(0, 0, 0, 0)),
                    frame(gyro=(math.inf, 0, 0))]:
            decoder = FrameDecoder()
            self.assertEqual(decoder.feed(raw), [])
            self.assertEqual(decoder.errors, 1)
            self.assertEqual(len(decoder.feed(frame())), 1)

    def test_bytewise_and_sequence_wrap(self):
        decoder = FrameDecoder()
        packets = []
        for value in frame(sequence=65535) + frame(sequence=0):
            packets.extend(decoder.feed(bytes([value])))
        self.assertEqual([p["sequence"] for p in packets], [65535, 0])

    def test_reference_quaternion_order(self):
        # 90 degrees around +Z, stored x/y/z/w.
        q = unit_quaternion([0, 0, 2**0.5, 2**0.5])
        self.assertAlmostEqual(q[2], math.sqrt(0.5))
        self.assertAlmostEqual(q[3], math.sqrt(0.5))

    def test_state_preserves_last_valid_and_reports_staleness(self):
        state = LiveState("test")
        state.accept(dict(quat=[0, 0, 0, 1]), age=2)
        state.accept(dict(quat=[math.nan, 0, 0, 1]))
        snapshot = state.snapshot()
        self.assertGreaterEqual(snapshot["age_ms"], 1999)
        self.assertEqual(snapshot["quat"], [0, 0, 0, 1])
        self.assertEqual(snapshot["received"], 1)
        self.assertEqual(snapshot["errors"], 1)


if __name__ == "__main__":
    unittest.main()
