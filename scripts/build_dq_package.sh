#!/usr/bin/env bash
# Builds the Silver data-quality Glue job artifacts (PR-033).
#
# TWO artifacts, unlike the transformer's single zipapp, because this is a Spark
# (`glueetl`) job and Spark jobs are wired differently from Python Shell ones:
#
#   dist/loteria_silver_dq.py   -> the job's `script_location`. A Spark job's script must
#                                  be a plain .py file; Glue runs it with spark-submit, it
#                                  does NOT run a zip as a zipapp the way pythonshell does.
#                                  So there is no __main__.py trick here (cf.
#                                  scripts/glue_zip_main.py) — the script IS the entry point.
#   dist/loteria_dq_lib.zip     -> the `loteria` package, passed as `--extra-py-files`,
#                                  which puts it on sys.path for the script above.
#
# Third-party deps are NOT vendored into the zip. great-expectations arrives through the
# job's `--additional-python-modules` (see terraform/modules/etl-glue/main.tf) because it
# has compiled transitive dependencies that must be resolved for the runtime's Python, not
# for whatever built this zip. pandas and pyarrow already ship with Glue 5.0.
#
# As with the transformer zip, Terraform does NOT manage these S3 objects — uploading is a
# separate step, and this script prints the commands.
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

# The entry point ships twice on purpose: once as the standalone script Glue executes, and
# once inside the library zip (it lives in src/loteria/dq/ so it is importable and unit
# tested). Copied rather than symlinked so the artifact is self-contained.
cp src/loteria/dq/glue_entrypoint.py "$OUT_SCRIPT"

echo "✅  Silver DQ artifacts ready:"
echo "      $OUT_SCRIPT   (job script_location)"
echo "      $OUT_ZIP   (--extra-py-files)"
echo
echo "    Upload them (Terraform does not manage these objects):"
echo "      aws s3 cp $OUT_SCRIPT s3://${CODE_BUCKET}/loteria_silver_dq.py"
echo "      aws s3 cp $OUT_ZIP s3://${CODE_BUCKET}/loteria_dq_lib.zip"
echo
echo "    Both must be uploaded together — the script imports loteria.dq from the zip, so a"
echo "    stale zip fails at import inside the job, not at deploy time."
