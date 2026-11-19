"""Things that change the system: purge fonts, unlock files, services, caches, Adobe, backups.

Every function takes `log(text, level)` (level: info | ok | warn | err | cmd) so the window can show a
terminal-style transcript of what happened. No GUI code here.
"""

import json
import os
import shutil
import subprocess
import time
import winreg
from datetime import datetime
from pathlib import Path

import psutil

from . import winapi
from .common import BACKUP_DIR, FONTS_KEY, USER_FONTS, WINDIR

NO_WINDOW = winapi.NO_WINDOW
HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}

ADOBE_SYNC = ["Creative Cloud.exe", "Creative Cloud Helper.exe", "Creative Cloud UI Helper.exe", "CoreSync.exe",
              "CCXProcess.exe", "CCLibrary.exe", "Adobe Desktop Service.exe", "AdobeIPCBroker.exe",
              "Adobe CEF Helper.exe"]
ADOBE_APPS = {"Photoshop.exe": "Photoshop", "Illustrator.exe": "Illustrator", "InDesign.exe": "InDesign",
              "AfterFX.exe": "After Effects", "Adobe Premiere Pro.exe": "Premiere Pro", "Acrobat.exe": "Acrobat",
              "Adobe Media Encoder.exe": "Media Encoder", "Animate.exe": "Animate", "InCopy.exe": "InCopy",
              "Adobe Audition.exe": "Audition", "Adobe XD.exe": "XD", "Adobe Express.exe": "Express"}
CC_DEFAULT = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe" / "Adobe Creative Cloud" / "ACC" / \
    "Creative Cloud.exe"
FONT_CACHE_DIR = WINDIR / "ServiceProfiles" / "LocalService" / "AppData" / "Local" / "FontCache"
FNTCACHE = WINDIR / "System32" / "FNTCACHE.DAT"
FONT_SERVICES = ["FontCache", "FontCache3.0.0.0"]
PENDING_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager"


def _nolog(*a, **k):
    pass


def run(cmd, log=_nolog, timeout=60):
    log("> " + subprocess.list2cmdline(cmd), "cmd")
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=timeout,
                       errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- processes / services

def procs_named(names):
    want = {n.lower() for n in names}
    out = []
    for p in psutil.process_iter(["name", "pid"]):
        try:
            if (p.info["name"] or "").lower() in want:
                out.append(p)
        except Exception:
            pass
    return out


def service_state(name):
    try:
        return psutil.win_service_get(name).status()   # running | stopped | start_pending ...
    except Exception:
        return None


def stop_service(name, log=_nolog):
    if service_state(name) in (None, "stopped"):
        return False
    run(["sc.exe", "stop", name], log)
    for _ in range(40):
        if service_state(name) == "stopped":
            log(f"service {name} stopped", "ok")
            return True
        time.sleep(0.25)
    log(f"service {name} did not stop", "warn")
    return False


def start_service(name, log=_nolog):
    if service_state(name) in (None, "running"):
        return
    run(["sc.exe", "start", name], log)
    for _ in range(40):
        if service_state(name) == "running":
            log(f"service {name} running", "ok")
            return
        time.sleep(0.25)


_shell_tok = None


def kill_explorer(log=_nolog):
    global _shell_tok
    ps = procs_named(["explorer.exe"])
    if ps and _shell_tok is None:
        _shell_tok = winapi.shell_token()      # to start it again with normal (non-admin) rights
    for p in ps:
        try:
            p.kill()
        except Exception:
            pass
    psutil.wait_procs(ps, timeout=5)
    if ps:
        log(f"explorer.exe stopped ({len(ps)} process{'es' if len(ps) > 1 else ''})", "ok")
    return bool(ps)


def start_explorer(log=_nolog):
    time.sleep(1.5)                     # Windows 11 often restarts the shell by itself
    if not procs_named(["explorer.exe"]):
        winapi.run_as_user([WINDIR / "explorer.exe"], token=_shell_tok)
    log("explorer.exe running again", "ok")


def restart_explorer(log=_nolog):
    log("Restarting Windows Explorer (taskbar and folders flicker for a moment)", "info")
    kill_explorer(log)
    start_explorer(log)


def kill_pid(pid, log=_nolog):
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.terminate()
        try:
            p.wait(4)
        except psutil.TimeoutExpired:
            p.kill()
        log(f"ended {name} (pid {pid})", "ok")
        return True
    except Exception as e:
        log(f"could not end pid {pid}: {e}", "err")
        return False


# ---------------------------------------------------------------- Adobe

def adobe_status():
    sync = procs_named(ADOBE_SYNC)
    apps = sorted({ADOBE_APPS[n] for n in ADOBE_APPS for p in procs_named([n])})
    return {"running": bool(sync), "processes": len(sync), "apps": apps}


