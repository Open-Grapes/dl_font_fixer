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


# ---------------------------------------------------------------- start programs as the normal (non-admin) user

if IS_WIN:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.CreateProcessWithTokenW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPCWSTR,
                                                 wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                                 wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                                 ctypes.POINTER(PROCESS_INFORMATION)]
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def shell_token():
    """A copy of the desktop shell's (explorer's) access token: the user's normal, non-elevated rights.
    Take it *before* killing Explorer to restart it later. Returns a handle or None."""
    if not IS_WIN:
        return None
    pid = wintypes.DWORD(0)
    hwnd = user32.GetShellWindow()
    if hwnd:
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        try:
            import psutil
            me = psutil.Process().username()
            pid.value = next(p.pid for p in psutil.process_iter(["name", "username"])
                             if (p.info["name"] or "").lower() == "explorer.exe" and p.info["username"] == me)
        except Exception:
            return None
    hproc = kernel32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not hproc:
        return None
    tok, dup = wintypes.HANDLE(), wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(hproc, 0x0002, ctypes.byref(tok)):     # TOKEN_DUPLICATE
            return None
        # TOKEN_QUERY | DUPLICATE | ASSIGN_PRIMARY | ADJUST_DEFAULT | ADJUST_SESSIONID, SecurityImpersonation, Primary
        if not advapi32.DuplicateTokenEx(tok, 0x0008 | 0x0002 | 0x0001 | 0x0080 | 0x0100, None, 2, 1,
                                         ctypes.byref(dup)):
            return None
        return dup
    finally:
        if tok:
            kernel32.CloseHandle(tok)
        kernel32.CloseHandle(hproc)


def run_as_user(cmd, cwd=None, token=None):
    """Start `cmd` (list) with the user's normal rights even when this app runs as administrator, so
    Creative Cloud / Explorer don't end up running elevated. Falls back to a plain start."""
    if is_admin():
        tok = token or shell_token()
        if tok:
            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(si)
            pi = PROCESS_INFORMATION()
            line = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(c) for c in cmd]))
            ok = advapi32.CreateProcessWithTokenW(tok, 0, None, line, 0, None, cwd, ctypes.byref(si),
                                                  ctypes.byref(pi))
            if token is None:
                kernel32.CloseHandle(tok)
            if ok:
                kernel32.CloseHandle(pi.hThread)
                kernel32.CloseHandle(pi.hProcess)
                return True
    subprocess.Popen([str(c) for c in cmd], cwd=cwd, creationflags=NO_WINDOW)
    return False


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


# ---------------------------------------------------------------- Recycle Bin

if IS_WIN:
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]

FO_DELETE = 3
# FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
_RECYCLE_FLAGS = 0x0004 | 0x0010 | 0x0040 | 0x0400


def recycle(path):
    """Move a file to the Recycle Bin (silently). True when the file is gone from `path`."""
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path) + "\0"            # double-null terminated list
    op.fFlags = _RECYCLE_FLAGS
    try:
        rc = shell32.SHFileOperationW(ctypes.byref(op))
    except OSError:
        return False
    return rc == 0 and not op.fAnyOperationsAborted and not os.path.exists(path)


def _read_recycle_info(i_path):
    """Original path and deletion time from a Recycle Bin $I file: (path, unix_time) or None."""
    import struct
    try:
        data = open(i_path, "rb").read()
        version, _size, ft = struct.unpack_from("<qqq", data, 0)
        if version == 2:
            n = struct.unpack_from("<i", data, 24)[0]
            orig = data[28:28 + 2 * n].decode("utf-16-le")
        else:
            orig = data[24:24 + 520].decode("utf-16-le")
        return orig.split("\0", 1)[0], ft / 1e7 - 11644473600
    except Exception:
        return None


def find_in_recycle_bin(original, since=0.0):
    """Where the Recycle Bin keeps `original` after recycle(): ($R data file, $I info file) or (None, None).
    Picks the newest match deleted at or after `since`."""
    drive = os.path.splitdrive(str(original))[0] or "C:"
    root = os.path.join(drive + os.sep, "$Recycle.Bin")
    want = os.path.normcase(os.path.normpath(str(original)))
    best = None
    try:
        sid_dirs = [e.path for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return None, None
    for d in sid_dirs:
        try:
            infos = [e for e in os.scandir(d) if e.name.upper().startswith("$I")]
        except OSError:
            continue
        for e in infos:
            meta = _read_recycle_info(e.path)
            if not meta or os.path.normcase(os.path.normpath(meta[0])) != want or meta[1] < since - 5:
                continue
            r = os.path.join(d, "$R" + e.name[2:])
            if os.path.exists(r) and (best is None or meta[1] > best[0]):
                best = (meta[1], r, e.path)
    return (best[1], best[2]) if best else (None, None)


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

def dark_title_bar(hwnd, caption_rgb=None, dark=True):
    """Windows 10/11 dark (or light) title bar, and on Windows 11 a custom caption colour."""
    try:
        dwm = ctypes.WinDLL("dwmapi")
        val = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))
        if caption_rgb is not None:
            r, g, b = caption_rgb
            col = ctypes.c_int(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:
        pass


def move_back(src, dst):
    """Put a file from the Recycle Bin back where it was."""
    import shutil
    from pathlib import Path
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dst)


def reveal(path):
    """Show a file selected in Explorer."""
    subprocess.Popen(["explorer.exe", "/select,", str(path)])
