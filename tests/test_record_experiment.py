"""Evidence calculations must not turn outages/resets into passing data."""
import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import websockets

spec = importlib.util.spec_from_file_location('record_experiment', Path(__file__).resolve().parents[1] / 'tools/record_experiment.py')
record = importlib.util.module_from_spec(spec)
spec.loader.exec_module(record)


def row(t, count=0, age=0, received=None, present=True):
    return {'elapsed_s': t, 'snapshot_received_s': t if received is None else received,
            'trackers': {'1': {'received_packets': count, 'last_update_ms': age,
                               'connection_type': 'BLE'}} if present else {}}


class EvidenceMath(unittest.TestCase):
    def test_source_and_assignment_checks_use_real_wire_spelling(self):
        sample = row(0)
        sample['trackers'] = {str(index): {'connection_type': 'Udp', 'assigned_bone': bone,
                                          'received_packets': 0, 'last_update_ms': 0}
                              for index, bone in enumerate(record.BODY_BONES)}
        summary = record.summarize([sample], list(range(6)), 1)
        self.assertEqual(record.source_warnings(summary, list(range(6)), 'simulated-udp'), [])
        self.assertEqual(len(record.source_warnings(summary, list(range(6)), 'physical-ble')), 6)
        self.assertFalse(summary['automatic_hardware_acceptance'])
        self.assertTrue(record.source_warnings(summary, list(reversed(range(6))), 'simulated-udp'))

    def test_regular_counters_and_percentile(self):
        result = record.summarize([row(i / 10, i * 10) for i in range(31)], [1, 2], 3.1)
        self.assertAlmostEqual(result['trackers']['1']['counter_rate_hz_p5'], 100)
        self.assertAlmostEqual(result['trackers']['1']['fresh_time_fraction_lower_estimate'], 1)
        self.assertEqual(result['trackers']['2']['rate_windows'], 0)
        self.assertEqual(result['trackers']['2']['fresh_time_fraction_lower_estimate'], 0)
        self.assertIsNone(result['trackers']['2']['counter_rate_hz_p5'])
        self.assertFalse(result['automatic_hardware_acceptance'])
        self.assertEqual(record.percentile([0, 100], 0.05), 5)

    def test_frozen_snapshot_expires_and_missing_time_is_not_fresh(self):
        rows = [row(0, received=0), row(1, received=0), row(2, received=0)]
        result = record.summarize(rows, [1], 3)['trackers']['1']
        self.assertAlmostEqual(result['fresh_time_fraction_lower_estimate'], 0.5 / 3)
        self.assertEqual(result['counter_rate_hz_p5'], 0)

    def test_counter_reset_and_tracker_disappearance(self):
        rows = [row(0, 100), row(.4, 200), row(.6, 150), row(1.6, 170),
                row(2, present=False), row(3, 500), row(4, 530)]
        result = record.summarize(rows, [1], 4.1)['trackers']['1']
        self.assertEqual(result['counter_resets_observed'], 1)
        self.assertEqual(result['rate_windows'], 2)
        self.assertAlmostEqual(result['counter_rate_hz_p5'], 20.5)


class CaptureIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_requests_and_outage_evidence(self):
        requests = []

        async def handler(socket):
            async for message in socket:
                requests.append(json.loads(message))
                await socket.send(json.dumps({'type': 'Snapshot', 'data': {
                    'trackers': row(0)['trackers'], 'packet_count': 1, 'ble_status': 'test'}}))
                # Disconnect after one response. Recorder must retain the outage,
                # not extrapolate the single fresh packet through the run.
                await socket.close()
                return

        with tempfile.TemporaryDirectory() as directory:
            async with websockets.serve(handler, '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                path = Path(directory) / 'samples.jsonl'
                rows, duration = await record.capture(f'ws://127.0.0.1:{port}', 1, .1, path)
            saved = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(saved, rows)
            self.assertGreaterEqual(duration, 1)
            self.assertEqual(requests, ['RequestSnapshot'])
            self.assertTrue(any(sample['connection_error'] for sample in rows))
            self.assertLess(record.summarize(rows, [1], duration)['trackers']['1']['fresh_time_fraction_lower_estimate'], .6)


if __name__ == '__main__':
    unittest.main()
