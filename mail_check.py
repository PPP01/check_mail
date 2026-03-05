#!/usr/bin/env python3
import sys
from pathlib import Path

from mail_check_app.main import main


if __name__ == "__main__":
    sys.exit(main(script_path=Path(__file__).resolve()))
