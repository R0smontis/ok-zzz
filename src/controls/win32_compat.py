"""Keep the overlay's ctypes signatures private to its own DLL objects."""
import ctypes
import importlib
import sys


def install_win32_compat():
    name = 'ok.ui.overlay.win32_gdi'
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, '_zzz_private_dlls', False):
        return
    snapshots = {}
    for name_dll in ('user32', 'gdi32', 'kernel32'):
        shared = getattr(ctypes.windll, name_dll)
        snapshots[name_dll] = {key: (value.argtypes, value.restype)
            for key, value in vars(shared).items() if isinstance(value, ctypes._CFuncPtr)}
    module = importlib.import_module(name)
    for name_dll, previous in snapshots.items():
        shared = getattr(module, name_dll)
        private = ctypes.WinDLL(name_dll, use_last_error=True)
        for key, function in list(vars(shared).items()):
            if not isinstance(function, ctypes._CFuncPtr):
                continue
            local = getattr(private, key)
            local.argtypes, local.restype = function.argtypes, function.restype
            if existing is None:
                function.argtypes, function.restype = previous.get(key, (None, ctypes.c_int))
            elif function.argtypes:
                # An already imported overlay can have left incompatible POINT/RECT
                # classes on the shared API. Their ABI is identical; accept pointers.
                function.argtypes = [ctypes.c_void_p if isinstance(arg, type)
                    and issubclass(arg, ctypes._Pointer) else arg for arg in function.argtypes]
        setattr(module, name_dll, private)
    module._zzz_private_dlls = True