def restart_adobe_cc(log=_nolog):
    """Close the Creative Cloud background processes and start Creative Cloud again, so it re-syncs fonts."""
    exe = None
    for p in procs_named(["Creative Cloud.exe"]):
        try:
            exe = p.exe()
            break
        except Exception:
            pass
    exe = exe or (str(CC_DEFAULT) if CC_DEFAULT.exists() else None)
    ps = procs_named(ADOBE_SYNC)
    # CCXProcess runs node.exe children
    for p in list(ps):
        try:
            ps += [c for c in p.children(recursive=True) if c not in ps]
        except Exception:
            pass
    log(f"Closing {len(ps)} Creative Cloud background process(es)", "info")
    for p in ps:
        try:
            p.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(ps, timeout=6)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass
    left = procs_named(ADOBE_SYNC)
    if left:
        log(f"{len(left)} Adobe process(es) would not close (they may run as administrator)", "warn")
    else:
        log("Creative Cloud closed", "ok")
    if exe:
        time.sleep(1)
        winapi.run_as_user([exe], cwd=str(Path(exe).parent))
        log(f"Started {exe}", "ok")
        log("Creative Cloud re-syncs Adobe Fonts in about a minute. In Photoshop / Illustrator use "
            "Type > Resolve Missing Fonts or reopen the document.", "info")
    else:
        log("Creative Cloud is not installed in the usual place; start it from the Start menu.", "warn")


# ---------------------------------------------------------------- font cache

def rebuild_font_cache(log=_nolog):
    """Stop the font cache services, delete their cache files, start them again. Needs admin."""
    if not winapi.is_admin():
        log("Rebuilding the font cache needs administrator rights", "err")
        return False
    stopped = [s for s in FONT_SERVICES if stop_service(s, log)]
    removed = 0
    targets = [FNTCACHE]
    if FONT_CACHE_DIR.is_dir():
        targets += [p for p in FONT_CACHE_DIR.iterdir() if p.is_file()]
    for p in targets:
        if not p.exists():
            continue
        try:
            p.unlink()
            removed += 1
            log(f"deleted {p}", "ok")
        except OSError as e:
            log(f"could not delete {p}: {e.strerror}", "warn")
    for s in FONT_SERVICES:
        if s in stopped or s == "FontCache":
            start_service(s, log)
    log(f"Font cache cleared ({removed} file(s)). Windows rebuilds it as fonts are used; a restart "
        f"makes it complete.", "ok")
    return True


# ---------------------------------------------------------------- pending reboot operations

