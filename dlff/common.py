"""Shared names, paths and settings for dl_font_fixer."""

import json
import os
import sys
from pathlib import Path

APP_NAME = "dl_font_fixer"
APP_VERSION = "1.4"
RELEASE_ASSET = f"{APP_NAME}-windows.zip"     # the Mac files are named by updater.asset_name()

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
BIN = "Recycle Bin" if IS_WIN else "Trash"        # where deleted fonts go
OS_NAME = "Windows" if IS_WIN else "macOS"

if IS_MAC:
    _SUPPORT = Path.home() / "Library" / "Application Support"
    CONFIG_DIR = _SUPPORT / APP_NAME
    WINDIR = Path("/System")
    SYSTEM_FONTS = Path("/Library/Fonts")                 # installed for all users
    USER_FONTS = Path.home() / "Library" / "Fonts"        # installed for you
    APPLE_FONTS = [Path("/System/Library/Fonts")]         # macOS's own fonts: read only, never touched
    ADOBE_LIVETYPE = _SUPPORT / "Adobe" / "CoreSync" / "plugins" / "livetype"
else:
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    WINDIR = Path(os.environ.get("WINDIR", r"C:\Windows"))
    SYSTEM_FONTS = WINDIR / "Fonts"
    USER_FONTS = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Microsoft" / "Windows" /         "Fonts"
    APPLE_FONTS = []
    ADOBE_LIVETYPE = Path(os.environ.get("APPDATA", Path.home())) / "Adobe" / "CoreSync" / "plugins" / "livetype"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
BACKUP_DIR = CONFIG_DIR / "backups"      # 1.0-1.1 only; read once into the history
HISTORY_FILE = CONFIG_DIR / "history.json"
FONTS_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"


def asset(name):
    for base in (APP_DIR / "assets", BUNDLE_DIR / "assets"):
        if (base / name).exists():
            return base / name
    return None


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
