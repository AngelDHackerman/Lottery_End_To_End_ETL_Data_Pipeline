"""UY-026.2: build ``src/sorteos`` as a pure-Python wheel, byte for byte the same every time.

The DQ job cannot import ``sorteos`` from a zip on ``--extra-py-files``: ``core/config.py``
opens its YAML and CSV files with ``open()``, which cannot read inside a zip. As a wheel
inside the .gluewheels.zip, pip installs it onto disk with GX, in one artifact.

Written by hand rather than with a build backend: the repo builds no package
(``[tool.uv] package = false``), and a wheel is a zip with three metadata files. Fixed
timestamps, sorted entries and normalised modes, so an unchanged tree gives the same bytes.
No ``Requires-Dist``: the dependencies come from requirements/uy-dq.lock, and listing the
parsers' (beautifulsoup4, pdfplumber) would make pip demand what the job never imports.

    python scripts/uy_build_wheel.py build/uy-dq/wheels
"""

from __future__ import annotations

import base64
import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "src" / "sorteos"
NAME = "sorteos"
VERSION = "0.1.0"
TAG = "py3-none-any"
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def files(source: Path = SOURCE) -> list[tuple[str, bytes]]:
    """(path inside the wheel, content) of every file of the package, sorted."""
    out = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            out.append((f"{NAME}/{path.relative_to(source).as_posix()}", path.read_bytes()))
    return out


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def build(out_dir: Path, source: Path = SOURCE) -> Path:
    info = f"{NAME}-{VERSION}.dist-info"
    entries = files(source)
    metadata = f"Metadata-Version: 2.1\nName: {NAME}\nVersion: {VERSION}\n"
    tags = f"Wheel-Version: 1.0\nGenerator: uy_build_wheel\nRoot-Is-Purelib: true\nTag: {TAG}\n"
    entries.append((f"{info}/METADATA", metadata.encode()))
    entries.append((f"{info}/WHEEL", tags.encode()))
    record = "\n".join([*(_record_line(p, d) for p, d in entries), f"{info}/RECORD,,"]) + "\n"
    entries.append((f"{info}/RECORD", record.encode()))

    out_dir.mkdir(parents=True, exist_ok=True)
    wheel = out_dir / f"{NAME}-{VERSION}-{TAG}.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries:
            entry = zipfile.ZipInfo(path, date_time=FIXED_DATE_TIME)
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(entry, data)
    return wheel


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
