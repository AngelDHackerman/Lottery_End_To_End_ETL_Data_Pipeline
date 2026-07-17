# Module: `etl-lambda`

The extractor Lambda function (scrapes loteria.org.gt), its S3 deployment artifact, and
its dependency layer.

**Status:** migrated in **PR-010** from `terraform-lottery/Prod/lambdas.tf` via cross-state
`terraform state rm` (legacy) + `terraform import` (main) — the function was not recreated.
See `docs/runbooks/PR-010-lambda-migration.md` for the exact commands.

## Deliberate change vs. the legacy config

The function's environment variables now carry bucket **names** (not ARNs) plus
`LOTERIA_SECRET_NAME`. This shows up as one in-place update on first apply. It is safe:
the extractor code currently reads all its config from Secrets Manager
(`src/loteria/common/aws_secrets.py`); PR-017 switches the code to consume these env vars.

**PR-016:** the deployment zip now carries the `loteria` package at its root, so
`handler` is `loteria.extractor.lambda_handler.lambda_handler` (was
`extractor.lambda_handler.lambda_handler`).

## The two artifacts (PR-019)

The single fat zip was split along the deps/code seam:

| Artifact | Built by | Contents | Size |
|---|---|---|---|
| `lambda_package.zip` | `scripts/build_lambda_function.sh` | `loteria/` only | ~16 KB |
| `lambda_layer.zip` | `scripts/build_lambda_layer.sh` | requests + beautifulsoup4 + transitive deps | ~888 KB |

Both are gitignored and rebuilt with `make build`, which must run **before**
`terraform apply` — the paths are hashed by `filemd5` / `filebase64sha256`, so a missing
file fails the plan. They are no longer hand-synced from S3.

The layer's internal layout is `python/lib/python3.12/site-packages/`. That nesting is
load-bearing: Lambda mounts layers at `/opt`, and only `/opt/python` and
`/opt/python/lib/python3.12/site-packages` are on the runtime's `sys.path`. A wrong
layout mounts cleanly and then fails every import at runtime.

Layer versions are immutable — changing `requirements/extractor.txt` publishes version
N+1 rather than mutating N. `create_before_destroy` keeps the live function pointed at a
valid version throughout the swap.

**Build the layer on Linux x86_64** (WSL2 qualifies; native Windows and macOS do not).
`pip` resolves wheels for the machine running it, and `charset_normalizer` is the one
dependency here that is not pure Python. Building elsewhere does not break the layer —
`charset_normalizer` falls back to its pure-python path — it just runs slower and carries
a dead `.so`. The failure is silent, which is why `compatible_architectures` is pinned.
See the runbook for the full story.

`boto3` is deliberately absent from both artifacts: the Python 3.12 runtime already
ships it.

## Inputs / outputs

- Inputs: `lambda_code_bucket`, `lambda_zip_key`, `lambda_zip_path`,
  `lambda_layer_zip_key`, `lambda_layer_zip_path`, `lambda_exec_role_arn`,
  `partitioned_bucket_name`, `simple_bucket_name`, `secret_name`, `region`,
  `environment`.
- Outputs: `extractor_lambda_arn`, `extractor_lambda_name`, `deps_layer_arn`.