def pending_operations():
    """[(source, target)] from PendingFileRenameOperations; target '' means delete."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PENDING_KEY) as k:
            data, _ = winreg.QueryValueEx(k, "PendingFileRenameOperations")
    except OSError:
        return []
    data = list(data or [])
    out = []
    for i in range(0, len(data) - 1, 2):
        out.append((data[i].replace("\\??\\", ""), data[i + 1].replace("\\??\\", "").lstrip("!")))
    return out


def pending_font_operations():
    return [(s, t) for s, t in pending_operations() if "\\fonts\\" in s.lower() or s.lower().endswith(".old")]


# ---------------------------------------------------------------- locks

def check_locks(paths):
    """{path: [locker dicts]} for the files that exist."""
    out = {}
    for p in paths:
        if p and os.path.exists(p):
            out[p] = winapi.lockers([p])
    return out


# ---------------------------------------------------------------- backup / restore

def _backup_root():
    d = BACKUP_DIR / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_backups():
    out = []
    if BACKUP_DIR.is_dir():
        for d in sorted(BACKUP_DIR.iterdir(), reverse=True):
            m = d / "manifest.json"
            if m.exists():
                try:
                    data = json.loads(m.read_text(encoding="utf-8"))
                    out.append({"dir": str(d), **data})
                except Exception:
                    pass
    return out


def restore_backup(backup_dir, log=_nolog):
    """Reinstall fonts from a backup for the current user (no admin needed)."""
    d = Path(backup_dir)
    data = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    USER_FONTS.mkdir(parents=True, exist_ok=True)
    n = 0
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as k:
        for item in data.get("items", []):
            src = d / item["backup_file"] if item.get("backup_file") else None
            if not src or not src.exists():
                continue
            dst = USER_FONTS / Path(item["path"]).name
            if dst.exists():
                dst = dst.with_name(f"{dst.stem}_restored{dst.suffix}")
            shutil.copy2(src, dst)
            names = [r[1] for r in item.get("reg", [])] or [f"{item.get('full_name') or dst.stem} (TrueType)"]
            for nm in names:
                winreg.SetValueEx(k, nm, 0, winreg.REG_SZ, str(dst))
            winapi.add_font_resource(dst)
            n += 1
            log(f"restored {dst.name}", "ok")
    winapi.broadcast_font_change()
    log(f"Restored {n} font file(s) for this user", "ok")
    return n


# ---------------------------------------------------------------- purge

def _delete_reg(hive, name, log):
    try:
        access = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
        with winreg.OpenKey(HIVES[hive], FONTS_KEY, 0, access) as k:
            winreg.DeleteValue(k, name)
        log(f"registry {hive}\\...\\Fonts  \"{name}\" deleted", "ok")
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        log(f"registry {hive} \"{name}\": needs administrator", "err")
        return False
    except OSError as e:
        log(f"registry {hive} \"{name}\": {e}", "err")
        return False


def _try_delete(path):
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def purge(faces, log=_nolog, unlock=True):
    """Remove fonts completely: backup -> unload -> registry -> delete file -> unlock -> rename / reboot queue.

    faces: scanner.Face objects. Returns {"deleted", "renamed", "queued", "failed", "backup"}.
    """
    admin = winapi.is_admin()
    faces = [f for f in faces if f.purgeable]
    res = {"deleted": [], "renamed": [], "queued": [], "failed": [], "backup": None, "reg": 0}
    if not faces:
        log("Nothing to purge (Adobe Fonts and Windows system fonts are never touched)", "warn")
        return res
    need_admin = [f for f in faces if f.scope != "user" or any(h == "HKLM" for h, *_ in f.reg)]
    if need_admin and not admin:
        log(f"{len(need_admin)} face(s) are installed for all users: they need administrator rights. "
            f"Use ADMIN in the top bar to restart elevated.", "warn")

    # 1. backup
    bdir = _backup_root()
    items = []
    for f in faces:
        item = {"path": f.path, "family": f.family, "style": f.style, "full_name": f.full_name,
                "scope": f.scope, "reg": f.reg, "backup_file": None}
        if f.exists and os.path.exists(f.path):
            dst = bdir / f"{len(items):03d}_{Path(f.path).name}"
            try:
                shutil.copy2(f.path, dst)
                item["backup_file"] = dst.name
            except OSError as e:
                log(f"backup of {f.path} failed: {e}", "warn")
        items.append(item)
    (bdir / "manifest.json").write_text(json.dumps(
        {"date": datetime.now().isoformat(timespec="seconds"), "families": sorted({f.family for f in faces}),
         "items": items}, indent=2), encoding="utf-8")
    res["backup"] = str(bdir)
    log(f"backup saved to {bdir}", "ok")

    # 2. unload from this session, 3. registry
    for f in faces:
        if f.exists:
            n = winapi.remove_font_resource(f.path)
            if n:
                log(f"unloaded {Path(f.path).name} from the session ({n}x)", "ok")
        for hive, name, _ in f.reg:
            if hive == "HKLM" and not admin:
                log(f"skip HKLM \"{name}\" (not administrator)", "warn")
                continue
            if _delete_reg(hive, name, log):
                res["reg"] += 1
    winapi.broadcast_font_change()

    # 4. delete files
    pending = []
    for f in faces:
        if not f.exists:
            continue
        if _try_delete(f.path):
            res["deleted"].append(f.path)
            log(f"deleted {f.path}", "ok")
        else:
            pending.append(f.path)

    # 5. unlock and retry
    stopped_services, explorer_killed = [], False
    if pending and unlock:
        lk = winapi.lockers(pending)
        if lk:
            names = ", ".join(sorted({(x.get("service") or x.get("exe") or x["name"]) for x in lk}))
            log(f"{len(pending)} file(s) locked by: {names}", "warn")
        else:
            log(f"{len(pending)} file(s) could not be deleted (locked by the Windows font system)", "warn")
        if admin:
            services = {x["service"] for x in lk if x.get("service")} | {"FontCache"}
            for s in services:
                if s in FONT_SERVICES and stop_service(s, log):
                    stopped_services.append(s)
        if any(x["kind"] == "explorer" or (x.get("exe") or "").lower() == "explorer.exe" for x in lk):
            explorer_killed = kill_explorer(log)
        apps = sorted({x.get("exe") or x["name"] for x in lk if x["kind"] in ("app", "console", "unknown")
                       and (x.get("exe") or "").lower() != "explorer.exe" and not x.get("service")})
        if apps:
            log("still open in: " + ", ".join(apps) + ". Close these programs to free the file(s).", "warn")
        for p in pending:
            winapi.remove_font_resource(p)
        time.sleep(0.4)
        still = []
        for p in pending:
            if _try_delete(p):
                res["deleted"].append(p)
                log(f"deleted {p}", "ok")
            else:
                still.append(p)
        pending = still

    # 6. rename to .old and/or queue for reboot
    for p in pending:
        target = p
        old = p + ".old"
        i = 1
        while os.path.exists(old):
            old = f"{p}.{i}.old"
            i += 1
        try:
            os.rename(p, old)
            target = old
            res["renamed"].append(old)
            log(f"renamed locked file -> {Path(old).name}", "ok")
        except OSError:
            pass
        if admin:
            try:
                winapi.delete_on_reboot(target)
                res["queued"].append(target)
                log(f"queued for deletion at next restart: {target}", "ok")
                continue
            except OSError as e:
                log(f"could not queue {target}: {e}", "err")
        if target != p:
            continue    # renamed: Windows no longer loads it, it's harmless until deleted
        res["failed"].append(p)
        log(f"could not remove {p}. It needs administrator rights to queue it for the next reboot.", "err")

    for s in stopped_services:
        start_service(s, log)
    if explorer_killed:
        start_explorer(log)
    winapi.broadcast_font_change()

    log(f"PURGE DONE  deleted {len(res['deleted'])}  renamed {len(res['renamed'])}  "
        f"reboot-queued {len(res['queued'])}  failed {len(res['failed'])}  registry {res['reg']}",
        "ok" if not res["failed"] else "warn")
    return res
