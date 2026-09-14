# PR-033 — The Silver data-quality gate

Connects PR-032's Great Expectations suites to the pipeline. Until this PR they existed,
were tested, and were **called by nothing** — the pipeline went straight from the silver
crawlers to the seven gold CTAS with no quality check anywhere in it.

## What changed

| Piece | File | Change |
|---|---|---|
| Entry point | `src/loteria/dq/glue_entrypoint.py` | **new** — bridges Glue's calling convention to `loteria.dq` |
| Reporting | `src/loteria/dq/runner.py` | `format_report` **moved here** from `scripts/run_dq.py`; `summarize_failures` added |
| CLI | `scripts/run_dq.py` | imports the two above instead of defining `format_report` |
| Build | `scripts/build_dq_package.sh` | **new** — builds `dist/loteria_silver_dq.py` + `dist/loteria_dq_lib.zip` |
| Build | `Makefile` | `make build` now builds the DQ artifacts too |
| Glue job | `terraform/modules/etl-glue/main.tf` | **new** `aws_glue_job.silver_dq` (Glue 5.0 `glueetl`) + its own log group |
| IAM | `terraform/modules/iam/main.tf` | **new** read-only `glue_dq_role`; SFN gains `glue:StartJobRun` on the DQ job and `sns:Publish` |
| Gate states | `terraform/modules/orchestration/main.tf` | `RunSilverDQ` → `NotifyDQFailure` → `SilverDQFailed` |
| Wiring | `terraform/main.tf` | `data.aws_caller_identity` + `local.alerts_topic_arn` |
| Coverage | `pyproject.toml` | ratchet 56 → 67 |

## The state machine, after this PR

```
RunExtractorLambda → RunTransformerGlueJob → RunSilverCrawlers (Parallel + polling)
  → RunSilverDQ  (Glue 5.0, .sync)
        │  pass                          │  any error
        ↓                                ↓
     PrepGold                      NotifyDQFailure (SNS publish)
        ↓                                ↓
     BuildGold (Map ×7)            SilverDQFailed (Fail)
```

Gold is not built when the gate fails. That is the whole point, and the reason it matters
more here than in most pipelines: `loteria.gold.purge_and_load` **drops each gold table and
empties its S3 prefix before the CTAS writes it**, so letting bad Silver through would not
just produce wrong Gold — it would destroy the last known-good Gold on the way there. The
gate protects the existing data as much as the incoming data.

## ⚠️ The job is a Spark job, and the roadmap said it would not be

The roadmap's prompt asks for "a Python Shell job that pip-installs great-expectations".
**That cannot work**, and PR-032 recorded why before this PR started:

