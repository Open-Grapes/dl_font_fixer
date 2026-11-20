"""Find every font Windows knows about and what is wrong with it.

Sources:
  * HKLM and HKCU  ...\\Windows NT\\CurrentVersion\\Fonts   (registry: name -> file)
  * C:\\Windows\\Fonts and %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts   (the files themselves)
  * %APPDATA%\\Adobe\\CoreSync\\plugins\\livetype   (fonts activated through Adobe Fonts / Creative Cloud)

Issues per face:
  ghost      a registry entry points to a file that no longer exists
  orphan     a font file sits in a Fonts folder but nothing registers it
  duplicate  the same font (PostScript name) is installed more than once
  adobe      the same font is also activated through Adobe Fonts -> Adobe apps show conflicts / missing glyphs
  unreadable the file exists but is not a valid font
No GUI code here.
"""

import json
import os
import re
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from .common import ADOBE_LIVETYPE, CONFIG_DIR, FONTS_KEY, SYSTEM_FONTS, USER_FONTS

FONT_EXT = {".ttf", ".otf", ".ttc", ".otc", ".fon", ".fnt"}
ISSUE_ORDER = ["ghost", "adobe", "duplicate", "orphan", "unreadable"]
RECENT_DAYS = 14
SEEN_FILE = CONFIG_DIR / "seen.json"        # font -> when dl_font_fixer first saw it (for "recently added")
ISSUE_LABEL = {"ghost": "GHOST", "adobe": "ADOBE CONFLICT", "duplicate": "DUPLICATE",
               "orphan": "ORPHAN", "unreadable": "BROKEN"}

# Fonts Windows itself needs. The app never deletes these from C:\Windows\Fonts.
PROTECTED = {
    "segoe ui", "segoe ui variable", "segoe ui emoji", "segoe ui symbol", "segoe ui historic", "segoe mdl2 assets",
    "segoe fluent icons", "segoe print", "segoe script", "marlett", "arial", "times new roman", "courier new",
    "tahoma", "microsoft sans serif", "calibri", "cambria", "consolas", "symbol", "wingdings", "webdings",
    "lucida console", "lucida sans unicode", "verdana", "georgia", "trebuchet ms", "ms gothic", "ms ui gothic",
    "simsun", "nsimsun", "malgun gothic", "yu gothic", "yu gothic ui", "microsoft yahei", "microsoft yahei ui",
    "microsoft jhenghei", "microsoft jhenghei ui", "gadugi", "nirmala ui", "ebrima", "leelawadee ui", "javanese text",
    "mongolian baiti", "microsoft himalaya", "microsoft new tai lue", "microsoft phagspa", "microsoft tai le",
    "microsoft yi baiti", "myanmar text", "sylfaen", "mv boli", "small fonts", "ms sans serif", "ms serif",
    "system", "terminal", "fixedsys", "modern", "roman", "script", "courier", "cascadia code", "cascadia mono",
}

_REG_SUFFIX = re.compile(r"\s*\((TrueType|OpenType|VGA res|All res|[^)]*res[^)]*|Type 1)\)\s*$", re.I)
_STYLE_WORDS = ["thin", "hairline", "extralight", "ultralight", "light", "book", "regular", "normal", "medium",
                "semibold", "demibold", "bold", "extrabold", "ultrabold", "heavy", "black", "italic", "oblique",
                "condensed", "variable"]


@dataclass
class Face:
    id: int
    path: str = ""                 # full path ("" for nothing)
    exists: bool = True
    scope: str = "user"            # user | system | adobe | other
    reg: list = field(default_factory=list)   # [(hive 'HKCU'|'HKLM', value name, raw data)]
    family: str = ""
    style: str = ""
    full_name: str = ""
    ps_name: str = ""
    version: str = ""
    size: int = 0
    variable: bool = False
    issues: set = field(default_factory=set)
    note: str = ""
    extra: bool = False            # a duplicate copy that can go (one copy of each duplicate is kept)
    added: float = 0.0             # when this font was installed (first seen), 0 = unknown / long ago

    @property
    def recent(self):
        return self.added > 0 and time.time() - self.added < RECENT_DAYS * 86400

    @property
    def protected(self):
        return self.scope == "system" and norm(self.family) in PROTECTED

    @property
    def purgeable(self):
        return self.scope in ("user", "system", "other") and not self.protected


