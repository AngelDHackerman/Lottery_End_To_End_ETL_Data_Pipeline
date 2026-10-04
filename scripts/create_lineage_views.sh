#!/usr/bin/env bash
# Creates (or replaces) the Silver lineage views in Athena (PR-045.2, `make lineage-views`).
#
# One Athena statement per file in sql/lineage/, in filename order — 02 reads the view 01
# creates, so the order is a dependency, not a preference.
#
# WHY A SCRIPT AND NOT TERRAFORM. An Athena view lives in Glue as a base64 blob of Athena's
# own JSON, carrying both the SQL and a column list that has to agree with it. Declaring it
# in Terraform means hand-maintaining an undocumented serialisation whose drift is invisible
# until a query fails — and it does drift: the views already in this account carry keys the
# public Terraform examples never mention. Athena writes the blob; this repo owns the SQL.
# The two Silver TABLES, whose schema is ours rather than Athena's, are in Terraform.
#
# Idempotent: CREATE OR REPLACE VIEW. Safe to re-run, and the way to recover a view that was
# dropped by hand. It reads nothing and writes no data — a view is catalog metadata, so this
# scans 0 bytes and costs nothing.
#
# Needs: AWS credentials, the lottery-wg workgroup (module.catalog), and LF/IAM rights to
# CREATE_TABLE in the database — a Lake Formation grant the owner already holds as a data
# lake admin. See docs/runbooks/PR-045.2-lineage-queryable.md §4.
set -euo pipefail

DATABASE="${DATABASE:-lottery_santalucia_db}"
WORKGROUP="${WORKGROUP:-lottery-wg}"
SQL_DIR="${SQL_DIR:-sql/lineage}"

shopt -s nullglob
files=("${SQL_DIR}"/*.sql)
if [ ${#files[@]} -eq 0 ]; then
  echo "No .sql files under ${SQL_DIR} — nothing to create. Refusing to report success." >&2
  exit 1
fi

for file in "${files[@]}"; do
  echo "==> ${file}"
  qid=$(aws athena start-query-execution \
    --work-group "${WORKGROUP}" \
    --query-execution-context "Database=${DATABASE}" \
    --query-string "file://${file}" \
    --query QueryExecutionId --output text)

  # Poll rather than sleep-and-hope. DDL against the catalog is seconds; the cap is here so
  # a stuck query ends as a failure someone reads instead of a job that never returns.
  state=""
  for _ in $(seq 1 60); do
    state=$(aws athena get-query-execution --query-execution-id "${qid}" \
      --query 'QueryExecution.Status.State' --output text)
    case "${state}" in
    SUCCEEDED | FAILED | CANCELLED) break ;;
    esac
    sleep 2
  done

  if [ "${state}" != "SUCCEEDED" ]; then
    reason=$(aws athena get-query-execution --query-execution-id "${qid}" \
      --query 'QueryExecution.Status.StateChangeReason' --output text)
    echo "FAILED (${state}) ${qid}: ${reason}" >&2
    exit 1
  fi
  echo "    ${state} (${qid})"
done

echo
echo "Views in ${DATABASE}:"
aws glue get-tables --database-name "${DATABASE}" \
  --query "TableList[?TableType=='VIRTUAL_VIEW'].Name" --output text
