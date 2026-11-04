"""Local bronze store and the manifest that says what has been fetched.

Two stores, deliberately separate (roadmap-uruguay.md, C3):

- **Bronze** holds raw bytes exactly as served, and only for real draws. Keys mirror the
  future S3 layout (``bronze/country=<cc>/source=<source>/year=<yyyy>/<source>_<date>.<ext>``),
  so moving to the cloud changes the backend and not the paths. The site regenerates its
  pages from a database with today's template (old extracts cite a 2019 decree), so the
  bytes are "the page as served on ``fetched_at``", never the original document.
- **The manifest** (``manifest.py``) is the cache. A ``no_draw`` day leaves nothing in
  bronze but has a manifest row, and that row is what stops it being requested again.

``S3BronzeStore`` is the same store in the cloud (UY-042.3): the same keys, written under a
prefix of the data bucket with the leading ``bronze/`` dropped (P15), so the manifest's
``bronze_key`` names the file on disk and the object in S3 alike.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path


class BronzeStore:
    def __init__(self, root: Path, country: str) -> None:
        # The country is a path segment, so it is checked rather than trusted: an ISO 3166-1
        # alpha-2 code in lower case (DESIGN.md, D1), the form the existing keys already use.
        if not re.fullmatch(r"[a-z]{2}", country):
            raise ValueError(
                f"country must be an ISO 3166-1 alpha-2 code in lower case: {country!r}"
            )
        self.root = Path(root)
        self.country = country

    def key(self, source: str, day: date, extension: str) -> str:
        return (
            f"bronze/country={self.country}/source={source}/year={day.year}/"
            f"{source}_{day.isoformat()}.{extension}"
        )

    def write(self, key: str, content: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)  # never leave a half-written page under the real name

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


BRONZE_ROOT = "bronze/"


class S3BronzeStore:
    """``BronzeStore`` on S3: ``bronze/<rest>`` is stored at ``<prefix><rest>`` (P15)."""

    def __init__(self, bucket: str, prefix: str, country: str, client=None) -> None:
        if not prefix.endswith("/"):
            raise ValueError(f"prefix must end with '/': {prefix!r}")
        self._keys = BronzeStore(Path("."), country)  # the one place keys are built
        self.bucket = bucket
        self.prefix = prefix
        self.country = country
        if client is None:  # pragma: no cover - the tests pass a moto client
            import boto3

            client = boto3.client("s3")
        self._client = client

    def key(self, source: str, day: date, extension: str) -> str:
        return self._keys.key(source, day, extension)

    def object_key(self, key: str) -> str:
        if not key.startswith(BRONZE_ROOT):
            raise ValueError(f"not a bronze key: {key!r}")
        return self.prefix + key[len(BRONZE_ROOT) :]

    def write(self, key: str, content: bytes) -> None:
        # One PUT is atomic in S3: a reader sees the old object or the new one, never half,
        # which is what the .tmp + rename of the local store exists to get.
        self._client.put_object(Bucket=self.bucket, Key=self.object_key(key), Body=content)

    def read(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=self.object_key(key))["Body"].read()
