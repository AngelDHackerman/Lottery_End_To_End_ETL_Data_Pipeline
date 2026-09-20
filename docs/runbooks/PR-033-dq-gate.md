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
| Kill switch | `terraform/variables.tf` | `enable_silver_dq` (default `true`) |
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

## The kill switch: `enable_silver_dq`

One root variable drives both modules. With `enable_silver_dq = false`:

- `module.etl_glue` creates neither the Glue job nor its log group (`count = 0`), and
- `module.orchestration` renders the state machine **byte-identically to its pre-PR-033
  form** — `local.dq_states` is an empty map and the crawlers point straight at `PrepGold`.

This exists so the stack is applyable **before** the job artifacts have been built and
uploaded. Without it, a fresh clone has to either upload artifacts it has not built yet, or
apply a Glue job whose `script_location` points at a key that does not exist — and Glue
accepts the second quietly, failing only at the first run, which is the worse of the two.

It is also the rollback: flip the flag and apply, no revert needed.

> ⚠️ **The flag must have the same value in both modules.** It is threaded from a single
> root variable for exactly that reason. `true` in orchestration with `false` in etl-glue
> would render a state machine that starts a Glue job that does not exist.

**Why the states are gated as a JSON string and then `jsondecode`d**, rather than
`var.enable_silver_dq ? {...} : {}`: Terraform requires both branches of a conditional to
unify to one type, and an ASL state map is heterogeneous by construction — a `Task` has
`Resource`/`Parameters`/`Catch`, a `Fail` has `Error`/`Cause`, and they share no attributes.
The direct form fails with *"the 'true' value includes object attribute "SilverDQFailed",
which is absent in the 'false' value"*. That is a real type mismatch, not a Terraform quirk.
Gating a string sidesteps unification, and `jsondecode` returns a map `merge()` accepts.

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

## Two checkov findings, accepted deliberately

The two resources this PR creates each trip a check, and PR-034's baseline was edited to
accept both:

| Check | Resource |
|---|---|
| `CKV_AWS_158` — CloudWatch log group not encrypted with a KMS CMK | `aws_cloudwatch_log_group.silver_dq` |
| `CKV_AWS_195` — Glue component has no security configuration | `aws_glue_job.silver_dq` |

**Neither is a new concession.** The sibling resources in the same file — the shared Python
Shell log groups and the transform job — already carry exactly these two check ids in the
baseline. Accepting them here keeps one standing project decision (SSE-managed encryption
rather than a customer-managed CMK) applied consistently, instead of making the DQ job the
one resource in the stack with a CMK and a key policy to maintain.

This mattered enough to do in the open: PR-034's baseline arrived with these two entries
**already in it**, because it was generated on a branch that contained this PR. They were
stripped there so these resources would be evaluated fresh when they actually landed — which
is what happened, and this is the deliberate acceptance that follows. A baseline that
pre-accepts findings for resources nobody has reviewed is not a ratchet.

Revisit if the log ever carries something the rest of the lake does not. Today it carries
expectation names, column names, row counts and sample values from failing rows — all of it
derived from data the lottery publishes publicly.

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

If the artifacts are not uploaded yet, apply with the gate off first — this is a real no-op
on the state machine, not an approximation:

