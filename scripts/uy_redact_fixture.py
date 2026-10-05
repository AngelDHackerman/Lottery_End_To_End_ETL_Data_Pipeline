"""Copy a raw loteria.gub.uy page into tests/fixtures/uy/, neutralising privacy links.

    python scripts/uy_redact_fixture.py <raw.html> tests/fixtures/uy/<name>.html

Results pages from mid-2016 on link the DNLQ's ``*_DET_INVALIDAS_*`` PDFs, which carry
national ID numbers. The page holds only the link, never the data, but the fixture scanner
(tests/unit/uy/test_uy_privacy.py) refuses any fixture that so much as names the pattern —
a rule simple enough to stay true. So each such href is replaced, and nothing else changes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HREF = re.compile(r"""href\s*=\s*(["'])([^"']*?det_invalidas[^"']*)\1""", re.IGNORECASE)
PLACEHOLDER = "#privacy-link-removed"


def redact(html: str) -> tuple[str, int]:
    return _HREF.subn(lambda m: f"href={m.group(1)}{PLACEHOLDER}{m.group(1)}", html)


def main(argv: list[str]) -> int:
    src, dst = Path(argv[0]), Path(argv[1])
    html, count = redact(src.read_bytes().decode("utf-8"))
    if "DET_INVALIDAS" in html.upper():
        raise SystemExit("pattern still present outside an href — inspect by hand")
    dst.write_bytes(html.encode("utf-8"))
    print(f"{dst}: {count} link(s) neutralised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
