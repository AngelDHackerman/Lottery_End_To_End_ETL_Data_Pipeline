#!/usr/bin/env bash
# Builds the extractor Lambda deployment zip.
#
# Zip layout (PR-016): dependencies at the root + the `loteria` package, so the
# function's handler resolves as `loteria.extractor.lambda_handler.lambda_handler`.
# Before PR-016 the zip carried a bare `extractor/` at its root.
#
# The output lands where Terraform expects it (root var `lambda_zip_path`, which
# defaults to `lambda_package.zip` relative to terraform/), so a plain
# `terraform apply` uploads the artifact and updates the handler together.
#
# TODO(PR-019): split the deps into a Lambda layer and ship a thin, code-only zip.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/lambda"
OUT_ZIP="${REPO_ROOT}/terraform/lambda_package.zip"

echo "🔄  Rebuilding Lambda package..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$BUILD_DIR"

pip install -r requirements/extractor.txt --target "$BUILD_DIR" --quiet
cp -r src/loteria "$BUILD_DIR/loteria"

# Drop caches so the zip hash only changes when the code does.
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  lambda_package.zip ready -> $OUT_ZIP"
echo "    handler: loteria.extractor.lambda_handler.lambda_handler"