- `great-expectations` 1.x declares `requires-python >=3.10`.
- Glue Python Shell supports only **3.6 and 3.9** (PR-020's runtime spike).
- On 3.9, pip silently resolves back to the GX **0.18** line, whose API is unrelated to the
  one `src/loteria/dq` is written against. It installs cleanly and fails at import — inside
  the job, on a Thursday.

So the DQ job is `glueetl` on **Glue 5.0 (Python 3.11)**. It never creates a `SparkContext`;
it runs as an ordinary Python process on the driver. We are paying for a Spark cluster to
get an interpreter version. At `2 × G.1X`, one run a week, seconds of work, that is a few
cents — cheaper than the alternatives (rewriting 20 expectations against GX 0.18, or moving
the gate onto Lambda/Fargate and maintaining a second runtime).

Consequences that are **not** cosmetic:

- `script_location` must be a **plain `.py`**, not a zip. Spark jobs are `spark-submit`'ed;
  they do not run a zip as a zipapp the way pythonshell does. The `__main__.py`-at-the-root
  trick from `scripts/glue_zip_main.py` does **not** apply — hence two artifacts.
- `max_capacity` cannot be combined with `worker_type`/`number_of_workers` for `glueetl`.
- A Spark job **can** have its own log group (`--continuous-log-logGroup` is Spark-only —
  the exact limitation PR-023 hit from the other side), so this one does.

## Why a separate, read-only IAM role

It would have been one line to reuse `glue_job_role`. That role holds `s3:PutObject` and
`s3:DeleteObject` on both data buckets, because the transformer writes Silver.

**A validator that can modify what it validates is not a gate.** The entire value of this PR
is that something independent asserts "Silver is fine", so the thing asserting it must not
be able to change Silver. `glue_dq_role` has `s3:GetObject` + `s3:ListBucket` on the Silver
prefix, read on the artifact bucket, and CloudWatch Logs. No write, no delete, no Secrets
Manager.

## Deploy

### 1. Build and upload the artifacts

Terraform does **not** manage these S3 objects (same as the transformer zip).

```bash
make build            # or: bash scripts/build_dq_package.sh
aws s3 cp dist/loteria_silver_dq.py s3://lambda-code-zip-prod/loteria_silver_dq.py
aws s3 cp dist/loteria_dq_lib.zip   s3://lambda-code-zip-prod/loteria_dq_lib.zip
```

**Upload both, always.** The script imports `loteria.dq` from the zip, so a stale zip fails
at import *inside the job*, not at deploy time — the failure surfaces as a red Thursday run.

> ⚠️ `make build` also rebuilds the Lambda layer and the transformer zip, which changes their
> hashes and produces plan churn unrelated to this PR (the known annoyance from PR-023).
> Run `bash scripts/build_dq_package.sh` alone if you want a clean plan diff.

### 2. Validate the rendered ASL **before** applying

Three new states were added by hand, including a `States.Format` intrinsic and a `Catch`
that writes to `$.dqError`. A typo here is a runtime failure minutes into a weekly run.
Same procedure as PR-026.1:

```bash
cd terraform
terraform plan -out=tfplan
terraform show -json tfplan > plan.json
python3 -c "
import json
p=json.load(open('plan.json'))
for rc in p['resource_changes']:
    if rc['address'].endswith('pipeline_state_machine'):
        open('asl.json','w').write(rc['change']['after']['definition'])
"
aws stepfunctions validate-state-machine-definition --definition file://asl.json --type STANDARD
```

Expected: `{"result": "OK", "diagnostics": []}`.

What this catches that `terraform validate` cannot: the `States.Format` placeholder count
(two `{}`, two arguments), the `$$.Execution.Name` context reference, and the `sns:publish`
parameter shape. The transition graph itself was already checked statically — every `Next`
target names a state that exists.

### 3. Apply

```bash
terraform apply tfplan
```

New resources: 1 Glue job, 1 log group, 1 IAM role, 1 IAM policy, 1 attachment. Modified:
`sfn_execution_policy` and the state machine definition. **No data resources are touched.**

### 4. Run the gate on its own, before trusting the pipeline to it

Do this before the first Thursday. It is the same code `make dq` runs locally, so a green
local run is a good predictor — but the job has its own role, its own runtime and its own
dependency install, and all three are new.

```bash
aws glue start-job-run \
  --job-name loteria-silver-dq-prod \
  --arguments '{"--PARTITIONED_BUCKET":"lottery-partitioned-storage-prod","--CORRELATION_ID":"manual-smoke-1"}'

# then, with the JobRunId it returns:
aws glue get-job-run --job-name loteria-silver-dq-prod --run-id <id> \
  --query 'JobRun.{State:JobRunState,Error:ErrorMessage,Seconds:ExecutionTime}'
```

Expected: `SUCCEEDED`. The verdict is in
`/aws-glue/jobs/loteria-silver-dq-prod` — look for the `DQ RESULT: PASS` line.

**Expect the first run to be slow.** `--additional-python-modules` pip-installs
great-expectations at job start; the validation itself is seconds, the install is not.

**Failure triage on this first run:**

| Symptom | Almost certainly |
|---|---|
| `ModuleNotFoundError: loteria` | the zip was not uploaded, or uploaded under a different key |
| `ModuleNotFoundError: great_expectations` | `--additional-python-modules` did not resolve — check job egress |
| `AccessDenied` on `ListObjectsV2` | `glue_dq_role` policy did not apply, or `silver_prefix` drifted |
| `No Silver data to validate` | wrong bucket or prefix. **Not** a data-quality failure — this is the distinction the entry point exists to draw |

### 5. Prove the gate actually closes

A gate that has only ever passed is indistinguishable from no gate. This is the PR-031
canary lesson — a check that always skips teaches everyone to ignore it.

The safe way, without touching real Silver: point the job at a prefix that does not exist
and confirm it fails with the *wiring* message rather than a quality one.

```bash
aws glue start-job-run --job-name loteria-silver-dq-prod \
  --arguments '{"--PARTITIONED_BUCKET":"lottery-partitioned-storage-prod","--SILVER_PREFIX":"silver_does_not_exist/"}'
```

Expected: `FAILED`, with `ErrorMessage` containing `No Silver data to validate` and
`wiring problem`.

To exercise a *real* expectation failure end to end, copy one Silver Parquet into a scratch
prefix, duplicate a `numero_sorteo` in it, and run against that prefix — never against
`silver/`. `tests/unit/test_dq_runner.py::TestRunDQ::test_a_duplicated_sorteo_across_two_files_fails`
already covers the logic; this only confirms the alert plumbing.

### 6. Confirm the alert wiring

Only reachable through a failing execution, so it is easiest to verify by reading rather
than by breaking production:

- `NotifyDQFailure` publishes to `arn:aws:sns:<region>:<account>:loteria-alerts-prod`.
- That ARN is **built from the name** in `terraform/main.tf`, not taken from
  `module.observability`, because observability already consumes orchestration — passing the
  output back would be a module cycle.
- **This is the one coupling a plan will not catch.** Renaming the topic in
  `modules/observability/main.tf` leaves both sides valid strings and produces an
  `AccessDenied` at the first DQ failure. If the topic is ever renamed, `terraform/main.tf`
  and `modules/iam/main.tf` must move with it.

## Rollback

The gate is one state and two error states. To disable it without reverting the code, point
`RunSilverCrawlers.Next` back at `"PrepGold"` and apply — the Glue job, the role and the log
group can stay, costing nothing while idle.

Reverting the whole PR is also safe: it creates no data and deletes nothing. The one
non-obvious piece is the coverage ratchet (67 → 56) in `pyproject.toml`, which must go back
with it or the suite fails on the revert commit.

## Not done here, deliberately

**Referential integrity** — every `premios.numero_sorteo` existing in `sorteos` — is still
the highest-value expectation the suites lack, and PR-032 flagged it as belonging to this
PR's runtime wiring. It needs a value set computed at run time from a second dataset, which
is a change to `loteria.dq.runner`'s validation model rather than to this PR's plumbing, and
mixing the two would have made the gate's first version harder to review. It belongs in
PR-035.
