#!/usr/bin/env bash
# Creates the pipeline's one secret in Secrets Manager (PR-039, `make secrets`).
#
# The secret must exist BEFORE the first `make deploy`: terraform/modules/iam looks it up
# by name (`data "aws_secretsmanager_secret"`) to scope the Lambda and Glue grants to its
# ARN, so a plan in an account without it fails at that lookup.
#
# Its shape is whatever src/loteria/common/aws_secrets.py:get_secrets() reads — two keys,
# nothing else:
#
#   s3_bucket_partitioned_data_storage_prod_arn   the partitioned bucket (the lake)
#   scrape_do_token                               the scrape.do API token
#
# PR-041.2 dropped the third, `s3_bucket_simple_data_storage_prod_arn`. A fresh account
# gets a secret without it; the LIVE prod payload still carries it, because Terraform does
# not own a secret's contents and removing it there is a manual owner edit — filed in
# docs/runbooks/PR-041-retire-simple-bucket.md. get_secrets() ignores the extra key either
# way, so the two shapes are interchangeable to the code.
#
# The bucket key is named *_arn and is stored as an ARN, to match the secret that runs in
# prod today. get_secrets() also accepts a bare bucket name (see _bucket_name). Terraform
# creates the bucket; the default below is the name module.storage gives it, so this can
# run before it exists.
#
# ⚠️ CREATE-ONLY. If a secret with this name already exists the script stops and changes
# nothing — `make secrets` must never be the way the prod token gets overwritten. To
# rotate the token, edit the secret deliberately (console, or `aws secretsmanager
# put-secret-value` with the full JSON: it replaces the whole payload, not one key).
#
# Never exercised against a fresh account: this stack was built by importing a running
# pipeline (PR-004 onward) and has not been deployed from zero.
#
# Inputs, all optional (each is prompted for when unset; .envrc.example sets the first two):
#   LOTERIA_SECRET_NAME   default lottery_secret_prod_2 (must match TF_VAR_lottery_secret_name)
#   SCRAPE_DO_TOKEN       read silently when unset, so it never lands in shell history
#   ENVIRONMENT           default prod — the suffix module.storage puts on bucket names
#   AWS_REGION            default us-east-1
set -euo pipefail

SECRET_NAME="${LOTERIA_SECRET_NAME:-lottery_secret_prod_2}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
REGION="${AWS_REGION:-us-east-1}"

# Only ResourceNotFoundException means "go ahead". Any other failure (expired credentials,
# wrong profile, no permission) must stop here rather than be read as "no secret yet".
if err="$(aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" \
  2>&1 >/dev/null)"; then
  echo "❌  Secret '$SECRET_NAME' already exists in $REGION. Nothing was changed." >&2
  echo "    This script only creates. To change a value, edit the secret deliberately." >&2
  exit 1
elif [[ "$err" != *ResourceNotFoundException* ]]; then
  echo "❌  Could not check for '$SECRET_NAME':" >&2
  echo "$err" >&2
  exit 1
fi

read -rp "Partitioned bucket name [lottery-partitioned-storage-${ENVIRONMENT}]: " partitioned
partitioned="${partitioned:-lottery-partitioned-storage-${ENVIRONMENT}}"

token="${SCRAPE_DO_TOKEN:-}"
if [[ -z "$token" ]]; then
  read -rsp "scrape.do token (hidden): " token
  echo
fi
if [[ -z "$token" ]]; then
  echo "❌  The scrape.do token is required — the extractor cannot fetch without it." >&2
  exit 1
fi

# json.dumps, not string interpolation: a token with a quote or backslash in it must not
# produce a secret that get_secrets() then fails to parse inside the Lambda.
payload="$(
  PARTITIONED="$partitioned" TOKEN="$token" python3 -c '
import json, os
print(json.dumps({
    "s3_bucket_partitioned_data_storage_prod_arn": "arn:aws:s3:::" + os.environ["PARTITIONED"],
    "scrape_do_token": os.environ["TOKEN"],
}))'
)"

# --secret-string reads from a file:// path rather than the command line, so the token is
# not visible in `ps` while the call runs.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf '%s' "$payload" >"$tmp"

aws secretsmanager create-secret \
  --name "$SECRET_NAME" \
  --description "Loteria pipeline: lake bucket ARN + scrape.do token (read by loteria.common.aws_secrets)" \
  --secret-string "file://$tmp" \
  --region "$REGION" \
  --query ARN --output text

echo "✅  Created '$SECRET_NAME'. Next: make deploy"