@dataclass
class Family:
    key: str
    name: str
    faces: list = field(default_factory=list)

    @property
    def issues(self):
        s = set()
        for f in self.faces:
            s |= f.issues
        return s

    @property
    def scopes(self):
        return {f.scope for f in self.faces}

    @property
    def size(self):
        return sum(f.size for f in self.faces if f.scope != "adobe")

    @property
    def local_faces(self):
        return [f for f in self.faces if f.scope != "adobe"]

    @property
    def added(self):
        return max((f.added for f in self.faces), default=0.0)

    @property
    def recent(self):
        return any(f.recent for f in self.faces)

    def severity(self):
        iss = self.issues
        for i, name in enumerate(ISSUE_ORDER):
            if name in iss:
                return i
        return 99


def norm(s):
    return re.sub(r"[\s_\-]+", "", (s or "").lower())


# ---------------------------------------------------------------- reading font names

def read_names(path):
    """(family, style, full, postscript, version, variable) from the font's name table, or None."""
    from fontTools.ttLib import TTFont, TTCollection
    ext = Path(path).suffix.lower()
    if ext in (".fon", ".fnt"):
        return None
    try:
        if ext in (".ttc", ".otc"):
            with TTCollection(path, lazy=True) as col:
                return _names(col.fonts[0])
        with TTFont(path, lazy=True, fontNumber=0) as f:
            return _names(f)
    except Exception:
        # Adobe Fonts files and some downloads have no extension or a wrong one: try as a collection too
        try:
            with TTCollection(path, lazy=True) as col:
                return _names(col.fonts[0])
        except Exception:
            return None


def _names(f):
    name = f["name"]
    g = lambda *ids: next((str(name.getDebugName(i)).strip() for i in ids if name.getDebugName(i)), "")  # noqa: E731
    return (g(16, 1), g(17, 2), g(4), g(6), g(5).replace("Version ", "v").split(";")[0], "fvar" in f)


def guess_from_reg_name(value_name):
    """'Antonio Bold (TrueType)' -> ('Antonio', 'Bold')."""
    base = _REG_SUFFIX.sub("", value_name).split(" & ")[0].strip()
    words = base.split()
    style = []
    while len(words) > 1 and words[-1].lower().replace("-", "") in _STYLE_WORDS:
        style.insert(0, words.pop())
    return " ".join(words), " ".join(style) or "Regular"


# ---------------------------------------------------------------- registry

def read_registry():
    """[(hive, value name, data)] for HKLM and HKCU font keys."""
    out = []
    for hive_name, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE), ("HKCU", winreg.HKEY_CURRENT_USER)):
        try:
            with winreg.OpenKey(hive, FONTS_KEY) as k:
                i = 0
                while True:
                    try:
                        name, data, typ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if isinstance(data, str) and data.strip():
                        out.append((hive_name, name, data.strip()))
        except OSError:
            pass
    return out


def resolve_reg_path(hive, data):
    p = Path(os.path.expandvars(data))
    if p.is_absolute():
        return p
    if hive == "HKCU" and (USER_FONTS / p).exists():
        return USER_FONTS / p
    return SYSTEM_FONTS / p


def scope_of(path):
    p = str(path).lower()
    if p.startswith(str(USER_FONTS).lower()):
        return "user"
    if p.startswith(str(SYSTEM_FONTS).lower()):
        return "system"
    if p.startswith(str(ADOBE_LIVETYPE).lower()):
        return "adobe"
    return "other"


# ---------------------------------------------------------------- the scan

def adobe_files():
    """Font files activated by Adobe Fonts (no extensions, numeric names, under livetype\\r)."""
    out = []
    base = ADOBE_LIVETYPE / "r"
    if base.is_dir():
        for p in base.iterdir():
            if p.is_file() and p.stat().st_size > 1024:
                out.append(p)
    return out


