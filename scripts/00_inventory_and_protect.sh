#!/usr/bin/env bash
#
# 00_inventory_and_protect.sh — Phase 0 safety belt (roadmap PR-002).
#
# For each production data bucket this script:
#   1. Snapshots object count + total bytes into docs/inventory/<bucket>_<UTC_DATE>.txt
#   2. Enables S3 Versioning (idempotent — safe if already on)
#   3. Renders + applies a bucket policy that DENIES delete operations to every
#      principal EXCEPT the account root, saved under scripts/policies/<bucket>_protect.json
#
# It is IDEMPOTENT: re-running produces the same end state.
# It DRY-RUNS by default (prints the mutating AWS commands instead of running
# them). Pass --apply (or APPLY=1) to actually mutate AWS.
#
# Requires env vars: AWS_PROFILE, AWS_REGION.
#
# Out of scope (deliberately, per roadmap PR-002):
#   - Object Lock (can only be enabled at bucket creation; later PR)
#   - Any Terraform change
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BUCKETS=(
  "lottery-partitioned-storage-prod"
  "lottery-data-simple-prod"
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INVENTORY_DIR="${REPO_ROOT}/docs/inventory"
POLICY_DIR="${SCRIPT_DIR}/policies"
UTC_DATE="$(date -u +%Y-%m-%d)"
UTC_STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
POLICY_SID="Phase0DenyDeleteExceptRoot"

# Extra principals (beyond account root) exempted from the delete-Deny, per bucket.
# PR-022: the gold-purge Lambda role must delete under gold/ on the partitioned bucket to
# rebuild the (reproducible, silver-derived) gold layer before each Athena CTAS. Its IAM
# policy already scopes it to gold/* only, so exempting it here does not widen its reach
# to raw/ or silver/. Value is the ARN suffix after "arn:aws:iam::<account>:".
declare -A EXTRA_EXEMPT_PRINCIPALS=(
  ["lottery-partitioned-storage-prod"]="role/lottery-gold-purge-role-prod"
)

# Mode: dry-run unless --apply / APPLY=1
MODE="dry-run"
if [[ "${APPLY:-0}" == "1" ]]; then MODE="apply"; fi
for arg in "$@"; do
  case "$arg" in
    --apply) MODE="apply" ;;
    --dry-run) MODE="dry-run" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------- #
# Colors
# --------------------------------------------------------------------------- #
if [[ -t 1 ]]; then
  GREEN="$(printf '\033[0;32m')"; YELLOW="$(printf '\033[0;33m')"
  RED="$(printf '\033[0;31m')";   BOLD="$(printf '\033[1m')"; NC="$(printf '\033[0m')"
else
  GREEN=""; YELLOW=""; RED=""; BOLD=""; NC=""
fi

log()  { echo "${BOLD}==>${NC} $*"; }
warn() { echo "${YELLOW}!${NC} $*" >&2; }
die()  { echo "${RED}✗${NC} $*" >&2; exit 1; }

# Run a mutating command: echo it in dry-run, execute it in apply.
mutate() {
  if [[ "$MODE" == "dry-run" ]]; then
    echo "  ${YELLOW}[DRY-RUN]${NC} $*"
  else
    "$@"
  fi
}

# --------------------------------------------------------------------------- #
# Preconditions
# --------------------------------------------------------------------------- #
: "${AWS_PROFILE:?Set AWS_PROFILE (e.g. export AWS_PROFILE=angel-adming)}"
: "${AWS_REGION:?Set AWS_REGION (e.g. export AWS_REGION=us-east-1)}"
command -v aws >/dev/null 2>&1 || die "aws CLI not found on PATH"

log "Mode: ${BOLD}${MODE}${NC}  (profile=${AWS_PROFILE}, region=${AWS_REGION})"

# Identity / account id (read-only; runs in both modes — needed to render policy)
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)" \
  || die "Unable to resolve AWS account — are credentials valid?"
ROOT_ARN="arn:aws:iam::${ACCOUNT_ID}:root"
log "AWS account: ${ACCOUNT_ID}"

