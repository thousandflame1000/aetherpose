"""A best-effort latency hint for this Windows process, not a global power plan."""
import ctypes
import sys


class PowerState(ctypes.Structure):
    _fields_ = [('Version', ctypes.c_uint32), ('ControlMask', ctypes.c_uint32),
                ('StateMask', ctypes.c_uint32)]


def configure_cpu_latency(enabled=True, *, platform_name=None, api=None):
    platform_name = sys.platform if platform_name is None else platform_name
    if not enabled:
        return {'applied': False, 'reason': 'disabled'}
    if platform_name != 'win32':
        return {'applied': False, 'reason': 'not_windows'}
    try:
        if api is None:
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.GetCurrentProcess.argtypes = []
            api.GetCurrentProcess.restype = ctypes.c_void_p
            signature = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32]
            for name in ('GetProcessInformation', 'SetProcessInformation'):
                method = getattr(api, name)
                method.argtypes = signature
                method.restype = ctypes.c_int32
        handle = api.GetCurrentProcess()
        old = PowerState(1, 0, 0)
        if not api.GetProcessInformation(handle, 4, ctypes.byref(old), ctypes.sizeof(old)):
            raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'GetProcessInformation failed')
        # ProcessPowerThrottling=4, EXECUTION_SPEED=1. Preserve any unrelated
        # controls, including IGNORE_TIMER_RESOLUTION, rather than overwriting them.
        requested = PowerState(1, old.ControlMask | 1, old.StateMask & ~1)
        if not api.SetProcessInformation(handle, 4, ctypes.byref(requested), ctypes.sizeof(requested)):
            raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'SetProcessInformation failed')
        return {'applied': True, 'scope': 'current_process', 'mode': 'high_qos',
                'previous_control': old.ControlMask, 'previous_state': old.StateMask,
                'control': requested.ControlMask, 'state': requested.StateMask}
    except (OSError, AttributeError) as exc:
        # Unsupported/restricted Windows environments must still run inference.
        return {'applied': False, 'reason': str(exc)}
