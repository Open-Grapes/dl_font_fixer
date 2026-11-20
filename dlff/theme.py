"""Colours and the Qt style sheet: the HUD / terminal look, dark or light.

Call use("dark" | "light" | "system") before building widgets; everything reads the module-level names
(T.BG, T.CYAN, T.QSS …) when it draws, so switching rebuilds the window with the new palette.
"""

PALETTES = {
    "dark": {
        "BG": "#05070b", "PANEL": "#0a0e15", "PANEL2": "#0f1520", "LINE": "#1a2433", "LINE_HI": "#24405a",
        "TEXT": "#d6e2f2", "DIM": "#6a7b92", "FAINT": "#3a4759", "CONSOLE": "#03050a",
        "CYAN": "#00e5ff", "GREEN": "#00ff9c", "AMBER": "#ffb020", "RED": "#ff3d71", "VIOLET": "#c27dff",
        "BLUE": "#4da3ff", "ON_ACCENT": "#05070b", "GRID_ALPHA": 9,
    },
    "light": {
        "BG": "#e9eef4", "PANEL": "#ffffff", "PANEL2": "#f2f5f9", "LINE": "#d3dbe5", "LINE_HI": "#a9bacd",
        "TEXT": "#142030", "DIM": "#566579", "FAINT": "#a3b0c0", "CONSOLE": "#f8fafc",
        "CYAN": "#0086a8", "GREEN": "#0a8f55", "AMBER": "#b06800", "RED": "#d0244b", "VIOLET": "#8237c9",
        "BLUE": "#1f63c6", "ON_ACCENT": "#ffffff", "GRID_ALPHA": 14,
    },
}

MONO = "Cascadia Mono, Consolas, Menlo, monospace"
MODE = "dark"           # the palette in use: "dark" or "light"
CHOICE = "dark"         # what the user picked: "dark", "light" or "system"


def windows_mode():
    """'light' or 'dark' from Windows Settings › Personalization › Colors (app mode)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "dark"


def rgba(hexs, alpha):
    h = hexs.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def rgb(hexs):
    h = hexs.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def use(choice="dark"):
    """Switch every colour name and QSS to the palette for `choice` ("dark", "light" or "system")."""
    global MODE, CHOICE, DARK, ISSUE_COLOR, SCOPE_COLOR, LOG_COLOR, HEADER_BG, FOOT_BG, QSS
    CHOICE = choice if choice in ("dark", "light", "system") else "dark"
    MODE = windows_mode() if CHOICE == "system" else CHOICE
    DARK = MODE == "dark"
    g = globals()
    g.update(PALETTES[MODE])
    ISSUE_COLOR = {"ghost": RED, "adobe": VIOLET, "duplicate": AMBER, "orphan": BLUE, "unreadable": RED}
    SCOPE_COLOR = {"user": BLUE, "system": DIM, "adobe": VIOLET, "other": AMBER}
    LOG_COLOR = {"info": TEXT, "ok": GREEN, "warn": AMBER, "err": RED, "cmd": CYAN}
    HEADER_BG = rgba(PANEL, 0.92)
    FOOT_BG = rgba(PANEL, 0.94)
    hover = "rgba(255,255,255,0.03)" if DARK else "rgba(0,0,0,0.04)"
    QSS = f"""
* {{ color: {TEXT}; font-family: "Segoe UI Variable Text", "Segoe UI", ".AppleSystemUIFont", "Helvetica Neue"; font-size: 13px; outline: 0; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {CYAN}; padding: 6px; font-family: {MONO}; }}
QLabel#h {{ font-family: {MONO}; font-size: 11px; color: {DIM}; letter-spacing: 2px; }}
QLabel#dim {{ color: {DIM}; }}
QLabel#mono {{ font-family: {MONO}; font-size: 12px; }}

QLineEdit {{ background: {PANEL}; border: 1px solid {LINE}; padding: 8px 10px; font-family: {MONO};
             selection-background-color: {CYAN}; selection-color: {ON_ACCENT}; }}
QLineEdit:focus {{ border: 1px solid {CYAN}; }}

QPushButton {{ background: transparent; border: 1px solid {LINE_HI}; padding: 8px 14px; font-family: {MONO};
               font-size: 12px; letter-spacing: 1px; color: {TEXT}; text-align: left; }}
QPushButton:hover {{ border-color: {CYAN}; color: {CYAN}; background: {rgba(CYAN, 0.06)}; }}
QPushButton:pressed {{ background: {rgba(CYAN, 0.18)}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {LINE}; }}
QPushButton#primary {{ border-color: {CYAN}; color: {CYAN}; text-align: center; }}
QPushButton#primary:hover {{ background: {CYAN}; color: {ON_ACCENT}; }}
QPushButton#primary:disabled {{ border-color: {LINE}; color: {FAINT}; }}
QPushButton#danger {{ border-color: {RED}; color: {RED}; text-align: center; }}
QPushButton#danger:hover {{ background: {RED}; color: {ON_ACCENT}; }}
QPushButton#danger:disabled {{ border-color: {LINE}; color: {FAINT}; }}
QPushButton#nav {{ border: none; border-left: 2px solid transparent; padding: 7px 12px; color: {DIM}; }}
QPushButton#nav:hover {{ color: {TEXT}; background: {hover}; }}
QPushButton#nav:checked {{ color: {CYAN}; border-left: 2px solid {CYAN}; background: {rgba(CYAN, 0.07)}; }}
QPushButton#chip {{ border: 1px solid {LINE}; padding: 4px 10px; font-size: 11px; text-align: center; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE_HI}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {CYAN}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {LINE_HI}; min-width: 30px; }}

QListView {{ background: transparent; border: none; }}
QTreeWidget {{ background: {PANEL}; border: 1px solid {LINE}; font-family: {MONO}; font-size: 12px;
               alternate-background-color: {PANEL2}; }}
QTreeWidget::item {{ padding: 4px 2px; border: none; }}
QTreeWidget::item:selected {{ background: {rgba(CYAN, 0.14)}; color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL2}; color: {DIM}; border: none; border-bottom: 1px solid {LINE};
                        padding: 6px; font-family: {MONO}; font-size: 11px; }}
QTreeWidget::indicator, QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {LINE_HI};
                                                background: {PANEL}; }}
QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{ background: {CYAN}; border-color: {CYAN}; }}
QTreeWidget::indicator:disabled {{ background: {PANEL2}; border-color: {LINE}; }}
QCheckBox {{ font-family: {MONO}; font-size: 12px; color: {DIM}; spacing: 8px; }}

QPlainTextEdit#console {{ background: {CONSOLE}; border: none; border-top: 1px solid {LINE};
                          font-family: {MONO}; font-size: 12px; color: {GREEN}; padding: 6px 10px; }}
QTextBrowser {{ background: {BG}; border: 1px solid {LINE}; color: {TEXT}; padding: 8px; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollArea {{ background: transparent; border: none; }}
QDialog {{ background: {PANEL}; }}
QMenu {{ background: {PANEL2}; border: 1px solid {LINE_HI}; font-family: {MONO}; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {rgba(CYAN, 0.15)}; color: {CYAN}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QProgressBar {{ background: {LINE}; border: none; }}
QProgressBar::chunk {{ background: {CYAN}; }}
"""


use("dark")
