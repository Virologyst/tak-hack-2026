"""Make `import taklib` work when running an example directly.

Python puts the *script's* directory on sys.path, not the repo root, so
`python examples/01_send_marker.py` can't see `taklib/` without help. Each
example does `import _path  # noqa` first and this fixes it.

If you'd rather do it properly: `pip install -e .` from the repo root, after
which this shim is a harmless no-op.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
