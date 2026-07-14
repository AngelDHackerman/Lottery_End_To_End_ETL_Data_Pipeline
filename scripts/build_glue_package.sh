#!/usr/bin/env bash
# Builds the Glue transformer job zip (bronze -> silver).
#
# Zip layout (PR-016): the `loteria` package at the root, so the job's
# `--script-file` resolves as `loteria/transformer/transformer.py`. Before PR-016 the
# zip carried bare `transformer/`, `parser/` and `extractor/` dirs at its root.
#
# Code only — no vendored deps. The Glue pythonshell runtime already ships pandas,
# pyarrow and boto3 (see requirements/glue.txt for the versions this code was written
# against); `awsglue` only exists inside Glue.
#
# Unlike the Lambda zip, Terraform does NOT manage this S3 object, so uploading is a
# separate step. This script prints the command.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/glue"
OUT_ZIP="${REPO_ROOT}/dist/lottery_transformer.zip"

: "${CODE_BUCKET:=lambda-code-zip-prod}"

echo "🔄  Rebuilding Glue transformer package..."
rm -rf "$BUILD_DIR" "$OUT_ZIP"
mkdir -p "$BUILD_DIR" "$(dirname "$OUT_ZIP")"

cp -r src/loteria "$BUILD_DIR/loteria"

# Glue runs the artifact as `python lottery_transformer.zip`, i.e. as a zipapp, so Python
# needs a __main__.py at the zip ROOT. (`--script-file` does not select the entry point.)
cp scripts/glue_zip_main.py "$BUILD_DIR/__main__.py"

find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

echo "✅  lottery_transformer.zip ready -> $OUT_ZIP"
echo "    entry point: __main__.py at the zip root -> loteria.transformer.transformer:main"
echo
echo "    Upload it (Terraform does not manage this object):"
echo "      aws s3 cp $OUT_ZIP s3://${CODE_BUCKET}/lottery_transformer.zip"
