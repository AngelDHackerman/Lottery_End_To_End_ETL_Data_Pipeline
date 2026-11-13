"""Is local UY bronze in S3, byte for byte? (UY-042.1). Read-only on both sides.

    python -m sorteos.uy.bronze_sync --root data/uy/bronze --bucket lottery-partitioned-storage-prod

``make uy-bronze-sync`` uploads with ``aws s3 sync`` and then runs this. Run alone
(``make uy-bronze-check``), it is also the dry run: before the upload it says how many files
S3 is missing.

**The key.** An object is ``uy/raw/`` plus the file's path under the local bronze root (P15),
so the manifest's ``bronze_key`` without its leading ``bronze/`` names the same file on disk
and in S3, and nothing is renamed on the way.

**The comparison.** Each local file against its object, by size and MD5. The data bucket
encrypts with SSE-S3, and under SSE-S3 a single-part upload has its MD5 as ETag. ``aws s3
sync`` uploads in one part below 8 MB, and the largest bronze file measures 4.7 MB
(2026-11-04). An ETag with a ``-`` is a multipart upload, which is not an MD5: only its size is
compared, and those are counted apart so the report says how many were not checked by content.

``*.tmp`` is skipped on both sides: ``BronzeStore.write`` writes there first and renames, so a
``.tmp`` is a write that did not finish, never bronze. The sync excludes it too.

The exit code is 1 when a local file is missing in S3 or differs from its object. Objects in
S3 without a local file are listed but do not fail: from UY-043 on the fetch Lambda writes
there, and the disk stops being the whole of bronze.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PREFIX = "uy/raw/"
SKIPPED_SUFFIX = ".tmp"
SHOW = 20  # how many keys of each kind the report lists


@dataclass(frozen=True)
class Entry:
    size: int
    md5: str | None  # None for a multipart object: its ETag is not an MD5


@dataclass
class Comparison:
    matched: int = 0
    size_only: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    different: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.different


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_inventory(root: Path) -> dict[str, Entry]:
    """Every bronze file under ``root``, keyed by its path relative to it."""
    return {
        path.relative_to(root).as_posix(): Entry(path.stat().st_size, _md5(path))
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(SKIPPED_SUFFIX)
    }


def s3_inventory(client, bucket: str, prefix: str) -> dict[str, Entry]:
    """Every object under ``prefix``, keyed by its key without the prefix."""
    found: dict[str, Entry] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"][len(prefix) :]
            if not key or key.endswith("/") or key.endswith(SKIPPED_SUFFIX):
                continue
            etag = obj["ETag"].strip('"')
            found[key] = Entry(obj["Size"], None if "-" in etag else etag)
    return found


def compare(local: dict[str, Entry], remote: dict[str, Entry]) -> Comparison:
    result = Comparison()
    for key, mine in local.items():
        theirs = remote.get(key)
        if theirs is None:
            result.missing.append(key)
        elif theirs.size != mine.size:
            result.different.append(key)
        elif theirs.md5 is None:
            result.size_only.append(key)
            result.matched += 1
        elif theirs.md5 != mine.md5:
            result.different.append(key)
        else:
            result.matched += 1
    result.extra = sorted(set(remote) - set(local))
    return result


def render(result: Comparison, local_count: int, remote_count: int, where: str) -> str:
    lines = [
        f"local files:      {local_count:>7,}",
        f"objects in S3:    {remote_count:>7,}  ({where})",
        f"matched:          {result.matched:>7,}"
        + (f"  ({len(result.size_only):,} multipart, by size only)" if result.size_only else ""),
        f"missing in S3:    {len(result.missing):>7,}",
        f"different in S3:  {len(result.different):>7,}",
        f"only in S3:       {len(result.extra):>7,}  (reported, not a failure)",
    ]
    for title, keys in (
        ("missing", result.missing),
        ("different", result.different),
        ("only in S3", result.extra),
    ):
        if keys:
            lines.append(f"\n{title} (first {min(len(keys), SHOW)}):")
            lines.extend(f"  {key}" for key in keys[:SHOW])
    lines.append("\nOK: every local bronze file is in S3, unchanged." if result.ok else "\nFAIL")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.bronze_sync",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, required=True, help="local bronze root (data/uy/bronze)")
    p.add_argument("--bucket", required=True, help="the data bucket")
    p.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"default {DEFAULT_PREFIX}")
    return p


def main(argv: list[str] | None = None, client=None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.root / "country=uy").is_dir():
        print(f"{args.root} has no country=uy/: is it the bronze root?", file=sys.stderr)
        return 2
    if client is None:  # pragma: no cover - the tests pass a moto client
        import boto3

        client = boto3.client("s3")
    local = local_inventory(args.root)
    remote = s3_inventory(client, args.bucket, args.prefix)
    result = compare(local, remote)
    print(render(result, len(local), len(remote), f"s3://{args.bucket}/{args.prefix}"))
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
