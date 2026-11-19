"""Thin ctypes wrappers for the Windows calls the app needs.

Restart Manager (which process holds a file open), GDI font resources, WM_FONTCHANGE broadcast,
MoveFileEx delete-on-reboot, admin check / relaunch elevated, dark title bar.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if IS_WIN:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    gdi32.AddFontResourceW.argtypes = [wintypes.LPCWSTR]
    gdi32.RemoveFontResourceW.argtypes = [wintypes.LPCWSTR]
    kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.MoveFileExW.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    shell32.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.LPCWSTR, ctypes.c_int]
    shell32.ShellExecuteW.restype = ctypes.c_void_p


# ---------------------------------------------------------------- admin

def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args=()):
    """Start this app again elevated (UAC prompt). Returns True when the new copy was started."""
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, list(extra_args)
    else:
        from pathlib import Path
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        args = [str(Path(__file__).resolve().parent.parent / "run.py"), *extra_args]
    params = subprocess.list2cmdline(args)
    r = shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return (r or 0) > 32


# ---------------------------------------------------------------- font resources

HWND_BROADCAST = 0xFFFF
WM_FONTCHANGE = 0x001D
SMTO_ABORTIFHUNG = 0x0002


def remove_font_resource(path, max_tries=8):
    """Unload a font file from this session (it may have been added several times). Returns how many times."""
    n = 0
    for _ in range(max_tries):
        if not gdi32.RemoveFontResourceW(str(path)):
            break
        n += 1
    return n


def add_font_resource(path):
    return gdi32.AddFontResourceW(str(path))


def broadcast_font_change():
    res = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, 1500, ctypes.byref(res))


# ---------------------------------------------------------------- delete on reboot

MOVEFILE_REPLACE_EXISTING = 0x1
MOVEFILE_DELAY_UNTIL_REBOOT = 0x4


def delete_on_reboot(path):
    """Queue `path` for deletion at the next restart (PendingFileRenameOperations). Needs admin."""
    ok = kernel32.MoveFileExW(str(path), None, MOVEFILE_DELAY_UNTIL_REBOOT)
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


# ---------------------------------------------------------------- Restart Manager: who has this file open?

if IS_WIN:
    rstrtmgr = ctypes.WinDLL("rstrtmgr")

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [("Process", RM_UNIQUE_PROCESS),
                    ("strAppName", wintypes.WCHAR * 256),
                    ("strServiceShortName", wintypes.WCHAR * 64),
                    ("ApplicationType", ctypes.c_int),
                    ("AppStatus", wintypes.ULONG),
                    ("TSSessionId", wintypes.DWORD),
                    ("bRestartable", wintypes.BOOL)]

APP_TYPES = {0: "unknown", 1: "app", 2: "app", 3: "service", 4: "explorer", 5: "console", 1000: "critical"}
ERROR_MORE_DATA = 234


def lockers(paths):
    """Processes that have any of `paths` open: [{pid, name, service, kind}]. Empty list when nothing locks them."""
    paths = [str(p) for p in paths if p]
    if not paths:
        return []
    handle = wintypes.DWORD(0)
    key = (wintypes.WCHAR * 33)()
    if rstrtmgr.RmStartSession(ctypes.byref(handle), 0, key):
        return []
    try:
        arr = (wintypes.LPCWSTR * len(paths))(*paths)
        if rstrtmgr.RmRegisterResources(handle, len(paths), arr, 0, None, 0, None):
            return []
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        rc = rstrtmgr.RmGetList(handle, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        if rc not in (0, ERROR_MORE_DATA) or needed.value == 0:
            return []
        for _ in range(3):
            info = (RM_PROCESS_INFO * needed.value)()
            count = wintypes.UINT(needed.value)
            rc = rstrtmgr.RmGetList(handle, ctypes.byref(needed), ctypes.byref(count), info, ctypes.byref(reasons))
            if rc == 0:
                break
            if rc != ERROR_MORE_DATA:
                return []
        out = []
        for i in range(count.value):
            p = info[i]
            out.append({"pid": p.Process.dwProcessId, "name": p.strAppName,
                        "service": p.strServiceShortName or "", "kind": APP_TYPES.get(p.ApplicationType, "unknown")})
        _add_exe_names(out)
        return out
    finally:
        rstrtmgr.RmEndSession(handle)


def _add_exe_names(items):
    try:
        import psutil
    except Exception:
        return
    for it in items:
        try:
            it["exe"] = psutil.Process(it["pid"]).name()
        except Exception:
            it["exe"] = ""


# ---------------------------------------------------------------- window chrome

def dark_title_bar(hwnd, caption_rgb=None):
    """Windows 10/11 dark title bar (and on Windows 11 a custom caption colour)."""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        val = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))
        if caption_rgb is not None:
            r, g, b = caption_rgb
            col = ctypes.c_int(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:
        pass
