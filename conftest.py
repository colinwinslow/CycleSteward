"""Pytest bootstrap: make the ``src`` layout importable without an install.

In a normal environment the package is installed with ``pip install -e .[dev]``
and this file is a harmless no-op. It exists so the test suite can also run from
a bare checkout (e.g. where the interpreter predates the project's required
Python and the editable install is skipped).
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
