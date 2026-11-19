"""Entry point.

  dl_font_fixer.exe                       open the window (asks Windows for administrator rights first)
  dl_font_fixer.exe --no-elevate          open the window without asking for administrator rights
  dl_font_fixer.exe --scan-report FILE    scan and write a JSON report (no changes), for build tests
"""

import json
import sys
from pathlib import Path


def scan_report(out_file):
    from . import scanner
    try:
        fams, stats = scanner.scan()
        issues = [{"family": f.name, "issues": sorted(f.issues),
                   "faces": [{"style": x.style, "scope": x.scope, "path": x.path, "issues": sorted(x.issues),
                              "registry": x.reg} for x in f.faces if x.issues]}
                  for f in fams if f.issues]
        res = {"stats": stats, "families_with_issues": issues}
    except Exception as e:
        import traceback
        res = {"error": str(e), "trace": traceback.format_exc()}
    Path(out_file).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0 if "error" not in res else 1


def main():
    args = sys.argv[1:]
    if args[:1] == ["--scan-report"] and len(args) > 1:
        return scan_report(args[1])
    # The app always runs as administrator: fonts for all users, the font cache and the reboot queue need it.
    # If the Windows prompt is declined it still opens, limited to fonts installed for the current user.
    from . import winapi
    if "--no-elevate" not in args and not winapi.is_admin():
        if winapi.relaunch_as_admin(["--no-elevate"]):
            return 0
    from .gui import main as gui_main
    return gui_main(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
