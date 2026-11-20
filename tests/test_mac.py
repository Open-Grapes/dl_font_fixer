"""macOS checks with a throwaway font (run by the Mac build on GitHub Actions; safe on a real Mac too).

Copies one of macOS's own fonts into ~/Library/Fonts under a test name, then: the scanner sees it as new,
delete moves it to the Trash, History says it's recoverable, Restore puts it back, deleting again and
emptying it from the Trash makes History say it can't be recovered. Also: lsof finds who has a file open,
and the window builds (offscreen) in dark and light.
"""

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dlff import actions, scanner, winapi  # noqa: E402
from dlff.common import HISTORY_FILE, IS_MAC, USER_FONTS  # noqa: E402

assert IS_MAC, "run this on a Mac"
log = lambda t, lvl="info": print("    ", lvl, t, flush=True)  # noqa: E731


def face_at(path):
    fams, _ = scanner.scan()
    return next((f for fam in fams for f in fam.faces if f.path == str(path)), None)


def main():
    before = HISTORY_FILE.read_text() if HISTORY_FILE.exists() else None
    src = next(p for p in Path("/System/Library/Fonts").rglob("*.ttf"))
    USER_FONTS.mkdir(parents=True, exist_ok=True)
    dst = USER_FONTS / "DLFF_CI_Test.ttf"
    shutil.copyfile(src, dst)          # contents only: system fonts carry a "restricted" flag
    try:
        fams, stats = scanner.scan()
        print("scan:", stats, flush=True)
        assert stats["faces"] > 50
        assert any(f.scope == "apple" for fam in fams for f in fam.faces), "macOS fonts not found"
        assert stats["ghost"] == 0 and stats["orphan"] == 0
        assert not any(f.purgeable for fam in fams for f in fam.faces if f.scope == "apple")

        f = face_at(dst)
        assert f and f.scope == "user" and f.purgeable, f
        assert f.recent, "a font installed just now should be NEW"
        print("1. found as NEW:", f.family, f.style, flush=True)

        res = actions.purge([f], log=log)
        assert not dst.exists() and res["recycled"], res
        item = actions.history()[0]["items"][0]
        assert item["state"] == "bin" and os.path.exists(item["bin"]), item
        print("2. in the Trash:", item["bin"], flush=True)

        date = actions.history()[0]["date"]
        assert actions.restore_from_bin([(date, str(dst))], log=log) == 1
        assert dst.exists() and actions.history()[0]["items"][0]["state"] == "restored"
        print("3. restored", flush=True)

        time.sleep(1.1)       # history entries are keyed by the second
        actions.purge([face_at(dst)], log=log)
        item = actions.history()[0]["items"][0]
        os.remove(item["bin"])                     # same as emptying the Trash
        assert actions.history()[0]["items"][0]["state"] == "gone"
        print("4. after emptying the Trash: can't recover", flush=True)

        with open(src, "rb"):
            lk = winapi.lockers([str(src)])
        assert any(x["pid"] == os.getpid() for x in lk), lk
        print("5. lsof sees the open file", flush=True)

        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from dlff import gui, theme as T
        app = QApplication([])
        for mode in ("dark", "light"):
            T.use(mode)
            app.setStyleSheet(T.QSS)
            gui.MainWindow._auto_update_check = lambda self: None
            w = gui.MainWindow({"families": fams, "stats": stats, "filter": "all", "scope": "any", "search": "",
                                "selected": [], "console": "", "update": None})
            w.show_everything("adobe")
            w.show_everything("all")
            app.processEvents()
            w.close()
        print("6. window builds in dark and light", flush=True)
    finally:
        dst.unlink(missing_ok=True)
        if before is None:
            HISTORY_FILE.unlink(missing_ok=True)
        else:
            HISTORY_FILE.write_text(before)
    print("MAC TESTS PASSED", flush=True)


if __name__ == "__main__":
    main()
