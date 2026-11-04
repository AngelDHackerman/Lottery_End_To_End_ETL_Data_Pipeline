#!/usr/bin/env bash
# Builds the Docker build context of the UY silver image (UY-042.4.1): a directory with
# exactly what docker/uy-silver/Dockerfile copies, laid out as in the repo. Nothing else can
# reach the image: no secret, state file or data, whatever is lying around the working tree.
#
# Why not a .dockerignore allowlist: the first version used Dockerfile.dockerignore with `*`
# and a few `!` lines. Docker 29 built it; the BuildKit on GitHub's runners applied the `*` to
# the Dockerfile itself and failed with "open Dockerfile: no such file or directory". A context
# made by copying does not depend on how a Docker version reads ignore files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONTEXT="build/uy-silver-context"

rm -rf "$CONTEXT"
mkdir -p "$CONTEXT/requirements" "$CONTEXT/src/loteria/common"

cp requirements/uy-silver.lock "$CONTEXT/requirements/"
cp -r src/sorteos "$CONTEXT/src/sorteos"
cp src/loteria/__init__.py "$CONTEXT/src/loteria/"
cp src/loteria/common/__init__.py src/loteria/common/logging_setup.py "$CONTEXT/src/loteria/common/"
find "$CONTEXT" \( -name '__pycache__' -o -name '*.pyc' \) -prune -exec rm -rf {} +

echo "$CONTEXT"
