#!/usr/bin/env bash
# Builds the extractor Lambda's code-only deployment zip (PR-019).
#
# Replaces build_lambda_package.sh, which vendored requests + beautifulsoup4 into the
# same archive as the source. Dependencies now ship in a layer (build_lambda_layer.sh);
# this zip carries `loteria/` and nothing else, so the handler still resolves as
# `loteria.extractor.lambda_handler.lambda_handler` (the PR-016 layout).
#
# The output lands where Terraform expects it (root var `lambda_zip_path`, which
# defaults to `lambda_package.zip` relative to terraform/), so a plain `terraform apply`
# uploads the artifact and updates the function together.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/lambda"
OUT_ZIP="${REPO_ROOT}/terraform/lambda_package.zip"

echo "🔄  Rebuilding Lambda function package..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$BUILD_DIR"

cp -r src/loteria "$BUILD_DIR/loteria"

# Drop caches so the zip hash only changes when the code does.
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  lambda_package.zip ready -> $OUT_ZIP"
echo "    handler: loteria.extractor.lambda_handler.lambda_handler"
echo "    deps:    provided by the loteria-deps layer (scripts/build_lambda_layer.sh)"
du -h "$OUT_ZIP" | awk '{print "    size:    " $1}'
