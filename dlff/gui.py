"""dl_font_fixer window: scan fonts, explain what's wrong, unlock and purge them."""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QModelIndex, QRect, QRectF, QSize, Qt, QThread,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QIcon, QPainter,
                           QPen)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QMainWindow, QMenu,
                               QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStyle, QStyledItemDelegate,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import actions, scanner, winapi
from . import theme as T
from .common import APP_NAME, APP_VERSION, BACKUP_DIR, asset, human_size, load_settings, save_settings

EXPLAIN = {
    "ghost": ("GHOST ENTRY",
              "Windows still lists this font in the registry, but the file is gone. Apps (Adobe especially) "
              "see a font that can't load: missing glyphs, red-dot conflicts, fallback fonts.",
              "Purge removes the dead registry entry."),
    "adobe": ("ADOBE FONTS CONFLICT",
              "The same font is also activated through Adobe Fonts (Creative Cloud). Two copies with the same "
              "name fight each other: Adobe apps flag it as missing or conflicting, or pick the wrong copy with "
              "missing weights.",
              "Purge the local copy (checked below), then RESTART ADOBE CC so Creative Cloud re-syncs it."),
    "duplicate": ("DUPLICATE INSTALL",
                  "The same font (PostScript name) is installed more than once, often once for you and once for "
                  "all users, or two versions of the file. Apps may use the older or broken one.",
                  "Purge the extra copies (checked); one copy of each is kept."),
    "orphan": ("ORPHAN FILE",
               "The file sits in a Fonts folder but nothing registers it, so Windows doesn't load it, and Font "
               "Settings can't remove it. Usually left behind by a half-finished install or uninstall.",
               "Purge deletes the leftover file."),
    "unreadable": ("BROKEN FILE",
                   "The file is in the Fonts folder but isn't a readable font (damaged or wrong format).",
                   "Purge deletes it."),
}


def mono(px, bold=False):
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas"])
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def brackets(p, r, color, L=8, w=1.5):
    p.setPen(QPen(QColor(color), w))
    x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
    for (x, y, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        p.drawLine(x, y, x + dx * L, y)
        p.drawLine(x, y, x, y + dy * L)


def qcolor(hexs, alpha=255):
    c = QColor(hexs)
    c.setAlpha(alpha)
    return c


# ---------------------------------------------------------------- background worker

class Worker(QThread):
    log = Signal(str, str)
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kw):
        super().__init__()
        self.fn, self.args, self.kw = fn, args, kw

    def run(self):
        try:
            kw = dict(self.kw)
            if kw.pop("_wants_log", True):
                kw["log"] = lambda t, lvl="info": self.log.emit(str(t), lvl)
            if kw.pop("_wants_progress", False):
                kw["progress"] = lambda a, b, t: self.progress.emit(a, b, t)
            self.done.emit(self.fn(*self.args, **kw))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- painted widgets

class GridRoot(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        p.setPen(QPen(qcolor(T.CYAN, 9), 1))
        step = 28
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)


class Panel(QFrame):
    """Translucent box with HUD corner brackets."""

    def __init__(self, accent=T.LINE_HI, parent=None):
        super().__init__(parent)
        self.accent = accent

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(r, qcolor(T.PANEL, 225))
        p.setPen(QPen(QColor(T.LINE), 1))
        p.drawRect(r)
        brackets(p, r, self.accent, 10)


