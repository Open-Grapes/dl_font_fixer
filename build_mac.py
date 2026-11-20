"""Build dl_font_fixer for macOS (run on a Mac; GitHub Actions does this automatically).

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python build_mac.py          # -> dist/MacOS/dl_font_fixer-mac-<arch>.dmg

Builds for the Mac it runs on (Apple Silicon or Intel): makes the .app, smoke-tests it (scan report, the
window, Check for updates), packs a .dmg with the app and install notes, and tests the in-place updater.
"""

import json
import os
import platform
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dlff.common import APP_NAME, APP_VERSION  # noqa: E402

ARCH = "apple-silicon" if platform.machine() == "arm64" else "intel"
DIST = ROOT / "dist" / "MacOS"
WORK = ROOT / "build-mac"
APP = WORK / "dist" / f"{APP_NAME}.app"
ICNS = ROOT / "assets" / "icon.icns"
BUNDLE_ID = "com.opengrapes.dl-font-fixer"
DMG_NAME = f"{APP_NAME}-mac-{ARCH}.dmg"

# Same trimming as the Windows build (build.py).
EXCLUDE = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtTest",
           "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
           "PySide6.QtSvg", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtPrintSupport",
           "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "tkinter", "unittest", "pydoc",
           "numpy", "PIL", "matplotlib", "scipy", "sympy", "lxml", "brotli", "zopfli", "unicodedata2"]


def sh(*cmd, **kw):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def make_icns():
    if ICNS.exists():
        return
    from PIL import Image
    img = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    img.save(ICNS, format="ICNS")


def pyinstaller():
    shutil.rmtree(WORK, ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", APP_NAME, "--icon", ICNS, "--osx-bundle-identifier", BUNDLE_ID,
           "--add-data", f"{ROOT / 'assets' / 'icon.png'}:assets",
           "--collect-data", "certifi",
           "--distpath", WORK / "dist", "--workpath", WORK / "work", "--specpath", WORK]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    sh(*cmd, ROOT / "run.py")


def fill_bundle():
    res = APP / "Contents" / "Resources"
    for name in ("LICENSE", "README.md"):
        shutil.copy2(ROOT / name, res / name)
    plist_path = APP / "Contents" / "Info.plist"
    with open(plist_path, "rb") as fh:
        pl = plistlib.load(fh)
    pl.update({
        "CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION, "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,          # light and dark title bars
        "NSAppleEventsUsageDescription": "dl_font_fixer asks for your password to remove or restore fonts "
                                         "installed for all users (/Library/Fonts).",
    })
    with open(plist_path, "wb") as fh:
        plistlib.dump(pl, fh)
    # Ad-hoc signature (required on Apple Silicon). Not notarized: first launch needs "Open Anyway".
    sh("codesign", "--force", "--deep", "--sign", "-", APP)
    sh("codesign", "--verify", "--deep", "--strict", APP)


DMG_README = f"""{APP_NAME} {APP_VERSION} for macOS ({ARCH.replace('-', ' ')})

INSTALL
1. Drag {APP_NAME} onto the Applications folder.
2. Open Applications and double-click {APP_NAME}.
   macOS says it can't verify the developer: click Done.
3. Apple menu > System Settings > Privacy & Security, scroll down to Security:
   "{APP_NAME}" was blocked... click Open Anyway, then Open Anyway again and enter your password.
   (Only needed once.)

USE
- It scans ~/Library/Fonts (installed for you), /Library/Fonts (all users), macOS's own fonts and
  the fonts Creative Cloud activates through Adobe Fonts.
- It shows Adobe Fonts conflicts, duplicates, broken files and recently added fonts.
- Delete a font: tick it and click DELETE, or right-click the family. It goes to the Trash, and HISTORY can
  put it back until you empty the Trash. Fonts in /Library/Fonts ask for your password.
- macOS's own fonts (/System/Library/Fonts) and Adobe Fonts are never deleted.
- REBUILD FONT CACHE clears your Mac's font caches; RESTART ADOBE CC makes Creative Cloud re-sync.
- THEME (top right): Dark, Light or Match macOS.
"""


def make_dmg():
    DIST.mkdir(parents=True, exist_ok=True)
    stage = WORK / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    sh("ditto", APP, stage / APP.name)              # ditto keeps symlinks and signatures intact
    os.symlink("/Applications", stage / "Applications")
    (stage / "READ ME.txt").write_text(DMG_README)
    out = DIST / DMG_NAME
    out.unlink(missing_ok=True)
    sh("hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO", out)
    print(f"\nBuilt {out} ({out.stat().st_size / 1e6:.0f} MB)")
    return out


# ---------------------------------------------------------------- smoke tests on the built app

def smoke_test():
    binary = APP / "Contents" / "MacOS" / APP_NAME
    t = WORK / "smoke"
    shutil.rmtree(t, ignore_errors=True)
    t.mkdir(parents=True)

    # The scanner inside the app finds this Mac's fonts.
    out = t / "scan.json"
    subprocess.run([str(binary), "--scan-report", str(out)], timeout=300)
    rep = json.loads(out.read_text())
    print("Scan:", rep.get("stats") or rep, flush=True)
    assert "error" not in rep and rep["stats"]["faces"] > 50, f"scan failed: {rep}"

    # The window opens and stays up.
    p = subprocess.Popen([str(binary)])
    time.sleep(12)
    alive = p.poll() is None
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=20)
    assert alive, "the window closed by itself (crash at start)"

    # Check for updates reaches GitHub from inside the app (certificates, network).
    out = t / "update.json"
    subprocess.run([str(binary), "--check-update", str(out)], timeout=120)
    res = json.loads(out.read_text())
    print("Check for updates:", res, flush=True)
    assert "error" not in res and res.get("version"), f"update check failed: {res}"
    print("\nSMOKE TEST PASSED", flush=True)


def update_install_test(dmg):
    """Run the real updater against the new .dmg: replace a copy of the app while a process 'is' the app."""
    from dlff import updater
    t = WORK / "update-test"
    shutil.rmtree(t, ignore_errors=True)
    t.mkdir(parents=True)
    old = t / f"{APP_NAME}.app"
    sh("ditto", APP, old)
    (old / "Contents" / "Resources" / "OLD_MARKER").write_text("old copy")
    dummy = subprocess.Popen(["sleep", "3"])
    import threading
    threading.Thread(target=dummy.wait, daemon=True).start()   # reap it, like a real app that quits
    cmd, work = updater.prepare_install(dmg, dummy.pid, launch=False, loc=old)
    updater.start_helper(cmd)
    for _ in range(120):
        if (work / "finished.txt").exists():
            break
        time.sleep(0.5)
    assert (work / "finished.txt").exists(), "the update helper didn't finish"
    assert not (old / "Contents" / "Resources" / "OLD_MARKER").exists(), "the app wasn't replaced"
    assert (old / "Contents" / "MacOS" / APP_NAME).exists(), "the replaced app has no program"
    sh("codesign", "--verify", "--deep", "--strict", old)
    print("UPDATE INSTALL TEST PASSED", flush=True)


if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("build_mac.py must run on macOS (GitHub Actions builds it: .github/workflows/mac.yml)")
    make_icns()
    pyinstaller()
    fill_bundle()
    smoke_test()
    update_install_test(make_dmg())
