"""Build dl_font_fixer for Windows.

    py -3.13 -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
    .venv\Scripts\python build.py            # -> dist\Windows\dl_font_fixer\ and dist\Windows\dl_font_fixer-windows.zip
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dlff.common import APP_NAME, RELEASE_ASSET  # noqa: E402

DIST = ROOT / "dist" / "Windows"
ICON = ROOT / "assets" / "icon.ico"

EXCLUDE = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtTest",
           "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
           "PySide6.QtSvg", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtPrintSupport",
           "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "tkinter", "unittest", "pydoc",
           "numpy", "PIL", "matplotlib", "scipy", "sympy", "lxml", "brotli", "zopfli", "unicodedata2"]
PRUNE = ["_internal/PySide6/opengl32sw.dll", "_internal/PySide6/translations"]


def make_icon():
    if ICON.exists():
        return
    from PIL import Image, ImageDraw, ImageFont
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), radius=44, fill=(7, 10, 16), outline=(0, 229, 255), width=6)
    cyan = (0, 229, 255)
    # HUD corner brackets
    for x, y, dx, dy in ((34, 34, 1, 1), (222, 34, -1, 1), (34, 222, 1, -1), (222, 222, -1, -1)):
        d.line((x, y, x + 34 * dx, y), fill=cyan, width=8)
        d.line((x, y, x, y + 34 * dy), fill=cyan, width=8)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/georgiab.ttf", 150)
    except OSError:
        f = ImageFont.load_default()
    d.text((128, 132), "F", font=f, fill=(230, 240, 255), anchor="mm")
    # red "fix" slash
    d.line((70, 196, 196, 70), fill=(255, 61, 113), width=12)
    ICON.parent.mkdir(exist_ok=True)
    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(ICON.with_suffix(".png"))


def pyinstaller():
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", APP_NAME, "--icon", str(ICON),
           "--add-data", f"{ICON};assets",
           "--add-data", f"{ICON.with_suffix('.png')};assets",
           "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build")]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    subprocess.check_call(cmd + [str(ROOT / "run.py")])


def assemble():
    out = DIST / APP_NAME
    for rel in PRUNE:
        p = out / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    for name in ("README.md", "LICENSE"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, out / name)
    z = DIST / RELEASE_ASSET
    z.unlink(missing_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                zf.write(f, Path(APP_NAME) / f.relative_to(out))
    print(f"\nBuilt {out}\nZipped {z} ({z.stat().st_size / 1e6:.0f} MB)")


def smoke_test():
    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    report = ROOT / "build_scan_report.json"
    rc = subprocess.call([str(exe), "--scan-report", str(report)], timeout=120)
    import json
    data = json.loads(report.read_text(encoding="utf-8"))
    report.unlink()
    if rc or "error" in data:
        raise SystemExit(f"smoke test failed: {data.get('error')}")
    print(f"smoke test OK: {data['stats']}")


if __name__ == "__main__":
    make_icon()
    pyinstaller()
    assemble()
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    smoke_test()
    print(f"Run: {DIST / APP_NAME / (APP_NAME + '.exe')}")
