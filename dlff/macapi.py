"""macOS versions of the system calls in winapi.py (same names, so the rest of the app doesn't care).

Fonts on a Mac have no registry: a font is installed when its file is in ~/Library/Fonts (you) or
/Library/Fonts (all users). Deleting moves the file to the Trash; /Library/Fonts needs an administrator
password, which macOS asks for in its own dialog.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

NO_WINDOW = 0
TRASH = Path.home() / ".Trash"
_TRASHED = {}       # original path -> where recycle() put it


def is_admin():
    return os.geteuid() == 0


def relaunch_as_admin(extra_args=()):
    return False


def _as_admin(cmd):
    """Run a shell command with administrator rights (macOS shows its password dialog). True on success."""
    script = "do shell script " + _applescript_str(cmd) + " with administrator privileges"
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode == 0


def _applescript_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _writable(path):
    return os.access(os.path.dirname(str(path)) or ".", os.W_OK)


def _trash_target(path):
    TRASH.mkdir(exist_ok=True)
    p = Path(path)
    dst = TRASH / p.name
    i = 1
    while dst.exists():
        dst = TRASH / f"{p.stem} {i}{p.suffix}"
        i += 1
    return dst


def recycle(path):
    """Move a font file to the Trash. True when it's gone from `path`."""
    dst = _trash_target(path)
    try:
        if _writable(path):
            shutil.move(str(path), dst)
        else:
            # /Library/Fonts: move it as administrator, then give the file back to the user so it can be restored
            user = os.environ.get("USER") or ""
            cmd = f"mv {shlex.quote(str(path))} {shlex.quote(str(dst))}"
            if user:
                cmd += f" && chown {shlex.quote(user)} {shlex.quote(str(dst))}"
            if not _as_admin(cmd):
                return False
    except OSError:
        return False
    if os.path.exists(path):
        return False
    _TRASHED[str(path)] = str(dst)
    return True


def find_in_recycle_bin(original, since=0.0):
    """Where recycle() put `original` in the Trash: (file, None) or (None, None)."""
    dst = _TRASHED.pop(str(original), None)
    return (dst, None) if dst and os.path.exists(dst) else (None, None)


def move_back(src, dst):
    """Put a file from the Trash back where it was (asks for the administrator password for /Library/Fonts)."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True) if _writable(dst) else None
    if _writable(dst):
        shutil.move(src, dst)
        return
    cmd = f"mv {shlex.quote(str(src))} {shlex.quote(str(dst))} && chown root:wheel {shlex.quote(str(dst))}"
    if not _as_admin(cmd):
        raise PermissionError("administrator password was not given")


def delete_on_reboot(path):
    raise OSError("not available on macOS")


def remove_font_resource(path, max_tries=8):
    return 0


def add_font_resource(path):
    return 0


def broadcast_font_change():
    pass


def lockers(paths):
    """Programs that have any of `paths` open (lsof): [{pid, name, service, kind, exe}]."""
    paths = [str(p) for p in paths if p and os.path.exists(p)]
    if not paths:
        return []
    try:
        r = subprocess.run(["lsof", "-F", "pc", "--", *paths], capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    out, pid = [], None
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("c") and pid is not None:
            out.append({"pid": pid, "name": line[1:], "service": "", "kind": "app", "exe": line[1:]})
    return out


def dark_title_bar(hwnd, caption_rgb=None, dark=True):
    pass                    # macOS draws the title bar itself, following the window's light/dark look


def shell_token():
    return None


def run_as_user(cmd, cwd=None, token=None):
    subprocess.Popen([str(c) for c in cmd], cwd=cwd)
    return False


def reveal(path):
    """Show a file selected in Finder."""
    subprocess.Popen(["open", "-R", str(path)])
