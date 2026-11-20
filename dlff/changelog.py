"""What changed in each version, newest first. Shown by Check for updates → Version history.
Add a section here with every new version."""

HISTORY = """
## 1.3  (20 Nov 2026)
- New **Mac version** (Apple Silicon and Intel, macOS 13+): scans ~/Library/Fonts, /Library/Fonts, macOS's own fonts and Adobe Fonts; Adobe conflicts, duplicates, broken files and recently added; deletes go to the Trash and HISTORY can put them back; rebuild font cache and restart Creative Cloud
- **Light mode**: THEME in the top bar switches between Dark, Light and Match Windows straight away; your choice is remembered
- New **Version history** in Check for updates: what changed in every version

## 1.2  (20 Nov 2026)
- **Recycle Bin + History**: deleted fonts go to the Recycle Bin. HISTORY lists every font you deleted as *in Recycle Bin (recoverable)*, *deleted (can't recover)* once the bin is emptied, or *restored*
- **Restore** from History puts a font back where it was, registry entry included
- **Recently added**: NEW badge, a NEW · 14 DAYS counter and a RECENTLY ADDED filter. Windows Update and Creative Cloud re-syncs don't count
- **Check for updates** in the top bar and the sidebar, also checked once a day; UPDATE NOW installs the new version in place
- Backups / Restore removed: file copies are no longer kept

## 1.1  (19 Nov 2026)
- Runs as administrator: Windows asks once at start (click Yes). The ADMIN button is gone
- **Right-click a font family** (or press Delete) to remove it from Windows completely, with a warning first
- **Adobe Fonts**: fonts that only come from Creative Cloud can't be deleted here, so delete and folder are greyed out with an explanation. For a font installed by hand *and* in Adobe Fonts, only your installed copy is deleted
- Clicking a counter (Ghosts, Duplicates, Orphans …) always shows those fonts; an empty list explains why and offers to clear the filters
- Simpler inspector: LOCKS, ALL / NONE and the auto-unlock checkbox removed (unlocking is automatic)
- Creative Cloud and Explorer are restarted with your normal rights, never as administrator

## 1.0  (19 Nov 2026)
- First release: scans both Fonts folders and the font registry, grouped by family
- Finds ghost registry entries, orphan files, duplicate installs and Adobe Fonts conflicts
- Shows which program is locking a font file, and purges fonts even when Windows says they're in use
- Rebuild font cache, restart Adobe Creative Cloud, restart Explorer, reboot queue
"""