```bash
terraform apply -var="enable_silver_dq=false"
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

> **It took two goes to make that true.** PR-033 asked Glue to fill the group with
> `--continuous-log-logGroup`; that ships *Spark's* log4j output and this job never starts
> Spark, so the group had **zero** streams. PR-033.1 made the job write to the group itself
> — and its first run produced a stream with **zero events**, because the handler fed its
> own boto3 log records back into itself and disabled itself (PR-033.2). Read the group by
> job-run date:
>
> | Run date | Where the verdict actually is |
> |---|---|
> | before 2026-09-20 20:55 UTC | `/aws-glue/jobs/output`, stream = the `jr_…` id |
> | from `jr_2101…` (2026-09-20 20:55 UTC) on | `/aws-glue/jobs/loteria-silver-dq-prod` |
>
> **Read the events, not the stream metadata.** `describe-log-streams` on a healthy stream
> reported `storedBytes: 0` and `firstEventTimestamp == lastEventTimestamp` while
> `get-log-events` returned all six events; those fields lag by minutes. A stream existing
> proves nothing either — the broken handler created one on every run and never wrote to it.
>
> **The stream is not named after the job run.** It is named with the correlation id — the
> Step Function execution name for a pipeline run, a fresh UUID for a manual one. To tie a
> stream back to a console run, match the `job_run_id` field on the `Silver DQ starting`
> line in `/aws-glue/jobs/output`, or the `correlation_id` those JSON lines carry.

**Expect the run to be slow the first time, not every time.** `--additional-python-modules`
pip-installs great-expectations at job *start*. Four measured runs:

| Run | Wall clock | Billed (`ExecutionTime`) |
|---|---|---|
| `jr_6873…` 2026-09-16 | **21m47s** | 86s |
| `jr_910c…` 2026-09-16 | **20m08s** | 82s |
| `jr_3c3d…` 2026-09-17 | 1m56s | 95s |
| `jr_68c2…` 2026-09-20 | 1m44s | 96s (start-up: 8s) |

The validation itself is a constant ~90 seconds; only the startup varies, and it collapsed
after the 16th — most likely Glue caching the resolved environment per job, though that is
an inference from four runs and not something AWS documents. So: **a 20-minute run is not a
hang** (the console showing `Duration 0s` through the wait is billed time, which excludes
startup), and **a 2-minute run is not a job that skipped the work** — check the
`Suite validated` lines with their row counts before believing either.

> PR-033.1 raised `timeout` from 30 to 60 minutes for exactly this reason: at 30 the slow
> startup left ~8 minutes of margin, and a slow PyPI day would trip the timeout — which the
> state machine's `Catch` reports as `NotifyDQFailure`, i.e. a **false** "Silver failed
> quality" alert that also blocks Gold. The ceiling has to cover the worst case this job has
> shown, not the case it usually shows. Raising it costs nothing (billed time excludes the
> startup); it is a stopgap, not the fix. The fix is to stop installing at runtime — see
> PR-033.1 in the roadmap.

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

## Verified in prod (2026-09-16 → 2026-09-20)

Applied with `terraform apply tfplan`: **6 added, 5 changed, 1 destroyed**. The plan showed
`6/6/1` — the extra `change` was `module.orchestration.aws_lambda_function.gold_purge`, the
known phantom from the deferred `archive_file` data source (PR-027), which resolved to a
no-op once the data source was actually read. The `1 destroyed` was the previous
`aws_lambda_layer_version`: layer versions are immutable, so a rebuilt zip publishes N+1 and
retires N. Both of those came from running the full `make build` rather than
`scripts/build_dq_package.sh` alone.

Checked before the first run, all read-only:

| | |
|---|---|
| Artifacts in S3 vs `dist/` | identical (6,414 B and 39,621 B) |
| `RunSilverDQ` in the deployed ASL | present; crawlers → gate → `PrepGold`, catch → `NotifyDQFailure` |
| SNS ARN in `NotifyDQFailure` | matches the real topic — **this is the coupling a plan cannot catch** |
| Topic subscription | `email`, confirmed (not `PendingConfirmation`) |
| `glue-silver-dq-role-prod` | `s3:GetObject` + `s3:ListBucket` + logs only. No `Put`, no `Delete`, no Secrets Manager |

**Both directions of the gate were exercised**, which is the part that matters — a gate that
has only ever passed is indistinguishable from no gate:

| Run | Result |
|---|---|
| `jr_6873896084f7a785…` (step 4, real Silver) | `SUCCEEDED` · 20 expectations over 115 sorteos / 121,050 premios · `DQ RESULT: PASS` |
| `jr_910c242d010ea13c…` (step 5, `--SILVER_PREFIX silver_does_not_exist/`) | `FAILED` · `SilverDataQualityFailed: No Silver data to validate … this is a wiring problem, not a data-quality one` |

The second run is the valuable one. It proves the gate closes **and** that it distinguishes
a wiring fault from a data fault in the string the SNS alert will carry.

Two defects were found by these runs and are fixed in PR-033.1: the per-job log group stayed
empty, and the 30-minute timeout left only ~8 minutes of margin over a 22-minute startup.

## Rollback

```bash
terraform apply -var="enable_silver_dq=false"
```

That is the whole rollback. The state machine returns to its exact pre-PR-033 definition and
the Glue job and its log group are destroyed. The read-only IAM role stays — it is
deliberately **not** gated, because an unused role costs nothing and grants nothing (only
`glue.amazonaws.com` can assume it, and only for a job that no longer exists), while gating
it would add a null-ARN dependency to `module.etl_glue` for no benefit.

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
