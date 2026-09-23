#!/usr/bin/env bash
# Builds the extractor Lambda's dependency layer (PR-019, pinned by PR-046).
#
# Zip layout: python/lib/python3.12/site-packages/<deps>. That path is not cosmetic —
# Lambda mounts a layer at /opt, and only /opt/python and /opt/python/lib/python3.12/
# site-packages are on the runtime's sys.path. Get the nesting wrong and the layer
# mounts fine but every import fails.
#
# Pairs with build_lambda_function.sh, which ships the code-only zip. Deps live here so
# a code change no longer re-uploads beautifulsoup4 on every apply; the layer only
# republishes when the lock below changes.
#
# ⚠️ PR-046: installs from requirements/extractor.lock, NOT extractor.txt.
# `extractor.txt` pins two direct dependencies and lets the six transitive ones float, so
# every `make build` resolved them against whatever PyPI had that morning. Because
# `make build` must run before any `plan` (filemd5/filebase64sha256 read the zips at plan
# time — PR-019), a floating transitive marks the layer FOR REPLACEMENT in an unrelated
# PR's plan. That happened on 2026-09-20: idna 3.20 quietly replaced 3.19 and PR-042.1's
# plan arrived as `1 add, 13 change, 1 destroy` instead of `0 add, 12 change, 0 destroy`.
# The lock is fully pinned with hashes, so the layer hash now moves only when somebody
# deliberately runs `make lock`.
#
# The output lands where Terraform expects it (root var `lambda_layer_zip_path`, which
# defaults to `lambda_layer.zip` relative to terraform/).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/layer"
SITE_PACKAGES="${BUILD_DIR}/python/lib/python3.12/site-packages"
OUT_ZIP="${REPO_ROOT}/terraform/lambda_layer.zip"
LOCK="requirements/extractor.lock"

if [[ ! -f "$LOCK" ]]; then
  echo "❌  $LOCK is missing. Generate it with: make lock" >&2
  exit 1
fi

echo "🔄  Rebuilding Lambda dependency layer..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$SITE_PACKAGES"

# Every flag here exists to make the output independent of the machine that built it:
#   --require-hashes   every wheel must match a hash in the lock. A compromised or
#                      re-uploaded artifact fails the build instead of shipping.
#   --no-deps          the lock is complete, so pip must not resolve anything itself.
#                      (Also what lets --platform be used at all.)
#   --only-binary      never build an sdist locally — a locally compiled extension would
#                      carry this machine's toolchain into a zip destined for Lambda.
#   --platform/--python-version/--implementation
#                      resolve for the Lambda runtime (python3.12, x86_64 — see
#                      terraform/modules/etl-lambda/main.tf), not for this shell. Only
#                      charset_normalizer ships a compiled wheel today, but "today" is
#                      exactly the assumption this PR exists to stop relying on.
pip install \
  --requirement "$LOCK" \
  --require-hashes \
  --no-deps \
  --only-binary=:all: \
  --platform manylinux_2_17_x86_64 \
  --python-version 3.12 \
  --implementation cp \
  --target "$SITE_PACKAGES" \
  --quiet

# Drop caches and dist-info RECORD noise so the zip hash only changes when the pinned
# dependencies do.
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  lambda_layer.zip ready -> $OUT_ZIP"
echo "    layout: python/lib/python3.12/site-packages/"
echo "    locked: $LOCK"
du -h "$OUT_ZIP" | awk '{print "    size:  " $1}'
