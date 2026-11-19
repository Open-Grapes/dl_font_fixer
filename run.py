"""Entry point for running from source and for PyInstaller."""
import sys

if __name__ == "__main__":
    from dlff.__main__ import main
    sys.exit(main())
