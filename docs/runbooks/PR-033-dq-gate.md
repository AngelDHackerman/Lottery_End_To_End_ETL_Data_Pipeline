# PR-033 — Deploying the Silver DQ gate

Everything here is NEW: nothing has to be imported, and the state machine is updated in
place. But the order matters, because the Glue job's artifacts live in S3 and Terraform does
not manage those objects.

## Why this job is a Spark job

`great-expectations` 1.x declares `requires-python >=3.10`. Glue Python Shell supports only
3.6 and 3.9 (PR-020's runtime spike, and re-verified against the AWS docs in PR-033). The
roadmap's "Python Shell job that pip-installs great-expectations" therefore cannot work: on
3.9, pip resolves back to the GX 0.18 line, whose API is unrelated to the one
`src/loteria/dq` is written against, so it would install cleanly and fail at import.

Glue 5.0 (`glueetl`) is where Python 3.11 lives. The script never creates a SparkContext, so
it runs as an ordinary Python process on the driver — the cluster is the price of the
interpreter version, not a design choice.

## Deploy order

The artifacts must exist in S3 **before** the first run, or the job fails with a missing
script. Terraform will happily create a job pointing at an object that does not exist.

```bash
# 1. Build and upload the two artifacts.
make build                       # runs scripts/build_dq_package.sh among others
aws s3 cp dist/loteria_silver_dq.py s3://lambda-code-zip-prod/loteria_silver_dq.py
aws s3 cp dist/loteria_dq_lib.zip   s3://lambda-code-zip-prod/loteria_dq_lib.zip

# 2. Apply. Expect 5 to add, 3 to change, 0 to destroy.
cd terraform && terraform apply
```

If you would rather apply the stack first, set `enable_silver_dq = false`. The state machine
then renders **byte-identical** to the pre-PR-033 definition (verified with a plan diff), the
Glue job and its log group are not created, and only the IAM role and policy appear. Flip it
back to `true` once the artifacts are up.

### Expected plan

| Action | Resource |
|--------|----------|
| create | `module.etl_glue.aws_cloudwatch_log_group.silver_dq[0]` |
| create | `module.etl_glue.aws_glue_job.silver_dq[0]` |
| create | `module.iam.aws_iam_role.glue_dq_job` |
| create | `module.iam.aws_iam_policy.glue_dq_job_policy` |
| create | `module.iam.aws_iam_role_policy_attachment.glue_dq_custom` |
| update | `module.iam.aws_iam_policy.sfn_execution_policy` |
| update | `module.orchestration.aws_sfn_state_machine.pipeline_state_machine` |
| update | `module.orchestration.aws_lambda_function.gold_purge` |

The last one is **not** part of this PR. `data.archive_file.gold_purge` re-zips on every plan
and its `source_code_hash` goes unknown-until-apply; it shows up on any plan run after a
`make build`. Nothing about the gold-purge Lambda changed here.

## Verifying it

```bash
# Run the job by hand before trusting the schedule.
aws glue start-job-run --job-name loteria-silver-dq-prod \
  --arguments '{"--CORRELATION_ID":"manual-check"}'

# Watch its own log group (Spark jobs, unlike pythonshell ones, get one).
aws logs tail /aws-glue/jobs/loteria-silver-dq-prod --follow
```

A pass ends with `DQ RESULT: PASS`. The same validation can be run locally against the same
data — `make dq PARTITIONED_BUCKET=lottery-partitioned-storage-prod` — which is the faster
way to iterate on a suite.

To exercise the failure path without corrupting anything, temporarily narrow an expectation
(for example drop a departamento from `DEPARTAMENTOS`), run `make dq-sync`, rebuild, upload,
and start the job. Expect: Glue run FAILED → `RunSilverDQ` task fails → `NotifyDQFailure`
publishes → `DQFailed` fails the execution → **no Gold CTAS runs**.

## What a failure looks like

The alert email body is Glue's `ErrorMessage`, which for a Python exception is the exception
string — so `scripts/glue_dq_main.py` raises with a summary naming the suite, expectation and
column. Offending *values* are deliberately excluded: a failing column can be full of vendor
names and this goes to an inbox. The full report, samples included, is in the job's log group.

When it fires, the gold tables are **stale, not wrong** — the previous run's CTAS output is
untouched, because the gate stopped the rebuild before `PrepGold`.

## Things worth knowing

- **PyPI egress is required.** `--additional-python-modules` installs
  great-expectations at run time. The job has no `connections` block, so it runs in Glue's
  managed network, which has internet access. Moving it into the project VPC would break the
  install unless `enable_internet` is on — there is no NAT otherwise.
- **The DQ job reads S3 directly, not through the Glue catalog**, so Lake Formation is not in
  the path and the role needs no `lakeformation:GetDataAccess` (unlike the Step Function role
  for the gold CTAS). This is deliberate: whole-dataset uniqueness cannot be checked one
  catalog partition at a time.
- **It does not need the crawlers.** Reading S3 directly means the gate has no data dependency
  on `RunSilverCrawlers`, and could run in parallel with it to save a couple of minutes. Kept
  sequential because a linear chain is much easier to read in the console at 11pm, and the
  saving is minutes on a weekly job.
- **The role is separate from the transform job's on purpose.** A component whose whole
  purpose is to judge the data should not be able to change it, and should not carry the
  scraper's Secrets Manager access. `lottery-glue-dq-role-prod` has no `PutObject` and no
  `DeleteObject` at all.
- **`AWSGlueServiceRole` is deliberately not attached.** That managed policy grants `glue:*`
  plus S3 write on any `aws-glue-*` bucket. This job reads Silver and writes logs.