class StatTile(QAbstractButton):
    def __init__(self, label, color, key, parent=None):
        super().__init__(parent)
        self.label, self.color, self.key = label, color, key
        self.value = 0
        self._shown = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(118, 64)
        self.anim = QVariantAnimation(self, duration=700, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._shown = v
        self.update()

    def set_value(self, v):
        self.value = v
        self.anim.stop()
        self.anim.setStartValue(float(self._shown))
        self.anim.setEndValue(float(v))
        self.anim.start()

    def sizeHint(self):
        return QSize(130, 64)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        hot = self.isChecked() or self.underMouse()
        p.fillRect(r, qcolor(self.color, 30) if self.isChecked() else qcolor(T.PANEL, 225))
        p.setPen(QPen(qcolor(self.color, 255 if self.isChecked() else 60), 1))
        p.drawRect(r)
        if hot:
            brackets(p, r, self.color, 7)
        live = self.value > 0 and self.key not in ("all", "faces")
        p.setPen(QColor(self.color if live or self.key == "all" else T.DIM))
        p.setFont(mono(24, True))
        p.drawText(QRect(14, 6, r.width() - 20, 34), Qt.AlignLeft | Qt.AlignVCenter, f"{round(self._shown):,}")
        p.setPen(QColor(T.DIM))
        f = mono(10)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.drawText(QRect(14, 40, r.width() - 20, 16), Qt.AlignLeft | Qt.AlignVCenter, self.label)
        if live:
            p.setBrush(QColor(self.color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(r.right() - 14, 10, 6, 6))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()


class ScanBar(QWidget):
    """Thin progress line with a moving glow; shows text while busy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.busy, self.frac, self.text, self.phase = False, 0.0, "", 0.0
        self.t = QTimer(self, interval=30, timeout=self._step)

    def start(self, text):
        self.busy, self.frac, self.text = True, 0.0, text
        self.t.start()
        self.update()

    def set(self, done, total, text):
        self.frac = done / max(1, total)
        self.text = text
        self.update()

    def stop(self, text=""):
        self.busy, self.frac, self.text = False, 1.0, text
        self.t.stop()
        self.update()

    def _step(self):
        self.phase = (self.phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setFont(mono(11))
        p.setPen(QColor(T.CYAN if self.busy else T.DIM))
        p.drawText(QRect(2, 0, w - 4, h - 5), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(p.font()).elidedText(self.text, Qt.ElideMiddle, w - 4))
        y = h - 2
        p.fillRect(0, y, w, 2, QColor(T.LINE))
        if self.busy:
            p.fillRect(0, y, int(w * self.frac), 2, QColor(T.CYAN))
            gx = int(w * self.phase)
            for i in range(60):
                p.fillRect(gx - i * 2, y - 1, 2, 4, qcolor(T.CYAN, max(0, 200 - i * 4)))
        elif self.frac >= 1:
            p.fillRect(0, y, w, 2, qcolor(T.CYAN, 90))


class Chip(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("chip")
        self.setCursor(Qt.PointingHandCursor)
        self.color = T.DIM

    def set_state(self, text, color, tip=""):
        self.setText(f"●  {text}")
        self.color = color
        self.setToolTip(tip)
        self.setStyleSheet(f"QPushButton#chip {{ color: {color}; border-color: {T.LINE}; }}"
                           f"QPushButton#chip:hover {{ border-color: {color}; background: rgba(255,255,255,0.03); }}")


# ---------------------------------------------------------------- family list

ROLE_FAM = Qt.UserRole + 1


class FamilyModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        fam = self.items[idx.row()]
        if role == ROLE_FAM:
            return fam
        if role == Qt.DisplayRole:
            return fam.name
        return None


class FamilyDelegate(QStyledItemDelegate):
    H = 70

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = set()

    def refresh_fonts(self):
        self.available = {f.lower() for f in QFontDatabase.families()}

    def sizeHint(self, option, index):
        return QSize(300, self.H)

    def paint(self, p, option, index):
        fam = index.data(ROLE_FAM)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = option.rect.adjusted(4, 3, -8, -3)
        sel = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.fillRect(r, qcolor(T.PANEL2, 240) if sel else qcolor(T.PANEL, 215))
        p.setPen(QPen(QColor(T.CYAN if sel else (T.LINE_HI if hover else T.LINE)), 1))
        p.drawRect(r)
        if sel:
            brackets(p, r, T.CYAN, 8, 2)

        iss = [i for i in scanner.ISSUE_ORDER if i in fam.issues]
        accent = T.ISSUE_COLOR[iss[0]] if iss else qcolor(T.GREEN, 120)
        p.fillRect(QRect(r.left(), r.top(), 3, r.height()), QColor(accent))

        # badges (right side)
        p.setFont(mono(10, True))
        fm = p.fontMetrics()
        x = r.right() - 10
        for i in reversed(iss):
            t = scanner.ISSUE_LABEL[i]
            bw = fm.horizontalAdvance(t) + 14
            br = QRect(x - bw, r.top() + 12, bw, 18)
            col = T.ISSUE_COLOR[i]
            p.fillRect(br, qcolor(col, 28))
            p.setPen(QPen(QColor(col), 1))
            p.drawRect(br)
            p.drawText(br, Qt.AlignCenter, t)
            x -= bw + 6
        if not iss:
            t = "OK"
            br = QRect(x - 30, r.top() + 12, 30, 18)
            p.setPen(QPen(qcolor(T.GREEN, 160), 1))
            p.drawText(br, Qt.AlignCenter, t)
            x -= 36

        # family name in its own font
        has = fam.name.lower() in self.available
        nf = QFont(fam.name) if has else mono(16)
        nf.setPixelSize(21 if has else 16)
        if not has:
            nf.setItalic(True)
        p.setFont(nf)
        p.setPen(QColor(T.TEXT if has else T.DIM))
        name_rect = QRect(r.left() + 16, r.top() + 6, x - r.left() - 24, 32)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(nf).elidedText(fam.name, Qt.ElideRight, name_rect.width()))

        # meta line
        local = fam.local_faces
        scopes = [s for s in ("user", "system", "other") if s in fam.scopes]
        meta = f"{len(local)} FACE{'S' if len(local) != 1 else ''}"
        if scopes:
            meta += "  ·  " + " + ".join(s.upper() for s in scopes)
        if "adobe" in fam.scopes:
            meta += "  ·  ADOBE FONTS"
        if fam.size:
            meta += f"  ·  {human_size(fam.size)}"
        if any(f.variable for f in fam.faces):
            meta += "  ·  VARIABLE"
        p.setFont(mono(11))
        p.setPen(QColor(T.DIM))
        p.drawText(QRect(r.left() + 16, r.top() + 40, r.width() - 30, 20), Qt.AlignLeft | Qt.AlignVCenter, meta)
        p.restore()


# ---------------------------------------------------------------- dialogs

class HudDialog(QDialog):
    def __init__(self, parent, title, html, buttons=(("CANCEL", "", False), ("OK", "primary", True)), wide=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result_key = None
        self.setMinimumWidth(720 if wide else 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        h = QLabel(f"// {title.upper()}")
        h.setObjectName("h")
        lay.addWidget(h)
        body = QLabel(html)
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if wide:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(body)
            sa.setMinimumHeight(320)
            lay.addWidget(sa)
        else:
            lay.addWidget(body)
        row = QHBoxLayout()
        row.addStretch()
        for text, kind, is_default in buttons:
            b = QPushButton(text)
            if kind:
                b.setObjectName(kind)
            b.setMinimumWidth(120)
            b.clicked.connect(lambda _=False, t=text: self._pick(t))
            if is_default:
                b.setDefault(True)
            row.addWidget(b)
        lay.addLayout(row)
        winapi.dark_title_bar(int(self.winId()), (10, 14, 21))

    def _pick(self, t):
        self.result_key = t
        self.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.PANEL))
        brackets(p, self.rect().adjusted(6, 6, -7, -7), T.CYAN, 12)


def ask(parent, title, html, ok="OK", danger=False, cancel="CANCEL"):
    d = HudDialog(parent, title, html, ((cancel, "", False), (ok, "danger" if danger else "primary", True)))
    d.exec()
    return d.result_key == ok


def info(parent, title, html, wide=False):
    HudDialog(parent, title, html, (("CLOSE", "primary", True),), wide=wide).exec()


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def css_name(name):
    return str(name).replace('"', "").replace("\\", "")


def c(text, color):
    return f'<span style="color:{color}">{esc(text)}</span>'


# ---------------------------------------------------------------- inspector

class Inspector(QWidget):
    purge_requested = Signal(list, bool)
    locks_requested = Signal(list)
    adobe_restart = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.families = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QWidget()
        body.setObjectName("ibody")
        sa = QScrollArea()
        sa.setStyleSheet("QScrollArea { background: transparent; } "
                         "QWidget#qt_scrollarea_viewport { background: transparent; } "
                         "QWidget#ibody { background: transparent; }")
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(body)
        sa.viewport().setAutoFillBackground(False)
        outer.addWidget(sa, 1)
        foot = QWidget()
        foot.setObjectName("foot")
        foot.setAttribute(Qt.WA_StyledBackground, True)
        foot.setStyleSheet(f"QWidget#foot {{ background: rgba(10,14,21,0.94); border-top: 1px solid {T.LINE}; }}")
        flay = QVBoxLayout(foot)
        flay.setContentsMargins(18, 10, 18, 12)
        flay.setSpacing(8)
        outer.addWidget(foot)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        h = QLabel("// INSPECTOR")
        h.setObjectName("h")
        lay.addWidget(h)
        self.title = QLabel("Select a font family")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"font-size: 26px; color: {T.TEXT};")
        lay.addWidget(self.title)
        self.sub = QLabel("")
        self.sub.setObjectName("mono")
        self.sub.setStyleSheet(f"color: {T.DIM};")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(70)
        self.preview.setStyleSheet(f"background: {T.PANEL}; border: 1px solid {T.LINE}; padding: 10px;")
        lay.addWidget(self.preview)
        self.sample = QLineEdit("The quick brown fox jumps over the lazy dog 0123456789")
        self.sample.setPlaceholderText("Type sample text…")
        self.sample.textChanged.connect(self._update_preview)
        lay.addWidget(self.sample)

        h = QLabel("// DIAGNOSIS")
        h.setObjectName("h")
        lay.addWidget(h)
        self.diag = QLabel("")
        self.diag.setWordWrap(True)
        self.diag.setTextFormat(Qt.RichText)
        self.diag.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.diag)

        h = QLabel("// FACES   (checked = will be purged)")
        h.setObjectName("h")
        lay.addWidget(h)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["STYLE", "STATUS", "WHERE", "FILE"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(170)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.header().setMinimumSectionSize(40)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Interactive)
        self.tree.itemChanged.connect(lambda *_: self._update_buttons())
        self.tree.itemDoubleClicked.connect(self._reveal)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.b_all = QPushButton("ALL")
        self.b_all.clicked.connect(lambda: self._check_all(True))
        self.b_none = QPushButton("NONE")
        self.b_none.clicked.connect(lambda: self._check_all(False))
        self.b_locks = QPushButton("⌕ LOCKS")
        self.b_locks.setToolTip("Ask Windows (Restart Manager) which programs have these font files open")
        self.b_locks.clicked.connect(lambda: self.locks_requested.emit(self.checked_faces() or self._all_local()))
        self.b_folder = QPushButton("FOLDER")
        self.b_folder.clicked.connect(self._open_folder)
        for b in (self.b_all, self.b_none, self.b_locks, self.b_folder):
            b.setStyleSheet("text-align: center; padding: 8px 6px;")
            b.setMinimumWidth(60)
            row.addWidget(b)

        self.locks = QLabel("")
        self.locks.setWordWrap(True)
        self.locks.setTextFormat(Qt.RichText)
        self.locks.hide()
        lay.addWidget(self.locks)

        lay = flay      # the rest stays visible below the scrolling part
        lay.addLayout(row)
        self.unlock = QCheckBox("Auto-unlock (stop FontCache / restart Explorer if locked)")
        self.unlock.setChecked(True)
        lay.addWidget(self.unlock)
        self.b_purge = QPushButton("⚠  PURGE CHECKED FACES")
        self.b_purge.setObjectName("danger")
        self.b_purge.setMinimumHeight(42)
        self.b_purge.clicked.connect(lambda: self.purge_requested.emit(self.checked_faces(), self.unlock.isChecked()))
        lay.addWidget(self.b_purge)
        self.b_adobe = QPushButton("⟳  RESTART ADOBE CREATIVE CLOUD")
        self.b_adobe.setObjectName("primary")
        self.b_adobe.clicked.connect(self.adobe_restart.emit)
        self.b_adobe.hide()
        lay.addWidget(self.b_adobe)
        self.show_families([])

    # ---- content
    def show_families(self, fams):
        self.families = fams
        self.locks.hide()
        self.tree.blockSignals(True)
        self.tree.clear()
        if not fams:
            self.title.setText("Select a font family")
            self.title.setStyleSheet(f"font-size: 22px; color: {T.DIM};")
            self.sub.setText("Pick a family on the left. Ctrl/Shift-click selects several.")
            self.preview.hide()
            self.sample.hide()
            self.diag.setText(c("—", T.DIM))
            self.tree.blockSignals(False)
            self._update_buttons()
            self.b_adobe.hide()
            return
        self.preview.show()
        self.sample.show()
        multi = len(fams) > 1
        if multi:
            self.title.setStyleSheet(f"font-size: 24px; color: {T.TEXT};")
            self.title.setText(f"{len(fams)} families")
            self.sub.setText(", ".join(f.name for f in fams[:12]) + (" …" if len(fams) > 12 else ""))
        else:
            fam = fams[0]
            self.title.setText(fam.name)
            self.title.setStyleSheet(f'color: {T.TEXT}; font-family: "{css_name(fam.name)}"; font-size: 30px;')
            loc = sorted({x.scope.upper() for x in fam.faces})
            self.sub.setText(f"{len(fam.local_faces)} installed face(s)  ·  {' / '.join(loc)}  ·  "
                             f"{human_size(fam.size)}")
        self._update_preview()

        issues = set()
        for fam in fams:
            issues |= fam.issues
        if issues:
            parts = []
            for key in scanner.ISSUE_ORDER:
                if key in issues:
                    t, why, fix = EXPLAIN[key]
                    col = T.ISSUE_COLOR[key]
                    parts.append(f'<div style="margin-bottom:8px"><span style="color:{col};font-family:Consolas;'
                                 f'font-weight:bold">■ {t}</span><br><span style="color:{T.TEXT}">{esc(why)}</span>'
                                 f'<br><span style="color:{T.CYAN}">→ {esc(fix)}</span></div>')
            self.diag.setText("".join(parts))
        else:
            self.diag.setText(c("■ NO PROBLEMS FOUND. ", T.GREEN) +
                              c("This family is registered correctly and every file exists. You can still "
                                "check faces below and purge them to remove the font completely.", T.TEXT))
        self.b_adobe.setVisible("adobe" in issues)

        for fam in fams:
            for face in fam.faces:
                st = [scanner.ISSUE_LABEL[i] for i in scanner.ISSUE_ORDER if i in face.issues] or ["OK"]
                if face.scope == "adobe":
                    st = ["ADOBE FONTS (synced)"] + [s for s in st if s not in ("OK", "ADOBE CONFLICT")]
                if face.protected:
                    st.append("PROTECTED")
                if face.extra:
                    st.append("EXTRA COPY")
                style = f"{fam.name} · {face.style}" if multi else (face.style or "—")
                where = face.scope.upper() + ("".join(f" {h}" for h, *_ in face.reg[:1]))
                fn = Path(face.path).name if face.scope != "adobe" else "livetype\\r\\" + Path(face.path).name
                it = QTreeWidgetItem([style, "  ".join(st), where, fn])
                it.setData(0, Qt.UserRole, face)
                tip = [face.path]
                if face.full_name:
                    tip.insert(0, f"{face.full_name}   ({face.ps_name})")
                for h, n, d in face.reg:
                    tip.append(f"{h}  \"{n}\" = {d}")
                if face.version:
                    tip.append(face.version)
                if face.note:
                    tip.append(face.note)
                for col in range(4):
                    it.setToolTip(col, "\n".join(tip))
                key = next((i for i in scanner.ISSUE_ORDER if i in face.issues), None)
                if face.scope == "adobe":
                    it.setForeground(1, QColor(T.VIOLET))
                elif key:
                    it.setForeground(1, QColor(T.ISSUE_COLOR[key]))
                else:
                    it.setForeground(1, QColor(T.GREEN))
                it.setForeground(2, QColor(T.SCOPE_COLOR.get(face.scope, T.DIM)))
                if face.purgeable:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    default = bool(face.issues & {"ghost", "adobe", "orphan", "unreadable"}) or face.extra
                    it.setCheckState(0, Qt.Checked if default else Qt.Unchecked)
                else:
                    it.setFlags((it.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEnabled)
                    it.setCheckState(0, Qt.Unchecked)
                    for col in range(4):
                        it.setForeground(col, QColor(T.FAINT)) if face.protected else None
                    reason = ("Adobe Fonts copy: manage it in the Creative Cloud app (Fonts tab)"
                              if face.scope == "adobe" else "Windows system font: never removed")
                    it.setToolTip(0, reason)
                self.tree.addTopLevelItem(it)
        fm = QFontMetrics(mono(12))
        widths = [max([fm.horizontalAdvance(self.tree.topLevelItem(i).text(col))
                       for i in range(self.tree.topLevelItemCount())] + [40]) for col in range(3)]
        self.tree.setColumnWidth(0, min(widths[0] + 52, 260))
        self.tree.setColumnWidth(1, min(widths[1] + 20, 260))
        self.tree.setColumnWidth(2, widths[2] + 20)
        self.tree.blockSignals(False)
        self._update_buttons()

    def _update_preview(self):
        if not self.families:
            return
        fam = self.families[0]
        self.preview.setStyleSheet(f'background: {T.PANEL}; border: 1px solid {T.LINE}; padding: 10px; '
                                   f'font-family: "{css_name(fam.name)}"; font-size: 26px;')
        self.preview.setText(self.sample.text() or fam.name)

    def checked_faces(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                out.append(it.data(0, Qt.UserRole))
        return out

    def _all_local(self):
        return [f for fam in self.families for f in fam.faces if f.scope != "adobe"]

    def _check_all(self, on):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.flags() & Qt.ItemIsEnabled:
                it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self):
        n = len(self.checked_faces())
        self.b_purge.setEnabled(n > 0)
        self.b_purge.setText(f"⚠  PURGE {n} CHECKED FACE{'S' if n != 1 else ''}" if n else "⚠  PURGE CHECKED FACES")
        has = bool(self.families)
        for b in (self.b_all, self.b_none, self.b_locks, self.b_folder):
            b.setEnabled(has)

    def show_locks(self, result):
        lines = []
        for path, lk in result.items():
            name = esc(Path(path).name)
            if lk:
                who = ", ".join(esc(x.get("service") or x.get("exe") or x["name"]) + f" <span style='color:{T.DIM}'>"
                                f"(pid {x['pid']})</span>" for x in lk)
                lines.append(f"<span style='color:{T.AMBER}'>🔒 {name}</span> &nbsp;← {who}")
            else:
                lines.append(f"<span style='color:{T.GREEN}'>✓ {name}</span> <span style='color:{T.DIM}'>"
                             f"not open in any program</span>")
        if not lines:
            lines = [c("No files on disk to check (ghost entries have no file).", T.DIM)]
        self.locks.setText(f"<div style='font-family:Consolas;font-size:12px'>{'<br>'.join(lines)}</div>")
        self.locks.show()

    def _current_face(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _reveal(self, it, col=0):
        face = it.data(0, Qt.UserRole)
        if face and os.path.exists(face.path):
            subprocess.Popen(["explorer.exe", "/select,", face.path])
        elif face:
            folder = Path(face.path).parent
            if folder.exists():
                os.startfile(folder)

    def _open_folder(self):
        face = self._current_face() or (self._all_local() or [None])[0]
        if face:
            it = self.tree.currentItem()
            if it:
                self._reveal(it)
            elif os.path.exists(Path(face.path).parent):
                os.startfile(Path(face.path).parent)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        face = it.data(0, Qt.UserRole)
        m = QMenu(self)
        m.addAction("Show in folder", lambda: self._reveal(it))
        m.addAction("Copy file path", lambda: QGuiApplication.clipboard().setText(face.path))
        if face.reg:
            m.addAction("Copy registry entries", lambda: QGuiApplication.clipboard().setText(
                "\n".join(f"{h}\\{scanner.FONTS_KEY}\\{n} = {d}" for h, n, d in face.reg)))
        m.exec(self.tree.viewport().mapToGlobal(pos))


# ---------------------------------------------------------------- main window

FILTERS = [("all", "ALL FAMILIES"), ("issues", "ANY ISSUE"), ("ghost", "GHOSTS"), ("adobe", "ADOBE CONFLICTS"),
           ("duplicate", "DUPLICATES"), ("orphan", "ORPHANS"), ("unreadable", "BROKEN FILES")]
SCOPES = [("any", "ANYWHERE"), ("user", "INSTALLED FOR ME"), ("system", "ALL USERS (SYSTEM)"),
          ("adobe", "ADOBE FONTS")]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} (v{APP_VERSION})")
        ic = asset("icon.png") or asset("icon.ico")
        if ic:
            self.setWindowIcon(QIcon(str(ic)))
        self.families, self.stats = [], {}
        self.filter, self.scope = "all", "any"
        self.workers = set()
        self.busy = False
        self.admin = winapi.is_admin()

        root = GridRoot()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_stats())

        vsplit = QSplitter(Qt.Vertical)
        hsplit = QSplitter(Qt.Horizontal)
        hsplit.addWidget(self._build_sidebar())
        hsplit.addWidget(self._build_center())
        self.inspector = Inspector()
        self.inspector.purge_requested.connect(self.purge)
        self.inspector.locks_requested.connect(self.scan_locks)
        self.inspector.adobe_restart.connect(self.restart_adobe)
        self.inspector.setMinimumWidth(460)
        hsplit.addWidget(self.inspector)
        hsplit.setStretchFactor(0, 0)
        hsplit.setStretchFactor(1, 1)
        hsplit.setStretchFactor(2, 0)
        hsplit.setSizes([230, 600, 560])
        vsplit.addWidget(hsplit)

        self.console = QPlainTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(4000)
        con_wrap = QWidget()
        cl = QVBoxLayout(con_wrap)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 6, 10, 4)
        lab = QLabel("// CONSOLE")
        lab.setObjectName("h")
        bar.addWidget(lab)
        bar.addStretch()
        clr = QPushButton("CLEAR")
        clr.setStyleSheet("padding: 2px 10px; font-size: 10px;")
        clr.clicked.connect(self.console.clear)
        bar.addWidget(clr)
        cl.addLayout(bar)
        cl.addWidget(self.console)
        vsplit.addWidget(con_wrap)
        vsplit.setStretchFactor(0, 1)
        vsplit.setSizes([700, 170])
        outer.addWidget(vsplit, 1)

        st = load_settings()
        g = st.get("geometry")
        if g:
            self.restoreGeometry(bytes.fromhex(g))
        else:
            self.resize(1440, 900)
        winapi.dark_title_bar(int(self.winId()), (5, 7, 11))

        self.status_timer = QTimer(self, interval=4000, timeout=self.refresh_status)
        self.status_timer.start()
        self.log(f"{APP_NAME} v{APP_VERSION}  ·  {'ADMINISTRATOR' if self.admin else 'standard user'}  ·  "
                 f"backups in {BACKUP_DIR}", "info")
        if not self.admin:
            self.log("Running without admin rights: fonts installed for you can be fixed; fonts installed for all "
                     "users, the font cache and the reboot queue need ADMIN (top right).", "warn")
        QTimer.singleShot(150, self.refresh_status)
        QTimer.singleShot(250, self.scan)

    # ---- layout pieces
    def _build_header(self):
        w = QWidget()
        w.setFixedHeight(62)
        w.setStyleSheet(f"background: rgba(10,14,21,0.92); border-bottom: 1px solid {T.LINE};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(10)
        logo = QLabel(f'<span style="color:{T.CYAN}">◢◤</span>&nbsp;<b>DL</b><span style="color:{T.CYAN}">//</span>'
                      f'<b>FONT_FIXER</b>')
        logo.setStyleSheet(f"font-family: {T.MONO}; font-size: 19px; letter-spacing: 2px; border: none;"
                           f"background: transparent;")
        lay.addWidget(logo)
        ver = QLabel(f"v{APP_VERSION}  ·  SCAN / UNLOCK / PURGE")
        ver.setStyleSheet(f"font-family: {T.MONO}; font-size: 11px; color: {T.DIM}; border: none; "
                          f"background: transparent; padding-top: 4px;")
        lay.addWidget(ver)
        lay.addStretch()
        self.chip_cache = Chip("FONTCACHE")
        self.chip_cache.clicked.connect(self.rebuild_cache)
        self.chip_adobe = Chip("ADOBE CC")
        self.chip_adobe.clicked.connect(self.restart_adobe)
        self.chip_reboot = Chip("REBOOT QUEUE")
        self.chip_reboot.clicked.connect(self.show_pending)
        self.chip_admin = Chip("ADMIN")
        self.chip_admin.clicked.connect(self.elevate)
        for ch in (self.chip_cache, self.chip_adobe, self.chip_reboot, self.chip_admin):
            lay.addWidget(ch)
        self.b_scan = QPushButton("⟳  RESCAN")
        self.b_scan.setObjectName("primary")
        self.b_scan.setMinimumWidth(120)
        self.b_scan.clicked.connect(self.scan)
        lay.addSpacing(6)
        lay.addWidget(self.b_scan)
        return w

    def _build_stats(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 12, 14, 8)
        lay.setSpacing(10)
        self.tiles = {}
        for key, label, col in (("all", "FAMILIES", T.CYAN), ("faces", "FONT FILES", T.DIM),
                                ("ghost", "GHOSTS", T.RED), ("adobe", "ADOBE CONFLICTS", T.VIOLET),
                                ("duplicate", "DUPLICATES", T.AMBER), ("orphan", "ORPHANS", T.BLUE),
                                ("unreadable", "BROKEN", T.RED)):
            t = StatTile(label, col, key)
            t.clicked.connect(lambda _=False, k=key: self.set_filter("all" if k == "faces" else k))
            lay.addWidget(t, 1)
            self.tiles[key] = t
        return w

    def _build_sidebar(self):
        w = QWidget()
        w.setMinimumWidth(210)
        w.setMaximumWidth(300)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 6, 6, 10)
        lay.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕  search family / file…")
        self.search.textChanged.connect(self.apply_filter)
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        lay.addSpacing(12)

        def head(t):
            l = QLabel(t)
            l.setObjectName("h")
            l.setContentsMargins(4, 8, 0, 4)
            lay.addWidget(l)

        head("// FILTER")
        self.nav_filter = {}
        for key, label in FILTERS:
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            lay.addWidget(b)
            self.nav_filter[key] = b
        head("// LOCATION")
        self.nav_scope = {}
        for key, label in SCOPES:
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_scope(k))
            lay.addWidget(b)
            self.nav_scope[key] = b
        head("// SYSTEM OPS")
        ops = [("✕  CLEAN ALL GHOSTS", self.clean_ghosts, "Remove every registry entry that points to a missing file"),
               ("▣  REBUILD FONT CACHE", self.rebuild_cache, "Stop FontCache, delete FNTCACHE.DAT and the cache "
                                                             "files, start it again (admin)"),
               ("⟳  RESTART ADOBE CC", self.restart_adobe, "Close Creative Cloud / CoreSync / CCXProcess and start "
                                                          "Creative Cloud again so Adobe Fonts re-sync"),
               ("⟳  RESTART EXPLORER", self.restart_explorer, "Explorer keeps font files open for previews"),
               ("◷  REBOOT QUEUE", self.show_pending, "Files queued for deletion at the next restart"),
               ("⛁  BACKUPS / RESTORE", self.show_backups, "Every purge is backed up first")]
        for text, fn, tip in ops:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            lay.addWidget(b)
        lay.addStretch()
        self.nav_filter["all"].setChecked(True)
        self.nav_scope["any"].setChecked(True)
        return w

    def _build_center(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        top = QHBoxLayout()
        self.list_head = QLabel("// FONT FAMILIES")
        self.list_head.setObjectName("h")
        top.addWidget(self.list_head)
        top.addStretch()
        lay.addLayout(top)
        self.bar = ScanBar()
        lay.addWidget(self.bar)
        self.model = FamilyModel()
        self.view = QListView()
        self.view.setModel(self.model)
        self.delegate = FamilyDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setUniformItemSizes(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setMouseTracking(True)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        lay.addWidget(self.view, 1)
        return w

    # ---- logging
    def log(self, text, level="info"):
        col = T.LOG_COLOR.get(level, T.TEXT)
        ts = datetime.now().strftime("%H:%M:%S")
        tag = {"ok": "OK ", "warn": "!! ", "err": "ERR", "cmd": "$  ", "info": ">  "}.get(level, ">  ")
        self.console.appendHtml(f'<span style="color:{T.FAINT}">[{ts}]</span> <span style="color:{col}">'
                                f'{tag} {esc(text)}</span>')

    # ---- workers
    def run_bg(self, fn, *args, on_done=None, progress=False, label="", **kw):
        if self.busy:
            self.log("Busy: wait for the current task to finish", "warn")
            return
        self.busy = True
        self.b_scan.setEnabled(False)
        w = Worker(fn, *args, _wants_progress=progress, **kw)
        w.log.connect(self.log)
        if progress:
            w.progress.connect(lambda a, b, t: self.bar.set(a, b, f"SCANNING  {a}/{b}   {t}"))
        self.bar.start(label or "WORKING…")

        def finish(result):
            self.busy = False
            self.b_scan.setEnabled(True)
            self.bar.stop("")
            if on_done:
                on_done(result)
            self.refresh_status()

        def fail(msg):
            self.log(msg, "err")
            finish(None)

        w.done.connect(finish)
        w.failed.connect(fail)
        w.finished.connect(lambda: self.workers.discard(w))
        self.workers.add(w)
        w.start()

    # ---- scan
    def scan(self):
        self.log("Scanning registry (HKLM + HKCU), C:\\Windows\\Fonts, your user Fonts folder and Adobe Fonts…",
                 "info")
        t0 = time.time()

        def done(res):
            if not res:
                return
            self.families, self.stats = res
            self.delegate.refresh_fonts()
            s = self.stats
            for k, t in self.tiles.items():
                t.set_value(s.get("families" if k == "all" else k, 0))
            self.log(f"Scan done in {time.time() - t0:.1f}s: {s['families']} families, {s['faces']} files "
                     f"({s['user']} yours, {s['system']} system, {s['adobe_faces']} Adobe Fonts).", "ok")
            found = [f"{s[k]} {n}" for k, n in (("ghost", "ghost entries"), ("adobe", "Adobe conflicts"),
                                                 ("duplicate", "duplicate files"), ("orphan", "orphan files"),
                                                 ("unreadable", "broken files")) if s[k]]
            self.log("Found: " + (", ".join(found) if found else "no problems"), "warn" if found else "ok")
            self.bar.stop(f"LAST SCAN {datetime.now():%H:%M:%S}  ·  {s['families']} FAMILIES  ·  "
                          f"{sum(s[k] for k in ('ghost', 'orphan', 'unreadable')) + s['duplicate']} ISSUE FILES")
            self.apply_filter()

        self.run_bg(scanner.scan, on_done=done, progress=True, label="SCANNING…", _wants_log=False)

    # ---- filtering
    def set_filter(self, key):
        self.filter = key
        for k, b in self.nav_filter.items():
            b.setChecked(k == key)
        for k, t in self.tiles.items():
            t.setChecked(k == key and key != "all")
        self.apply_filter()

    def set_scope(self, key):
        self.scope = key
        for k, b in self.nav_scope.items():
            b.setChecked(k == key)
        self.apply_filter()

    def apply_filter(self):
        q = self.search.text().strip().lower()
        keep_keys = {f.key for f in self.selected_families()}
        out = []
        for fam in self.families:
            iss = fam.issues
            if self.filter == "issues" and not iss:
                continue
            if self.filter not in ("all", "issues") and self.filter not in iss:
                continue
            if self.filter == "adobe" and not fam.local_faces:
                continue
            if self.scope != "any" and self.scope not in fam.scopes:
                continue
            if self.scope == "any" and self.filter == "all" and fam.scopes == {"adobe"} and not q:
                pass
            if q and q not in fam.name.lower() and not any(q in Path(f.path).name.lower() or
                                                           q in (f.ps_name or "").lower() for f in fam.faces):
                continue
            out.append(fam)
        if self.filter != "all":
            out.sort(key=lambda f: (f.severity(), f.name.lower()))
        self.model.set_items(out)
        label = dict(FILTERS).get(self.filter, "")
        self.list_head.setText(f"// FONT FAMILIES  ·  {label}  ·  {len(out)} SHOWN")
        sel = self.view.selectionModel()
        restored = False
        for row, fam in enumerate(out):
            if fam.key in keep_keys:
                sel.select(self.model.index(row), sel.SelectionFlag.Select)
                if not restored:
                    self.view.scrollTo(self.model.index(row))
                restored = True
        if not restored:
            self.inspector.show_families([])

    def selected_families(self):
        try:
            return [i.data(ROLE_FAM) for i in sorted(self.view.selectionModel().selectedIndexes(),
                                                     key=lambda i: i.row())]
        except Exception:
            return []

    def _selection_changed(self, *_):
        self.inspector.show_families(self.selected_families())

    # ---- status chips
    def refresh_status(self):
        cache = actions.service_state("FontCache")
        col = T.GREEN if cache == "running" else (T.AMBER if cache else T.DIM)
        self.chip_cache.set_state(f"FONTCACHE {str(cache or 'n/a').upper()}", col,
                                  "Windows Font Cache Service. Click to rebuild the font cache (admin).")
        a = actions.adobe_status()
        if a["running"]:
            tip = "Creative Cloud is running. Click to restart it (re-syncs Adobe Fonts)."
            if a["apps"]:
                tip += "\nOpen Adobe apps: " + ", ".join(a["apps"])
            self.chip_adobe.set_state("ADOBE CC ONLINE" + (f" · {len(a['apps'])} APP" if a["apps"] else ""),
                                      T.VIOLET, tip)
        else:
            self.chip_adobe.set_state("ADOBE CC OFF", T.DIM, "Creative Cloud is not running. Click to start it.")
        n = len(actions.pending_font_operations())
        self.chip_reboot.set_state(f"REBOOT QUEUE {n}", T.AMBER if n else T.DIM,
                                   f"{n} font file(s) will be deleted at the next restart" if n
                                   else "Nothing queued for the next restart")
        if self.admin:
            self.chip_admin.set_state("ADMIN", T.GREEN, "Running as administrator")
        else:
            self.chip_admin.set_state("ADMIN OFF · ELEVATE", T.AMBER, "Click to restart as administrator")

    # ---- actions
    def elevate(self):
        if self.admin:
            info(self, "Administrator", "Already running as administrator.")
            return
        if ask(self, "Restart as administrator",
               "Restart dl_font_fixer with administrator rights?<br><br>Needed to fix fonts installed "
               "<b>for all users</b> (C:\\Windows\\Fonts, HKLM), rebuild the font cache and queue locked files "
               "for deletion at the next restart.", ok="ELEVATE"):
            if winapi.relaunch_as_admin():
                self._save()
                QApplication.quit()
            else:
                self.log("Elevation was cancelled", "warn")

    def scan_locks(self, faces):
        paths = [f.path for f in faces if f.exists]
        self.log(f"Asking Restart Manager who has {len(paths)} file(s) open…", "cmd")

        def done(res):
            if res is None:
                return
            locked = {p: lk for p, lk in res.items() if lk}
            for p, lk in locked.items():
                self.log(f"{Path(p).name} locked by " + ", ".join(
                    f"{x.get('service') or x.get('exe') or x['name']} ({x['pid']})" for x in lk), "warn")
            self.log(f"{len(locked)} of {len(res)} file(s) locked", "warn" if locked else "ok")
            self.inspector.show_locks(res)

        self.run_bg(actions.check_locks, paths, on_done=done, label="CHECKING LOCKS…", _wants_log=False)

    def purge(self, faces, unlock):
        faces = [f for f in faces if f.purgeable]
        if not faces:
            return
        fams = sorted({f.family for f in faces})
        need_admin = [f for f in faces if f.scope != "user" or any(h == "HKLM" for h, *_ in f.reg)]
        adobe = actions.adobe_status()
        rows = "".join(f"<tr><td style='color:{T.TEXT};padding-right:14px'>{esc(f.family)} {esc(f.style)}</td>"
                       f"<td style='color:{T.SCOPE_COLOR.get(f.scope, T.DIM)};padding-right:14px'>{f.scope}</td>"
                       f"<td style='color:{T.DIM}'>{esc(Path(f.path).name)}"
                       f"{'' if f.exists else ' (missing)'}</td></tr>" for f in faces[:40])
        more = f"<br>… and {len(faces) - 40} more" if len(faces) > 40 else ""
        warn = ""
        if need_admin and not self.admin:
            warn += (f"<p style='color:{T.AMBER}'>⚠ {len(need_admin)} of these are installed for all users. "
                     f"Without ADMIN only their per-user parts can be removed.</p>")
        if adobe["apps"]:
            warn += (f"<p style='color:{T.AMBER}'>⚠ Close {', '.join(adobe['apps'])} first: open apps keep "
                     f"fonts loaded.</p>")
        html = (f"<p>Remove <b>{len(faces)}</b> font file(s) from <b>{len(fams)}</b> famil"
                f"{'y' if len(fams) == 1 else 'ies'}: registry entry and file, unlocking them if needed.</p>"
                f"<table style='font-family:Consolas;font-size:12px'>{rows}</table>{more}{warn}"
                f"<p style='color:{T.DIM}'>A backup of every file is saved first (BACKUPS / RESTORE).</p>")
        if not ask(self, "Purge fonts", html, ok="PURGE", danger=True):
            return
        had_adobe = any("adobe" in f.issues for f in faces)
        self.log(f"PURGE {len(faces)} face(s): {', '.join(fams[:6])}{' …' if len(fams) > 6 else ''}", "cmd")

        def done(res):
            if res is None:
                return
            msg = (f"<p>Deleted <b style='color:{T.GREEN}'>{len(res['deleted'])}</b> file(s), removed "
                   f"<b>{res['reg']}</b> registry entr{'y' if res['reg'] == 1 else 'ies'}.</p>")
            if res["renamed"] or res["queued"]:
                msg += (f"<p style='color:{T.AMBER}'>{len(res['renamed'])} locked file(s) renamed to .old, "
                        f"{len(res['queued'])} queued for deletion at the next restart. Windows no longer loads "
                        f"them.</p>")
            if res["failed"]:
                msg += (f"<p style='color:{T.RED}'>{len(res['failed'])} file(s) could not be removed: "
                        f"{esc(', '.join(Path(p).name for p in res['failed'][:8]))}. Restart as ADMIN and try "
                        f"again (they can then be queued for the next restart).</p>")
            if had_adobe and actions.adobe_status()["running"]:
                msg += (f"<p>These fonts were also in Adobe Fonts. Restart Creative Cloud now so it re-syncs "
                        f"the Adobe copy?</p>")
                d = HudDialog(self, "Purge complete", msg, (("LATER", "", False), ("RESTART ADOBE CC", "primary",
                                                                                    True)))
                d.exec()
                if d.result_key == "RESTART ADOBE CC":
                    QTimer.singleShot(200, lambda: self.run_bg(actions.restart_adobe_cc, label="RESTARTING ADOBE CC…",
                                                               on_done=lambda _: QTimer.singleShot(1500, self.scan)))
                    return
            else:
                info(self, "Purge complete", msg)
            self.scan()

        self.run_bg(actions.purge, faces, unlock=unlock, on_done=done, label="PURGING…")

    def clean_ghosts(self):
        ghosts = [f for fam in self.families for f in fam.faces if "ghost" in f.issues and f.purgeable]
        if not ghosts:
            info(self, "Clean ghosts", "No ghost entries found. Every registered font file exists.")
            return
        self.purge(ghosts, False)

    def rebuild_cache(self):
        if not self.admin:
            if ask(self, "Rebuild font cache", "Rebuilding the Windows font cache needs administrator rights."
                                               "<br><br>Restart as administrator now?", ok="ELEVATE"):
                self.elevate()
            return
        if ask(self, "Rebuild font cache",
               "Stop the <b>Windows Font Cache Service</b>, delete <b>FNTCACHE.DAT</b> and the cache files, "
               "then start it again.<br><br>Fixes fonts that show the wrong weight, old versions, or don't show "
               "at all. Apps may look odd until they restart; a Windows restart completes the rebuild.",
               ok="REBUILD"):
            self.run_bg(actions.rebuild_font_cache, label="REBUILDING FONT CACHE…")

    def restart_adobe(self):
        a = actions.adobe_status()
        extra = ""
        if a["apps"]:
            extra = (f"<p style='color:{T.AMBER}'>⚠ Open: {', '.join(a['apps'])}. Save your work and close them, "
                     f"they need a restart to see font changes anyway.</p>")
        text = ("Close Creative Cloud, CoreSync and CCXProcess and start Creative Cloud again. Adobe Fonts "
                "re-sync and red-dot / missing-font conflicts usually clear." if a["running"] else
                "Creative Cloud is not running. Start it now?")
        if ask(self, "Restart Adobe Creative Cloud", text + extra, ok="RESTART CC" if a["running"] else "START CC"):
            self.run_bg(actions.restart_adobe_cc, label="RESTARTING ADOBE CC…")

    def restart_explorer(self):
        if ask(self, "Restart Explorer", "Windows Explorer keeps font files open for thumbnails and previews. "
                                         "Restart it now? The taskbar disappears for a second.", ok="RESTART"):
            self.run_bg(actions.restart_explorer, label="RESTARTING EXPLORER…")

    def show_pending(self):
        ops = actions.pending_font_operations()
        if ops:
            rows = "<br>".join(f"<span style='color:{T.AMBER}'>✕</span> {esc(s)}"
                               f"{' → ' + esc(t) if t else ''}" for s, t in ops)
            html = (f"<p>{len(ops)} font file(s) will be deleted the next time Windows starts:</p>"
                    f"<div style='font-family:Consolas;font-size:12px'>{rows}</div>"
                    f"<p style='color:{T.DIM}'>Restart Windows to finish. No Safe Mode needed.</p>")
        else:
            html = "Nothing queued. Locked fonts that can't be deleted right away are queued here (needs ADMIN)."
        info(self, "Reboot queue", html, wide=bool(ops))

    def show_backups(self):
        bks = actions.list_backups()
        if not bks:
            info(self, "Backups", f"No backups yet. Every purge saves the removed files to<br>{esc(BACKUP_DIR)}")
            return
        d = QDialog(self)
        d.setWindowTitle("Backups")
        d.setMinimumSize(760, 460)
        d.setStyleSheet(f"QDialog {{ background: {T.PANEL}; }}")
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        h = QLabel("// BACKUPS  ·  restore reinstalls the fonts for your user")
        h.setObjectName("h")
        lay.addWidget(h)
        tree = QTreeWidget()
        tree.setHeaderLabels(["DATE", "FILES", "FAMILIES"])
        tree.setRootIsDecorated(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for b in bks:
            n = sum(1 for i in b.get("items", []) if i.get("backup_file"))
            it = QTreeWidgetItem([b.get("date", "").replace("T", "  "), str(n), ", ".join(b.get("families", []))])
            it.setData(0, Qt.UserRole, b["dir"])
            tree.addTopLevelItem(it)
        lay.addWidget(tree, 1)
        row = QHBoxLayout()
        b_open = QPushButton("OPEN FOLDER")
        b_open.clicked.connect(lambda: os.startfile(tree.currentItem().data(0, Qt.UserRole) if tree.currentItem()
                                                    else str(BACKUP_DIR)))
        b_restore = QPushButton("RESTORE SELECTED")
        b_restore.setObjectName("primary")

        def restore():
            it = tree.currentItem()
            if not it:
                return
            if ask(d, "Restore", f"Reinstall the fonts from {esc(it.text(0))} for your user?", ok="RESTORE"):
                d.accept()
                self.run_bg(actions.restore_backup, it.data(0, Qt.UserRole), label="RESTORING…",
                            on_done=lambda _: self.scan())

        b_restore.clicked.connect(restore)
        b_close = QPushButton("CLOSE")
        b_close.clicked.connect(d.accept)
        row.addWidget(b_open)
        row.addStretch()
        row.addWidget(b_restore)
        row.addWidget(b_close)
        lay.addLayout(row)
        winapi.dark_title_bar(int(d.winId()), (10, 14, 21))
        d.exec()

    # ---- close
    def _save(self):
        st = load_settings()
        st["geometry"] = bytes(self.saveGeometry()).hex()
        save_settings(st)

    def closeEvent(self, e):
        self._save()
        for w in list(self.workers):
            w.wait(3000)
        super().closeEvent(e)


def main(argv=None):
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv or [])
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(T.QSS)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"OpenGrapes.{APP_NAME}")
    except Exception:
        pass
    w = MainWindow()
    w.show()
    return app.exec()
