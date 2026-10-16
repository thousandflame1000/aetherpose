"""The latency hint is limited to this process and preserves other policy bits."""
import ctypes
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('cpu_latency', Path(__file__).resolve().parents[1] / 'frontend/cpu_latency.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Api:
    def __init__(self, read=True, write=True):
        self.read, self.write, self.calls = read, write, []
    def GetCurrentProcess(self): return 42
    def GetProcessInformation(self, handle, kind, state, size):
        self.calls.append(('read', handle, kind, size))
        state._obj.ControlMask = 5
        state._obj.StateMask = 5
        return self.read
    def SetProcessInformation(self, handle, kind, state, size):
        self.calls.append(('write', handle, kind, size, state._obj.ControlMask, state._obj.StateMask))
        return self.write


class LatencyTests(unittest.TestCase):
    def test_preserves_unrelated_flags_and_targets_current_process_only(self):
        api = Api()
        result = module.configure_cpu_latency(platform_name='win32', api=api)
        self.assertTrue(result['applied'])
        self.assertEqual(api.calls, [('read', 42, 4, 12), ('write', 42, 4, 12, 5, 4)])
        self.assertEqual(result['previous_state'], 5)
        self.assertEqual(result['scope'], 'current_process')

    def test_disabled_and_other_platforms_do_not_call_windows(self):
        for enabled, platform in [(False, 'win32'), (True, 'linux'), (True, 'darwin')]:
            api = Api()
            result = module.configure_cpu_latency(enabled, platform_name=platform, api=api)
            self.assertFalse(result['applied'])
            self.assertEqual(api.calls, [])

    def test_unsupported_read_never_attempts_to_set_policy(self):
        api = Api(read=False)
        result = module.configure_cpu_latency(platform_name='win32', api=api)
        self.assertFalse(result['applied'])
        self.assertEqual(len(api.calls), 1)
        self.assertIn('GetProcessInformation', result['reason'])

    def test_denied_write_is_reported_without_stopping_inference(self):
        result = module.configure_cpu_latency(platform_name='win32', api=Api(write=False))
        self.assertFalse(result['applied'])
        self.assertIn('SetProcessInformation', result['reason'])


if __name__ == '__main__':
    unittest.main()
