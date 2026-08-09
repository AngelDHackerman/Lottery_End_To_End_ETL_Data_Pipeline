"""Scrub vendor identities out of a raw sorteo .txt so it can be committed as a fixture.

The raw files in ``s3://<partitioned>/raw/`` name the person who sold each winning ticket:

    VENDIDO POR JUAN TOMAS TIQUIRAM, DE SAN LUCAS SACATEPÉQUEZ, SACATEPÉQUEZ

The S3 bucket is private and stays that way. ``tests/fixtures/`` does not — it is committed
to a public GitHub repo — so the fixtures get scrubbed on the way in. This script is the
scrubber, kept in the repo rather than run ad hoc so the transformation is auditable and the
fixtures can be regenerated from a fresh capture.

**Only the name segment is replaced.** ``vendido_por`` is comma-delimited and
``parser.split_vendido_por_column`` splits on commas, so replacing the whole field with a
bare ``VENDOR_001`` would erase ciudad and departamento — and with them the ability to test
that function at all, including its ciudad-only branch. Ciudad and departamento are public
geography, not personal data, so they are kept verbatim:

    VENDIDO POR VENDOR_001, DE SAN LUCAS SACATEPÉQUEZ, SACATEPÉQUEZ

Two properties worth preserving, both load-bearing for the tests:

* **The name→id map is stable across files.** One person is ``VENDOR_007`` in every fixture,
  so a future test can still group by vendor.
* **``NO VENDIDO`` lines are left alone.** They are a parser branch, not a person.

Note the name segment sometimes carries more than a name — observed in real data:
``PERSONA CON DISCAPACIDAD VISUAL <nombre>``. Replacing the whole segment (rather than
attempting to match name-shaped substrings) is what makes that disappear too.

Usage::

    # Anonymize every fixture in ONE run — the shared name map is what makes the ids
    # consistent across files, so do not invoke this once per file.
    python scripts/anonymize_fixture.py --out-dir tests/fixtures/sorteos raw/*.txt

    # Guard: fail if any committed fixture still holds a real name.
    python scripts/anonymize_fixture.py --check tests/fixtures/sorteos/*.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# "VENDIDO POR <name>," — the name runs to the FIRST comma, which is where ciudad starts.
# Anchored to the literal marker the parser itself looks for (parser.process_body).
_VENDIDO_RE = re.compile(r"(VENDIDO POR\s+)([^,]+)(,?)")

_PLACEHOLDER_RE = re.compile(r"^VENDOR_\d{3}$")


def anonymize_lines(lines: list[str], name_map: dict[str, str]) -> list[str]:
    """Replace each vendor name with a stable ``VENDOR_NNN``, mutating ``name_map`` in place.

    Passing the same ``name_map`` across several files is what keeps one person mapped to one
    id repo-wide.
    """
    out = []

    for line in lines:
        # "NO VENDIDO" contains no "VENDIDO POR", so it never matches — but be explicit,
        # because the two markers are one word apart and a future regex edit could blur them.
        if "NO VENDIDO" in line:
            out.append(line)
            continue

        def _sub(m: re.Match) -> str:
            name = m.group(2).strip()
            if name not in name_map:
                name_map[name] = f"VENDOR_{len(name_map) + 1:03d}"
            return f"{m.group(1)}{name_map[name]}{m.group(3)}"

        out.append(_VENDIDO_RE.sub(_sub, line))

    return out


def check_file(path: Path) -> list[str]:
    """Return a list of leak descriptions; empty means the file is clean.

    This is the guard that matters: it is what stops a hand-edited or newly captured fixture
    from reaching a public repo with a real name in it.
    """
    problems = []

    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "NO VENDIDO" in line:
            continue
        for m in _VENDIDO_RE.finditer(line):
            name = m.group(2).strip()
            if not _PLACEHOLDER_RE.match(name):
                problems.append(f"{path}:{i}: un-anonymized vendor name: {name!r}")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--out-dir", type=Path, help="Directory to write anonymized copies into.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify the given files contain no real vendor names. Exits non-zero if any do.",
    )
    args = ap.parse_args(argv)

    if args.check:
        problems = [p for path in args.paths for p in check_file(path)]
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{'FAIL' if problems else 'OK'}: checked {len(args.paths)} file(s)")
        return 1 if problems else 0

    if args.out_dir is None:
        ap.error("--out-dir is required when anonymizing")

    # ONE map for the whole run. Anonymizing files in separate invocations would restart the
    # numbering and map the same person to different ids per file.
    name_map: dict[str, str] = {}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for src in sorted(args.paths):
        before = len(name_map)
        lines = src.read_text(encoding="utf-8").splitlines()
        dest = args.out_dir / src.name
        dest.write_text("\n".join(anonymize_lines(lines, name_map)) + "\n", encoding="utf-8")
        print(f"{src} -> {dest}  (+{len(name_map) - before} new names)")

    print(f"{len(name_map)} distinct vendor names replaced across {len(args.paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