mkdir -p "$INVENTORY_DIR" "$POLICY_DIR"

# --------------------------------------------------------------------------- #
# Per-bucket work
# --------------------------------------------------------------------------- #
for bucket in "${BUCKETS[@]}"; do
  echo
  log "Processing ${BOLD}${bucket}${NC}"

  # --- 1. Inventory snapshot ------------------------------------------------ #
  inv_file="${INVENTORY_DIR}/${bucket}_${UTC_DATE}.txt"
  if [[ "$MODE" == "dry-run" ]]; then
    echo "  ${YELLOW}[DRY-RUN]${NC} aws s3 ls --summarize --recursive s3://${bucket} | grep Total > ${inv_file#${REPO_ROOT}/}"
  else
    # Capture only the summary totals (object count + bytes), not every key.
    totals="$(aws s3 ls --summarize --recursive "s3://${bucket}" | grep -E 'Total (Objects|Size):' || true)"
    {
      echo "# Inventory snapshot for s3://${bucket}"
      echo "# Generated (UTC): ${UTC_STAMP}"
      echo "# AWS account:     ${ACCOUNT_ID}"
      echo "${totals}"
    } > "$inv_file"
    echo "  inventory -> ${inv_file#${REPO_ROOT}/}"
    sed 's/^/    /' "$inv_file"
  fi

  # --- 2. Enable versioning (idempotent) ----------------------------------- #
  mutate aws s3api put-bucket-versioning \
    --bucket "$bucket" \
    --versioning-configuration Status=Enabled

  # --- 3. Deny-delete bucket policy ---------------------------------------- #
  policy_file="${POLICY_DIR}/${bucket}_protect.json"

  # Exempt principals: account root always, plus any per-bucket extras. Emitted as a bare
  # string for one principal (root-only) or a JSON array when there are extras — both are
  # valid for aws:PrincipalArn in a Condition.
  extra_exempt="${EXTRA_EXEMPT_PRINCIPALS[$bucket]:-}"
  if [[ -n "$extra_exempt" ]]; then
    principal_arns_json="[\"${ROOT_ARN}\", \"arn:aws:iam::${ACCOUNT_ID}:${extra_exempt}\"]"
  else
    principal_arns_json="\"${ROOT_ARN}\""
  fi

  cat > "$policy_file" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "${POLICY_SID}",
      "Effect": "Deny",
      "Principal": "*",
      "Action": [
        "s3:DeleteBucket",
        "s3:DeleteObject*"
      ],
      "Resource": [
        "arn:aws:s3:::${bucket}",
        "arn:aws:s3:::${bucket}/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalArn": ${principal_arns_json}
        }
      }
    }
  ]
}
JSON
  echo "  policy   -> ${policy_file#${REPO_ROOT}/}"

  # Guard: never clobber an UNRELATED existing policy. If a policy already
  # exists and does not contain our Sid, refuse and ask for a manual merge.
  existing="$(aws s3api get-bucket-policy --bucket "$bucket" --query Policy --output text 2>/dev/null || true)"
  if [[ -n "$existing" && "$existing" != "None" ]]; then
    if echo "$existing" | grep -q "$POLICY_SID"; then
      echo "  existing policy already contains ${POLICY_SID} (idempotent re-apply)"
    else
      warn "${bucket} already has a DIFFERENT bucket policy. Refusing to overwrite."
      warn "Merge ${POLICY_SID} into it manually, then re-run. Skipping policy step."
      echo "${GREEN}✅ ${bucket} protected${NC} (versioning only; policy skipped — see warning)"
      continue
    fi
  fi

  mutate aws s3api put-bucket-policy \
    --bucket "$bucket" \
    --policy "file://${policy_file}"

  echo "${GREEN}✅ ${bucket} protected${NC}"
done

echo
if [[ "$MODE" == "dry-run" ]]; then
  log "Dry-run complete. Re-run with ${BOLD}--apply${NC} to enact changes."
else
  log "Done. Versioning enabled + deny-delete policy applied on all buckets."
fi
