"""Copy a raw loteria.gub.uy page into tests/fixtures/uy/, neutralising privacy links and coupons.

    python scripts/uy_redact_fixture.py <raw.html> tests/fixtures/uy/<name>.html

Results pages from mid-2016 on link the DNLQ's ``*_DET_INVALIDAS_*`` PDFs, which carry
national ID numbers. The page holds only the link, never the data, but the fixture scanner
(tests/unit/uy/test_uy_privacy.py) refuses any fixture that so much as names the pattern —
a rule simple enough to stay true. So each such href is replaced.

Winning coupon numbers stay in bronze only (owner decision C7, roadmap-uruguay.md), so each
one is replaced by a fake of the same shape: a per-page counter, zero-padded to the length of
the first group, with every check digit set to 0 (``123456789-1`` -> ``000000001-0``). The
parser still counts the same coupons (D7, docs/uruguay/DESIGN.md), and a fake is obvious at a
glance because it starts with ``FAKE_PREFIX``. Nothing else changes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HREF = re.compile(r"""href\s*=\s*(["'])([^"']*?det_invalidas[^"']*)\1""", re.IGNORECASE)
PLACEHOLDER = "#privacy-link-removed"

# Every shape seen in local bronze (2006–2026, both sources): 8 to 11 digits with one or two
# dashed check digits, and since 2018 ten bare digits. The bare form is only ever the whole
# text of a cell, so it is matched only between a tag or whitespace and the next tag — that
# keeps amounts, dates and draw numbers out of reach.
COUPON_PATTERNS = (
    re.compile(r"(?<![\d-])\d{8,11}(?:-\d){1,2}(?![\d-])"),
    re.compile(r"(?<=[\s>])\d{10}(?=\s*<)"),
)
FAKE_PREFIX = "000000"


def redact(html: str) -> tuple[str, int]:
    return _HREF.subn(lambda m: f"href={m.group(1)}{PLACEHOLDER}{m.group(1)}", html)


def redact_coupons(html: str) -> tuple[str, int]:
    count = 0

    def fake(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        first, *checks = match.group().split("-")
        return "-".join([str(count).zfill(len(first)), *("0" * len(c) for c in checks)])

    for pattern in COUPON_PATTERNS:
        html = pattern.sub(fake, html)
    return html, count


def main(argv: list[str]) -> int:
    src, dst = Path(argv[0]), Path(argv[1])
    html, links = redact(src.read_bytes().decode("utf-8"))
    if "DET_INVALIDAS" in html.upper():
        raise SystemExit("pattern still present outside an href — inspect by hand")
    html, coupons = redact_coupons(html)
    dst.write_bytes(html.encode("utf-8"))
    print(f"{dst}: {links} link(s) neutralised, {coupons} coupon(s) replaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
