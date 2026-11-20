"""Colours and the Qt style sheet: a dark HUD / terminal look."""

BG = "#05070b"
PANEL = "#0a0e15"
PANEL2 = "#0f1520"
LINE = "#1a2433"
LINE_HI = "#24405a"
TEXT = "#d6e2f2"
DIM = "#6a7b92"
FAINT = "#3a4759"
CYAN = "#00e5ff"
GREEN = "#00ff9c"
AMBER = "#ffb020"
RED = "#ff3d71"
VIOLET = "#c27dff"
BLUE = "#4da3ff"

ISSUE_COLOR = {"ghost": RED, "adobe": VIOLET, "duplicate": AMBER, "orphan": BLUE, "unreadable": RED}
SCOPE_COLOR = {"user": BLUE, "system": DIM, "adobe": VIOLET, "other": AMBER}
LOG_COLOR = {"info": TEXT, "ok": GREEN, "warn": AMBER, "err": RED, "cmd": CYAN}

MONO = "Cascadia Mono, Consolas, monospace"

QSS = f"""
* {{ color: {TEXT}; font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 13px; outline: 0; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {CYAN}; padding: 6px; font-family: {MONO}; }}
QLabel#h {{ font-family: {MONO}; font-size: 11px; color: {DIM}; letter-spacing: 2px; }}
QLabel#dim {{ color: {DIM}; }}
QLabel#mono {{ font-family: {MONO}; font-size: 12px; }}

QLineEdit {{ background: {PANEL}; border: 1px solid {LINE}; padding: 8px 10px; font-family: {MONO};
             selection-background-color: {CYAN}; selection-color: {BG}; }}
QLineEdit:focus {{ border: 1px solid {CYAN}; }}

QPushButton {{ background: transparent; border: 1px solid {LINE_HI}; padding: 8px 14px; font-family: {MONO};
               font-size: 12px; letter-spacing: 1px; color: {TEXT}; text-align: left; }}
QPushButton:hover {{ border-color: {CYAN}; color: {CYAN}; background: rgba(0,229,255,0.06); }}
QPushButton:pressed {{ background: rgba(0,229,255,0.18); }}
QPushButton:disabled {{ color: {FAINT}; border-color: {LINE}; }}
QPushButton#primary {{ border-color: {CYAN}; color: {CYAN}; text-align: center; }}
QPushButton#primary:hover {{ background: {CYAN}; color: {BG}; }}
QPushButton#primary:disabled {{ border-color: {LINE}; color: {FAINT}; }}
QPushButton#danger {{ border-color: {RED}; color: {RED}; text-align: center; }}
QPushButton#danger:hover {{ background: {RED}; color: {BG}; }}
QPushButton#danger:disabled {{ border-color: {LINE}; color: {FAINT}; }}
QPushButton#nav {{ border: none; border-left: 2px solid transparent; padding: 7px 12px; color: {DIM}; }}
QPushButton#nav:hover {{ color: {TEXT}; background: rgba(255,255,255,0.03); }}
QPushButton#nav:checked {{ color: {CYAN}; border-left: 2px solid {CYAN}; background: rgba(0,229,255,0.07); }}
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
QTreeWidget::item:selected {{ background: rgba(0,229,255,0.14); color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL2}; color: {DIM}; border: none; border-bottom: 1px solid {LINE};
                        padding: 6px; font-family: {MONO}; font-size: 11px; }}
QTreeWidget::indicator, QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {LINE_HI};
                                                background: {BG}; }}
QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{ background: {CYAN}; border-color: {CYAN}; }}
QTreeWidget::indicator:disabled {{ background: {PANEL2}; border-color: {LINE}; }}
QCheckBox {{ font-family: {MONO}; font-size: 12px; color: {DIM}; spacing: 8px; }}

QPlainTextEdit#console {{ background: #03050a; border: none; border-top: 1px solid {LINE};
                          font-family: {MONO}; font-size: 12px; color: {GREEN}; padding: 6px 10px; }}
QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QScrollArea {{ background: transparent; border: none; }}
QDialog {{ background: {PANEL}; }}
QMenu {{ background: {PANEL2}; border: 1px solid {LINE_HI}; font-family: {MONO}; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.15); color: {CYAN}; }}
"""