def scan(progress=None, include_adobe=True):
    """Return (families sorted by name, stats dict). progress(done, total, text) is called while reading files."""
    faces = {}          # lower path -> Face
    nid = [0]

    def new_face(path, scope):
        nid[0] += 1
        f = Face(id=nid[0], path=str(path), scope=scope)
        faces[str(path).lower()] = f
        return f

    reg = read_registry()
    for hive, name, data in reg:
        p = resolve_reg_path(hive, data)
        key = str(p).lower()
        f = faces.get(key) or new_face(p, scope_of(p))
        f.reg.append((hive, name, data))

    for folder, scope in ((SYSTEM_FONTS, "system"), (USER_FONTS, "user")):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            entries = []
        for e in entries:
            ext = Path(e.name).suffix.lower()
            if not e.is_file() or ext not in FONT_EXT or e.path.lower() in faces:
                continue
            if scope == "system" and ext in (".fon", ".fnt"):
                continue    # Windows ships dozens of unregistered legacy bitmap fonts: not a problem, just noise
            new_face(e.path, scope)

    for p in (adobe_files() if include_adobe else []):
        new_face(p, "adobe")

    items = list(faces.values())
    total = len(items)
    for i, f in enumerate(items):
        if progress and (i % 8 == 0 or i == total - 1):
            progress(i + 1, total, f.path)
        try:
            st = os.stat(f.path)
            f.exists, f.size = True, st.st_size
        except OSError:
            f.exists = False
        names = read_names(f.path) if f.exists else None
        if names:
            f.family, f.style, f.full_name, f.ps_name, f.version, f.variable = names
        if not f.family:
            if f.reg:
                f.family, f.style = guess_from_reg_name(f.reg[0][1])
            else:
                f.family, f.style = guess_from_reg_name(Path(f.path).stem.replace("-", " ").replace("_", " "))
            if f.exists and Path(f.path).suffix.lower() not in (".fon", ".fnt"):
                f.issues.add("unreadable")
        if not f.full_name:
            f.full_name = f"{f.family} {f.style}".strip()
        if not f.exists:
            f.issues.add("ghost")
        if f.exists and not f.reg and f.scope in ("user", "system"):
            # Windows ships many unregistered legacy bitmap fonts (.fon) and a hidden Marlett: not a problem
            legacy = Path(f.path).suffix.lower() in (".fon", ".fnt")
            if f.scope == "user" or not (legacy or f.protected):
                f.issues.add("orphan")

    # Adobe files that failed to parse are just noise
    items = [f for f in items if not (f.scope == "adobe" and "unreadable" in f.issues)]

    local = [f for f in items if f.scope != "adobe" and f.exists]
    adobe = [f for f in items if f.scope == "adobe"]
    adobe_ps = {f.ps_name.lower() for f in adobe if f.ps_name}
    adobe_fam = {norm(f.family) for f in adobe}

    # same PostScript name installed more than once
    by_ps = {}
    for f in local:
        k = (f.ps_name or f.full_name).lower()
        by_ps.setdefault(k, []).append(f)
    for group in by_ps.values():
        if len({g.path.lower() for g in group}) > 1:
            group.sort(key=lambda g: (not g.reg, g.scope != "system", len(Path(g.path).name), g.path.lower()))
            for i, g in enumerate(group):
                g.issues.add("duplicate")
                g.extra = i > 0
                g.note = f"also at {', '.join(x.path for x in group if x is not g)}"

    # A face conflicts when Adobe Fonts has the exact same font (PostScript name). Other weights of a family
    # Adobe also has are only noted: removing them would lose weights Adobe doesn't provide.
    local_ps = {f.ps_name.lower() for f in local if f.ps_name}
    for f in items:
        if f.scope == "adobe":
            continue
        if f.ps_name and f.ps_name.lower() in adobe_ps:
            f.issues.add("adobe")
        elif not f.ps_name and norm(f.family) in adobe_fam:
            f.issues.add("adobe")
        elif norm(f.family) in adobe_fam:
            f.note = (f.note + "; " if f.note else "") + "Adobe Fonts has other weights of this family"
    for f in adobe:
        if f.ps_name and f.ps_name.lower() in local_ps:
            f.issues.add("adobe")

    _mark_added(items)

    fams = {}
    for f in items:
        k = norm(f.family) or norm(Path(f.path).stem)
        fam = fams.get(k)
        if not fam:
            fam = fams[k] = Family(key=k, name=f.family or Path(f.path).stem)
        fam.faces.append(f)
    for fam in fams.values():
        fam.faces.sort(key=lambda x: (x.scope == "adobe", _weight_rank(x.style), x.style))

    fam_list = sorted(fams.values(), key=lambda x: x.name.lower())
    stats = {
        "families": len(fam_list),
        "faces": len(items),
        "ghost": sum(1 for f in items if "ghost" in f.issues),
        "orphan": sum(1 for f in items if "orphan" in f.issues),
        "duplicate": sum(1 for f in items if "duplicate" in f.issues and f.scope != "adobe"),
        "adobe": sum(1 for fam in fam_list if "adobe" in fam.issues and fam.local_faces),
        "unreadable": sum(1 for f in items if "unreadable" in f.issues),
        "adobe_faces": len(adobe),
        "user": sum(1 for f in items if f.scope == "user"),
        "system": sum(1 for f in items if f.scope == "system"),
        "recent": sum(1 for fam in fam_list if fam.recent),
    }
    return fam_list, stats


