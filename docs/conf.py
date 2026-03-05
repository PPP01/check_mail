from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

project = "check_emails"
author = "check_emails contributors"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"

# Keep API pages compact and predictable.
autodoc_member_order = "bysource"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# Ensure docs build is deterministic across environments.
os.environ.setdefault("PYTHONUTF8", "1")
