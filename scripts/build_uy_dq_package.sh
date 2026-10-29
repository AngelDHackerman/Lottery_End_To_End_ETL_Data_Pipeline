#!/usr/bin/env bash
# UY-026.2 (D20, P14): the UY DQ job's dependencies as ONE zip of wheels for AWS Glue 5.0.
#
#   dist/uy/uy_dq.gluewheels.zip
#     wheels/*.whl              requirements/uy-dq.lock (what Glue 5.0 lacks) + sorteos itself
#     wheels/requirements.txt   every one of them, pinned, for pip to install from the zip
#
# Glue installs it with
#   --additional-python-modules s3://.../uy_dq.gluewheels.zip
#   --python-modules-installer-option --no-index
# so pip resolves from the zip alone and never reaches PyPI. What Glue already has (pandas,
# numpy, pyarrow...) is not in the zip and is never reinstalled (owner, UY-026 2a). The job and
# the upload are Fase 5; nothing here touches AWS.
#
# Byte-identical on every run: pip downloads the exact files the lock hashes, the sorteos wheel
# is written with fixed timestamps (scripts/uy_build_wheel.py), and _zipdir.py sorts entries
# and fixes timestamps and modes. CI checks it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/uy-dq"
WHEELS="${BUILD_DIR}/wheels"
OUT_ZIP="${REPO_ROOT}/dist/uy/uy_dq.gluewheels.zip"
LOCK="requirements/uy-dq.lock"

if [[ ! -f "$LOCK" ]]; then
  echo "❌  $LOCK is missing. Generate it with: make uy-dq-lock" >&2
  exit 1
fi

echo "🔄  Rebuilding the UY DQ zip of wheels..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$WHEELS" "$(dirname "$OUT_ZIP")"

# Same target as scripts/uy_dq_lock.py: Python 3.11 on the manylinux tags Glue 5.0 accepts.
python3 -m pip download \
  --requirement "$LOCK" \
  --require-hashes \
  --no-deps \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --platform manylinux_2_28_x86_64 \
  --platform manylinux_2_34_x86_64 \
  --python-version 3.11 \
  --implementation cp \
  --dest "$WHEELS" \
  --disable-pip-version-check \
  --quiet

wheel="$(python3 scripts/uy_build_wheel.py "$WHEELS")"
version="$(basename "$wheel" | cut -d- -f2)"

# The lock's pins without hashes, plus sorteos: the whole zip, pinned.
{
  grep -E '^[a-z0-9][a-z0-9._-]*==' "$LOCK" | sed 's/ \\$//'
  echo "sorteos==${version}"
} > "${WHEELS}/requirements.txt"

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  $OUT_ZIP"
echo "    $(ls "$WHEELS"/*.whl | wc -l) wheels from $LOCK + sorteos ${version}"
du -h "$OUT_ZIP" | awk '{print "    size:  " $1}'
