"""Things that change the system: purge fonts, unlock files, services, caches, Adobe, deletion history.

Every function takes `log(text, level)` (level: info | ok | warn | err | cmd) so the window can show a
terminal-style transcript of what happened. No GUI code here.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil

from . import winapi
from .common import BACKUP_DIR, BIN, CONFIG_DIR, FONTS_KEY, HISTORY_FILE, IS_MAC, IS_WIN, USER_FONTS, WINDIR

if IS_WIN:
    import winreg
    HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
else:
    HIVES = {}

NO_WINDOW = winapi.NO_WINDOW

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

if IS_MAC:
    # process names on macOS (no .exe); Adobe apps carry the year: "Adobe Photoshop 2026"
    ADOBE_SYNC = ["Creative Cloud", "Creative Cloud Helper", "Creative Cloud UI Helper", "Core Sync",
                  "CoreSync", "CCXProcess", "CCLibrary", "Adobe Desktop Service", "AdobeIPCBroker",
                  "Adobe CEF Helper", "Core Sync Helper"]
    ADOBE_APPS = {"Adobe Photoshop": "Photoshop", "Adobe Illustrator": "Illustrator", "Adobe InDesign": "InDesign",
                  "Adobe After Effects": "After Effects", "Adobe Premiere Pro": "Premiere Pro",
                  "Adobe Acrobat": "Acrobat", "Adobe Media Encoder": "Media Encoder", "Adobe Animate": "Animate",
                  "Adobe InCopy": "InCopy", "Adobe Audition": "Audition", "Adobe Express": "Express"}


def _nolog(*a, **k):
    pass


def run(cmd, log=_nolog, timeout=60):
    log("> " + " ".join(str(c) for c in cmd), "cmd")
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
    if not IS_WIN:
        return None
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
    if not IS_WIN:
        return False
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

def _adobe_apps_running():
    if not IS_MAC:
        return sorted({ADOBE_APPS[n] for n in ADOBE_APPS for p in procs_named([n])})
    found = set()
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name") or ""
        for prefix, label in ADOBE_APPS.items():
            if name.startswith(prefix):
                found.add(label)
    return sorted(found)


def adobe_status():
    sync = procs_named(ADOBE_SYNC)
    if IS_MAC:
        return {"running": bool(sync), "processes": len(sync), "apps": _adobe_apps_running()}
    apps = sorted({ADOBE_APPS[n] for n in ADOBE_APPS for p in procs_named([n])})
    return {"running": bool(sync), "processes": len(sync), "apps": apps}


def restart_adobe_cc(log=_nolog):
    """Close the Creative Cloud background processes and start Creative Cloud again, so it re-syncs fonts."""
    if IS_MAC:
        return _restart_adobe_cc_mac(log)
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


def _restart_adobe_cc_mac(log):
    ps = procs_named(ADOBE_SYNC)
    log(f"Closing {len(ps)} Creative Cloud background process(es)", "info")
    for p in ps:
        try:
            p.terminate()
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(ps, timeout=6)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass
    time.sleep(1)
    for cmd in (["open", "-b", "com.adobe.acc.AdobeCreativeCloud"], ["open", "-a", "Creative Cloud"]):
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            log("Started Creative Cloud", "ok")
            log("Creative Cloud re-syncs Adobe Fonts in about a minute. In Photoshop / Illustrator use "
                "Type > Resolve Missing Fonts or reopen the document.", "info")
            return
    log("Creative Cloud isn't installed in the usual place; start it from Applications.", "warn")


# ---------------------------------------------------------------- font cache

def rebuild_font_cache(log=_nolog):
    """Stop the font cache services, delete their cache files, start them again. Needs admin on Windows."""
    if IS_MAC:
        # macOS: clear your font caches and restart the font server (no password needed)
        for cmd in (["atsutil", "databases", "-removeUser"], ["atsutil", "server", "-shutdown"],
                    ["atsutil", "server", "-ping"]):
            rc, out = run(cmd, log)
            if out.strip():
                log(out.strip(), "info" if rc == 0 else "warn")
        log("Font caches cleared. Restart open apps (or log out and in) so they pick up the change.", "ok")
        return True
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
    if not IS_WIN:
        return []
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


# ---------------------------------------------------------------- history (what was deleted)

def _read_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_history(entries):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)


def _import_old_backups(entries):
    """1.0/1.1 kept backup folders with a manifest.json; list those deletions in the history too."""
    if not BACKUP_DIR.is_dir():
        return entries
    known = {e.get("date") for e in entries}
    for d in sorted(BACKUP_DIR.iterdir()):
        try:
            data = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("date") in known:
            continue
        entries.append({"date": data.get("date", ""), "items": [
            {"family": i.get("family", ""), "style": i.get("style", ""), "full_name": i.get("full_name", ""),
             "path": i.get("path", ""), "scope": i.get("scope", ""), "reg": i.get("reg", []),
             "result": "deleted" if i.get("backup_file") else "registry entry removed (file was already missing)"}
            for i in data.get("items", [])]})
    entries.sort(key=lambda e: e.get("date", ""))
    return entries


def item_state(item):
    """Where a deleted font is now: 'bin' (in the Recycle Bin, can be restored), 'restored', 'gone' (permanently
    deleted), 'registry' (only a dead registry entry was removed) or 'failed'."""
    res = item.get("result", "deleted")
    if res.startswith("registry"):
        return "registry"
    if res.startswith("FAILED"):
        return "failed"
    if item.get("restored"):
        return "restored"
    if item.get("bin") and os.path.exists(item["bin"]):
        return "bin"
    if item.get("bin") and os.path.exists(item.get("path", "")):
        return "restored"           # put back with the Recycle Bin's own Restore
    return "gone"


def history():
    """Every deletion, newest first: [{date, items: [{family, style, full_name, path, scope, reg, result,
    bin?, state}]}]."""
    entries = _import_old_backups(_read_history())
    for e in entries:
        for i in e.get("items", []):
            i["state"] = item_state(i)
    return list(reversed(entries))


def restore_from_bin(keys, log=_nolog):
    """Put fonts back from the Recycle Bin: file to its old place, registry entries back, loaded again.
    keys: [(date, path)] identifying history items. Returns how many were restored."""
    entries = _read_history()
    want = {tuple(k) for k in keys}
    n = 0
    admin = winapi.is_admin()
    for e in entries:
        for item in e.get("items", []):
            if (e.get("date"), item.get("path")) not in want or item_state(item) != "bin":
                continue
            dst = Path(item["path"])
            if dst.exists():
                log(f"{dst.name}: a file with that name is already there, skipped", "warn")
                continue
            try:
                winapi.move_back(item["bin"], str(dst))
            except OSError as ex:
                log(f"{dst.name}: couldn't move it out of the {BIN} ({ex})", "err")
                continue
            if item.get("bin_info"):
                try:
                    os.remove(item["bin_info"])         # the Recycle Bin's own record of it
                except OSError:
                    pass
            for hive, name, data in item.get("reg", []):
                if hive == "HKLM" and not admin:
                    log(f"HKLM \"{name}\" needs administrator rights, not restored", "warn")
                    continue
                try:
                    with winreg.CreateKeyEx(HIVES[hive], FONTS_KEY, 0,
                                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
                except OSError as ex:
                    log(f"registry {hive} \"{name}\": {ex}", "err")
            winapi.add_font_resource(dst)
            item["restored"] = datetime.now().isoformat(timespec="seconds")
            n += 1
            log(f"restored {item.get('family', '')} {item.get('style', '')}  ->  {dst}", "ok")
    if n:
        _write_history(entries)
        winapi.broadcast_font_change()
    log(f"Restored {n} font file(s) from the {BIN}", "ok" if n else "warn")
    return n


def clear_history():
    _write_history([])
    if BACKUP_DIR.is_dir():
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)


def _record(faces, res):
    """Add one purge to the history file."""
    done = set(res["deleted"])
    queued = set(res["queued"])
    failed = set(res["failed"])
    items = []
    for f in faces:
        if not f.exists:
            result = "registry entry removed (file was already missing)"
        elif f.path in res["recycled"]:
            result = "recycled"
        elif f.path in done:
            result = "deleted"
        elif f.path in failed:
            result = "FAILED (file still there)"
        elif any(q.startswith(f.path) for q in queued):
            result = "deleted at next restart"
        elif any(r.startswith(f.path) for r in res["renamed"]):
            result = "renamed to .old (locked)"
        else:
            result = "deleted"
        item = {"family": f.family, "style": f.style, "full_name": f.full_name, "ps_name": f.ps_name,
                "path": f.path, "scope": f.scope, "reg": [list(r) for r in f.reg], "result": result}
        if f.path in res["recycled"]:
            item["bin"], item["bin_info"] = res["recycled"][f.path]
        items.append(item)
    try:
        entries = _import_old_backups(_read_history())
        entries.append({"date": datetime.now().isoformat(timespec="seconds"), "items": items})
        _write_history(entries)
    except OSError:
        pass


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


def _remove(path, res, log):
    """Move `path` to the Recycle Bin (so it can be restored from History); delete it outright only when the
    Recycle Bin can't take it. False when the file is locked and still there."""
    t0 = time.time()
    if winapi.recycle(path):
        r, i = winapi.find_in_recycle_bin(path, t0)
        res["deleted"].append(path)
        if r:
            res["recycled"][path] = [r, i]
            log(f"moved to {BIN}: {path}", "ok")
        else:
            log(f"deleted {path} (the {BIN} didn't keep it)", "ok")
        return True
    if os.path.exists(path) and _try_delete(path):
        res["deleted"].append(path)
        log(f"deleted {path} ({BIN} not available)", "ok")
        return True
    return not os.path.exists(path)


