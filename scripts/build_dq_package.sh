#!/usr/bin/env bash
# Builds the two artifacts the Silver DQ Glue job needs (PR-033).
#
#   dist/loteria_silver_dq.py   the job script  -> aws_glue_job.command.script_location
#   dist/loteria_dq_lib.zip     the library     -> --extra-py-files
#
# TWO artifacts, unlike the transformer's single zipapp, because this is a `glueetl` (Spark)
# job rather than `pythonshell`. Glue runs a pythonshell job as `python <artifact>`, so a
# zipapp with a __main__.py at its root works there. A glueetl job instead expects a plain
# .py at script_location and puts anything in --extra-py-files on sys.path — so the entry
# point and the package have to be shipped separately.
#
# Why glueetl at all, for a script that never touches Spark: great-expectations 1.x needs
# Python >= 3.10 and Python Shell tops out at 3.9 (PR-032's finding). Glue 5.0 is where
# Python 3.11 lives. See scripts/glue_dq_main.py.
#
# great-expectations itself is NOT vendored here — the job installs it at run time via
# --additional-python-modules, pinned in requirements/dq.txt. Vendoring it would mean
# shipping scipy and altair through S3 on every deploy.
#
# Terraform does NOT manage these S3 objects (same as the transformer zip), so uploading is
# a separate step. This script prints the commands.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/dq"
OUT_ZIP="${REPO_ROOT}/dist/loteria_dq_lib.zip"
OUT_SCRIPT="${REPO_ROOT}/dist/loteria_silver_dq.py"

: "${CODE_BUCKET:=lambda-code-zip-prod}"

echo "🔄  Rebuilding Silver DQ package..."
rm -rf "$BUILD_DIR" "$OUT_ZIP" "$OUT_SCRIPT"
mkdir -p "$BUILD_DIR" "$(dirname "$OUT_ZIP")"

cp -r src/loteria "$BUILD_DIR/loteria"
find "$BUILD_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 "$REPO_ROOT/scripts/_zipdir.py" "$OUT_ZIP")

cp scripts/glue_dq_main.py "$OUT_SCRIPT"

echo "✅  Silver DQ artifacts ready:"
echo "      $OUT_SCRIPT   (job script)"
echo "      $OUT_ZIP      (--extra-py-files)"
echo
echo "    Upload them (Terraform does not manage these objects):"
echo "      aws s3 cp $OUT_SCRIPT s3://${CODE_BUCKET}/loteria_silver_dq.py"
echo "      aws s3 cp $OUT_ZIP s3://${CODE_BUCKET}/loteria_dq_lib.zip"