def _seen_key(f):
    # Creative Cloud re-writes its Adobe Fonts files under new names when it re-syncs: key them by font name
    return f"adobe:{(f.ps_name or f.full_name).lower()}" if f.scope == "adobe" else f.path.lower()


def _birth(path):
    try:
        st = os.stat(path)
        return getattr(st, "st_birthtime", st.st_ctime)
    except OSError:
        return 0.0


def _mark_added(items):
    """Set Face.added: when the font was installed. dl_font_fixer remembers every font it has seen, so a font
    is new when it wasn't there at the previous scan (Windows Update rewriting Segoe UI or Creative Cloud
    re-syncing doesn't count). On the very first scan the file's creation date is used for fonts you installed."""
    try:
        seen = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        first_run = False
    except Exception:
        seen, first_run = {}, True
    now = time.time()
    out = {}
    for f in items:
        if not f.exists:
            continue
        k = _seen_key(f)
        if k in out:
            f.added = out[k]
            continue
        if k in seen:
            t = seen[k]
        elif f.scope == "adobe":
            t = 0.0 if first_run else now
        elif first_run and f.scope == "system" and not f.reg:
            t = 0.0
        elif first_run and f.scope == "system" and (f.protected or _birth(f.path) and
                                                    abs(_birth(f.path) - _windows_fonts_birth()) < 3600):
            t = 0.0         # shipped with or updated by Windows
        else:
            b = _birth(f.path)
            t = min(b, now) if b else now
        f.added = t
        out[k] = t
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass


_WIN_BIRTH = []


def _windows_fonts_birth():
    """Creation time of Segoe UI: Windows feature updates rewrite all its own fonts at about that time."""
    if not _WIN_BIRTH:
        _WIN_BIRTH.append(_birth(SYSTEM_FONTS / "segoeui.ttf"))
    return _WIN_BIRTH[0]


_WEIGHTS = [("hairline", 0), ("extralight", 2), ("ultralight", 2), ("thin", 1), ("semilight", 3),
            ("light", 3), ("book", 4), ("regular", 5), ("normal", 5), ("medium", 6), ("semibold", 7),
            ("demibold", 7), ("extrabold", 9), ("ultrabold", 9), ("bold", 8), ("heavy", 10), ("black", 11)]


def _weight_rank(style):
    s = (style or "").lower().replace(" ", "").replace("-", "")
    ital = "italic" in s or "oblique" in s
    for w, r in _WEIGHTS:
        if w in s:
            return r * 2 + ital
    return 5 * 2 + ital
