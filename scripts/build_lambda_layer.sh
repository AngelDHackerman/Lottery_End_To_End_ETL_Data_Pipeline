#!/usr/bin/env bash
# Builds the extractor Lambda's dependency layer (PR-019).
#
# Zip layout: python/lib/python3.12/site-packages/<deps>. That path is not cosmetic —
# Lambda mounts a layer at /opt, and only /opt/python and /opt/python/lib/python3.12/
# site-packages are on the runtime's sys.path. Get the nesting wrong and the layer
# mounts fine but every import fails.
#
# Pairs with build_lambda_function.sh, which ships the code-only zip. Deps live here so
# a code change no longer re-uploads beautifulsoup4 on every apply; the layer only
# republishes when requirements/extractor.txt changes.
#
# The output lands where Terraform expects it (root var `lambda_layer_zip_path`, which
# defaults to `lambda_layer.zip` relative to terraform/).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/layer"
SITE_PACKAGES="${BUILD_DIR}/python/lib/python3.12/site-packages"
OUT_ZIP="${REPO_ROOT}/terraform/lambda_layer.zip"

echo "🔄  Rebuilding Lambda dependency layer..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$SITE_PACKAGES"

pip install -r requirements/extractor.txt --target "$SITE_PACKAGES" --quiet

# Drop caches and dist-info RECORD noise so the zip hash only changes when the pinned
# dependencies do.
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  lambda_layer.zip ready -> $OUT_ZIP"
echo "    layout: python/lib/python3.12/site-packages/"
du -h "$OUT_ZIP" | awk '{print "    size:  " $1}'
