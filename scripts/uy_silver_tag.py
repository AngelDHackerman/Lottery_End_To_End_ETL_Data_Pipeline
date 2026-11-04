"""Print the tag of the UY silver image: a hash of everything that goes into it (UY-042.4.1).

    python scripts/uy_silver_tag.py        # s-<16 hex>

`docker build` does not give the same digest twice, so the tag cannot come from the image.
It comes from the inputs instead: the Dockerfile, the script that builds its context, the
lock and every file the image copies. Same inputs, same tag, so `make uy-silver-push` finds
it already in ECR and pushes nothing, and Terraform sees no change. The repo's tags are
IMMUTABLE (ecr.tf): a tag always names the image that was built from these exact bytes.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    "docker/uy-silver/Dockerfile",
    "scripts/build_uy_silver_context.sh",
    "requirements/uy-silver.lock",
    "src/loteria/__init__.py",
    "src/loteria/common/__init__.py",
    "src/loteria/common/logging_setup.py",
)
TREES = ("src/sorteos",)


def inputs(root: Path = ROOT) -> list[Path]:
    paths = [root / f for f in FILES]
    for tree in TREES:
        paths += [
            p
            for p in (root / tree).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ]
    return sorted(paths)


def tag(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for path in inputs(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "s-" + digest.hexdigest()[:16]


if __name__ == "__main__":
    print(tag())
    sys.exit(0)