def purge(faces, log=_nolog, unlock=True):
    """Remove fonts completely: unload -> registry -> file to the Recycle Bin -> unlock -> rename / reboot queue.
    Every purge is written to the history; files in the Recycle Bin can be restored from there.

    faces: scanner.Face objects. Returns {"deleted", "renamed", "queued", "failed", "reg"}.
    """
    admin = winapi.is_admin()
    faces = [f for f in faces if f.purgeable]
    res = {"deleted": [], "recycled": {}, "renamed": [], "queued": [], "failed": [], "reg": 0}
    if not faces:
        log("Nothing to purge (Adobe Fonts and Windows system fonts are never touched)", "warn")
        return res
    need_admin = [f for f in faces if f.scope != "user" or any(h == "HKLM" for h, *_ in f.reg)]
    if need_admin and IS_MAC:
        log(f"{len(need_admin)} face(s) are in /Library/Fonts (all users): macOS asks for your password", "info")
    elif need_admin and not admin:
        log(f"{len(need_admin)} face(s) are installed for all users: they need administrator rights. "
            f"Reopen the app and click Yes on the administrator prompt.", "warn")

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
        if not _remove(f.path, res, log):
            pending.append(f.path)

    # 5. unlock and retry
    stopped_services, explorer_killed = [], False
    if pending and unlock:
        lk = winapi.lockers(pending)
        if lk:
            names = ", ".join(sorted({(x.get("service") or x.get("exe") or x["name"]) for x in lk}))
            log(f"{len(pending)} file(s) locked by: {names}", "warn")
        else:
            log(f"{len(pending)} file(s) could not be deleted "
                f"({'locked by the Windows font system' if IS_WIN else 'password not given, or in use'})", "warn")
        if admin and IS_WIN:
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
            if not _remove(p, res, log):
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

    _record(faces, res)
    log(f"PURGE DONE  deleted {len(res['deleted'])}  renamed {len(res['renamed'])}  "
        f"reboot-queued {len(res['queued'])}  failed {len(res['failed'])}  registry {res['reg']}",
        "ok" if not res["failed"] else "warn")
    return res
