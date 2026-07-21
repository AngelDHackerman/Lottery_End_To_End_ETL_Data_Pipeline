# PR-020 — Glue runtime spike: stay on Python Shell 3.9

**Outcome: keep the transform job on Python Shell, Python 3.9. No version bump.**

The roadmap prompt asked to bump the `etl-glue` defaults to `glue_version = "4.0"` /
`python_version = "3.10"`, run the job once, and keep-or-revert with evidence. The spike's
finding is that the target **is not valid for this job type**, so the "keep" branch of the
acceptance criteria applies — with the evidence below.

## The job is Python Shell, not Spark

`terraform/modules/etl-glue/main.tf` defines the job with `command.name = "pythonshell"`,
`max_capacity = 1` (1 DPU). AWS Glue has two unrelated job families that version
differently:

| | Python Shell (this job) | Spark ETL |
|---|---|---|
| `command.name` | `pythonshell` | `glueetl` |
| Runtime knob | `python_version` (3.6 / 3.9) | `glue_version` (3.0 / 4.0 / 5.0) |
| Runs on | one Python process | a Spark cluster |
| "Glue 4.0" | **ignored** | applies |

"Glue 4.0 / Python 3.10" mixes Spark vocabulary (`glue_version 4.0`) with a Python Shell
job. The two don't compose.

## Evidence

**1. Python Shell supports only Python 3.6 or 3.9.** Per the AWS Glue docs:

> "Valid versions are Python 3.6 and Python 3.9. The default is Python 3.9."
> "Support for Pyshell v3.6 will end on March 1, 2026."

There is no Python 3.10 option. 3.9 is the sole current runtime.

**2. `glue_version` is inert for Python Shell.** Per the same docs:

> "You don't need to specify the version of AWS Glue since the parameter `--glue-version`
> doesn't apply for AWS Glue shell jobs. Any version specified will be ignored."

Confirmed against prod (read-only, 2026-07-21):

```
$ aws glue get-job --job-name lottery-transform-prod \
    --query 'Job.{GlueVersion:GlueVersion,Command:Command,MaxCapacity:MaxCapacity}'
{
  "GlueVersion": "3.0",
  "Command": { "Name": "pythonshell", "PythonVersion": "3.9", ... },
  "MaxCapacity": 1.0
}
```

AWS *stored* `GlueVersion: "3.0"` (which is why we keep that literal in Terraform — see
"No infra change" below) but the runtime is driven entirely by `PythonVersion: "3.9"`.

Sources:
- <https://docs.aws.amazon.com/glue/latest/dg/add-job-python.html>
- <https://docs.aws.amazon.com/glue/latest/dg/release-notes.html>

## What we changed (docs only — no infra change)

- `main.tf`: replaced the `TODO PR-020` upgrade note with the conclusion, and added an
  inline comment marking `glue_version` as inert.
- `variables.tf`: rewrote the `glue_version` / `python_version` descriptions to state the
  supported values and why `glue_version` does nothing here.
- `README.md`: a "PR-020: runtime spike" section.

No resource attribute values change. `glue_version` stays `"3.0"` deliberately — the live
job already reads back `"3.0"`, so removing or bumping the attribute would create a diff
(a churn, or an ignored-yet-mutating write) for no runtime benefit. **`terraform plan` for
the etl-glue module stays a no-op** — nothing to apply for this PR.

## If a newer runtime is ever actually needed

It is a **job-type migration**, not a version bump:

- Rewrite `loteria.transformer` from single-process pandas to **PySpark** and run it as a
  `glueetl` job on Glue 4.0/5.0 (Python 3.10+), **or** move to a **Ray** (`glueray`) job.
- New DPU/billing model (Spark clusters vs. 1 DPU Python Shell), new IAM/logging surface,
  and the parser/transform logic reworked for Spark DataFrames.
- AWS now publishes a "Migrate from AWS Glue Python shell jobs" guide, so this is the
  sanctioned long-term direction — but it is a real project, tracked as a deferred (L-)
  item, not PR-020.

## Rollback

Nothing to roll back — the change is comments and docs. Reverting the commit restores the
prior TODO wording.
