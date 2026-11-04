#!/usr/bin/env bash
# Builds the UY fetch Lambda's zip (UY-042.3; DESIGN.md D29): the `sorteos` package and its
# dependencies in ONE archive, both at the zip root, so the handler resolves as
# `sorteos.uy.lambda_fetch.handler`. The deps weigh ~1.5 MB, so a layer would only add a
# second artifact to keep in step.
#
# Output: dist/uy/uy_fetch.zip, which terraform/uy reads (var.fetch_zip_path) at plan time.
# The zip must be byte-identical for the same lock and code, or every plan redeploys the
# function (memory of PR-046/046.2). So, as in build_lambda_layer.sh:
#   --require-hashes --no-deps --only-binary   install exactly the lock, nothing compiled here
#   --platform/--python-version/--implementation   for the Lambda runtime (python3.12,
#                                                 x86_64), not for this shell; pyyaml and
#                                                 charset_normalizer ship compiled wheels
#   no bin/ and no __pycache__                    console-script shebangs name the pip that
#                                                 ran (PR-046.3); caches name nothing useful
#   scripts/_zipdir.py                            fixed timestamps, sorted entries, 0644/0755
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/uy-fetch"
OUT_ZIP="${REPO_ROOT}/dist/uy/uy_fetch.zip"
LOCK="requirements/uy-fetch.lock"

if [[ ! -f "$LOCK" ]]; then
  echo "❌  $LOCK is missing. Generate it with: make uy-fetch-lock" >&2
  exit 1
fi

echo "🔄  Building the UY fetch Lambda zip..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$BUILD_DIR" "$(dirname "$OUT_ZIP")"

pip install \
  --requirement "$LOCK" \
  --require-hashes \
  --no-deps \
  --only-binary=:all: \
  --platform manylinux_2_17_x86_64 \
  --python-version 3.12 \
  --implementation cp \
  --target "$BUILD_DIR" \
  --disable-pip-version-check \
  --quiet

rm -rf "${BUILD_DIR}/bin"
find "$BUILD_DIR" -path '*.dist-info/RECORD' -exec sed -i '\#^\.\./\.\./bin/#d' {} +

cp -r src/sorteos "$BUILD_DIR/sorteos"
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  uy_fetch.zip ready -> $OUT_ZIP"
echo "    handler: sorteos.uy.lambda_fetch.handler"
echo "    locked:  $LOCK"
du -h "$OUT_ZIP" | awk '{print "    size:    " $1}'
