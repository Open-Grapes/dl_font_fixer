"""Shared names, paths and settings for dl_font_fixer."""

import json
import os
import sys
from pathlib import Path

APP_NAME = "dl_font_fixer"
APP_VERSION = "1.1"
RELEASE_ASSET = f"{APP_NAME}-windows.zip"

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
SETTINGS_FILE = CONFIG_DIR / "settings.json"
BACKUP_DIR = CONFIG_DIR / "backups"

WINDIR = Path(os.environ.get("WINDIR", r"C:\Windows"))
SYSTEM_FONTS = WINDIR / "Fonts"
USER_FONTS = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Microsoft" / "Windows" / "Fonts"
ADOBE_LIVETYPE = Path(os.environ.get("APPDATA", Path.home())) / "Adobe" / "CoreSync" / "plugins" / "livetype"
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
