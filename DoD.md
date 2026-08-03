# Definition of Done — "Hiring Manager Ready"
**Project:** Loteria Santa Lucia de Guatemala — Serverless Data Pipeline on AWS
**Author / Owner:** Angel Hernandez
**Status:** Decisions locked — execution tracked in [`roadmap.md`](./roadmap.md) (2026-06-28)

> This document is the contract between the current state of the project and the "hiring-manager-ready" target. Decisions in §4 are now locked. The granular, PR-by-PR execution plan lives in [`roadmap.md`](./roadmap.md) — that's the file to hand to Claude Code / Codex.
>
> **Focus statement (owner):** the showcase is **Data Quality + MLOps**, *not* generic DevOps. Choices that exist purely to "look DevOps-y" (multi-env Terraform folders, complex branching, Terraform Cloud) are out. Choices that show data correctness, observability, and reproducibility are in.

---

## 1. Vision (what "done" looks like)

A reviewer (hiring manager, senior data engineer, SRE) can:

1. **Clone the repo**, set 3 environment variables, run `make bootstrap && make deploy`, and have the full pipeline running in **their own AWS account** in under 30 minutes.
2. **Read one diagram** that matches the deployed architecture exactly.
3. **Open the README** and understand the *problem*, *architecture*, *medallion layers*, *cost*, *quality gates*, and *how to run tests* — without needing to ask.
4. **Run `make test`** and see unit + integration + data-quality tests pass locally and in CI.
5. **Query Athena** and see Bronze → Silver → **Gold** business metrics.
6. **Inspect CloudWatch** and see dashboards + alarms wired to the Step Function, Glue Job, Lambda, and crawlers.
7. **Tear down** with `make destroy` without orphaning resources or losing the historical raw data (which lives in a *separate, protected* bucket).

---

## 2. Current state — observed gaps

Pulled from reading the repo today. None of this is a complaint — it's the punch list.

### 2.1 Infrastructure / Terraform
- `terraform-lottery/Prod/` is a **flat folder, no modules, no envs**. Hard to clone and re-deploy without manual edits.
- **Hard-coded ARNs / bucket names** in `iam.tf`, `glue_job.tf`, `glue_crawlers*.tf` (e.g. `lottery-partitioned-storage-prod`, `lambda-code-zip-prod`). Breaks portability.
- **No remote state backend** (S3 + DynamoDB lock). Local `terraform.tfstate` only.
- The two **core S3 buckets** (partitioned + simple) are **commented out** in `s3.tf` — they were created out-of-band and now Terraform doesn't manage them. New cloners cannot deploy.
- `secrets.tf` is **entirely commented out**. Secrets exist in AWS but are not in code.
- **Two EventBridge rules** doing the same thing (`eventbridge.tf` + `cloudwatch_event_rule.tf` / `cloudwatch_event_target.tf`). One needs to be removed.
- `null_resource` running `aws glue start-crawler` at apply time — fragile, runs on every apply, no clean way to gate.
- IAM has **wildcards** (`Resource = "*"` on Secrets Manager, Glue, Logs) — fine for a personal project, not for "production-ready".
- `temp_tf_files/` and a leftover `s3_bucket_objects_arn` variable described `"ELIMINAR ESTE BUCKET"` — leftover noise.
- `iam.tf` references two pre-existing IAM users (`santa-lucia-dev`, `angel-adming`) by name. Will fail in any other account.
- Lake Formation is acknowledged as configured **manually** in the README and `challanges_faced.md`. Not in code → not reproducible.
- No `outputs.tf` → callers don't get the bucket names, state-machine ARN, etc.
- `glue_job.tf` is locked to Glue 3.0 / Python 3.9 with a hard-coded `script_location` referencing `lambda-code-zip-prod`.

### 2.2 Application code
- **Two copies** of the same pipeline code: `lambda/` (extractor + obsolete `transformer/lambda_handler.py`) and `glue_job_transformer/` (the real transformer). Drift risk.
- `lambda/transformer/lambda_handler.py` is dead code (Glue handles transform now per `challanges_faced.md` §7). Should be deleted.
- `aws_secrets.py` has the secret name **hard-coded** (`lottery_secret_prod_2`), and parses ARNs in a fragile way (`.split(":::")[-1]`). Region also hard-coded to `us-east-1`.
- `extractor/dry_test.py` does an `import` from `scraping` (no package prefix) — only works when run from inside the folder.
- `parser.py` mixes Spanish + English comments, has leftover `print(...)` debug calls, and is not covered by tests.
- `miscellaneous/` and `modules/ETL/Prod/temp_files/` look like scratch space committed by accident (incl. `.parquet` files). Should be `.gitignore`d or removed.
- `build_lambda_package.sh` builds for the extractor only; there is no equivalent build for the Glue job zip — and **no Lambda layer** strategy (so cold starts pay the dependency cost every time).

### 2.3 Medallion layers
- **Bronze** (raw `.txt`) ✅ exists in the partitioned bucket under `raw/year=/sorteo=/`.
- **Silver** (typed Parquet) ✅ written by Glue under `silver/{sorteos|premios}/year=/sorteo=/`. Crawler exists.
- **Legacy `processed/` prefix** still being crawled by the *original* crawlers (`glue_crawlers.tf`) — but the new transformer writes to `silver/`. The two crawlers are now redundant; old ones should be deleted (without deleting the data).
- **Gold** ❌ not implemented. No business-metric tables, no aggregation job, nothing for QuickSight to consume directly.

### 2.4 Observability
- No **CloudWatch dashboard**.
- No **CloudWatch alarms** (Step Function failure, Glue Job failure, Lambda errors, crawler failure, missing weekly run).
- No **SNS topic** for alerts (e.g. email when the Monday run fails).
- No **log retention policies** on log groups (defaults to "never expire" = $).
- No **X-Ray** / structured logging. `print(...)` and `logging.info` mixed.
- No **EventBridge dead-letter queue** for missed schedules.

### 2.5 QA / Testing (this is the part you specifically want to showcase)
- **Zero automated tests** in the repo. Only `dry_test.py` smoke scripts.
- No `pytest`, no `tox`, no `coverage`, no `pre-commit`.
- No **data-quality** layer (Great Expectations / Soda / dbt tests).
- No **contract tests** for the scraper (HTML structure can change silently).
- No **integration test** that runs the Glue script against a known fixture and asserts on the resulting Parquet schema/rows.
- No **CI** workflow (GitHub Actions). No lint, no security scan (`tfsec`, `checkov`, `bandit`), no `terraform validate`/`plan` on PRs.

### 2.6 Documentation / Diagrams
- README is detailed but **stale in places** (mentions RDS being "retired", mentions "Planned" Lambda for orchestration but Step Functions are already wired).
- `aws_etl_setup.md` describes a **3-Lambda design** that is no longer the real architecture. Misleading for a reviewer.
- Diagrams exist (NAT ON/OFF, ETL workflow, Step Functions) but were made before the Silver layer and don't show: Step Functions, EventBridge, the dual-crawler setup, or Gold.
- No **ADRs** beyond `vpc-separation.md`.

### 2.7 Repo hygiene
- 12 MB of `.png` / `.jpg` assets in `images/` (some look like raw screenshots `Imagen pegada.png`). Could move to `docs/`.
- `notebooks/` is committed without `nbstripout` → noisy diffs.
- No `LICENSE` section in the README, no `CONTRIBUTING.md`, no `Makefile`.
- No language/tooling pinning at the repo root (`.python-version`, `pyproject.toml`, `Pipfile`, etc.).

---

## 3. Proposed plan — phased

Order is deliberate: **safety first** (don't lose data), then **make it reproducible**, then **make it impressive**, then **prove quality**.

### Phase 0 — Safety net (do before anything else)
- **Snapshot / inventory** the existing two production buckets (`lottery-partitioned-storage-prod`, `lottery-data-simple-prod`) so we can prove nothing was lost.
- Enable **S3 Versioning + MFA-Delete-equivalent (Object Lock or strict bucket policy)** on the partitioned bucket. Add a lifecycle rule sending raw `.txt` files older than 90 days to **Glacier Instant Retrieval** (cheap, still queryable for re-runs).
- **Import** the two existing buckets into Terraform state (`terraform import`) so they become managed without being recreated. Add `prevent_destroy = true` lifecycle rule.

### Phase 1 — Reproducible Terraform (single env)
> **Decision update:** we are *not* creating `envs/dev` + `envs/prod` subfolders. The dual-env pattern was a DevOps showcase and the owner wants the focus on Data Quality / MLOps. If we later want a `dev` deployment, we do it in a **separate AWS account** so cost can be measured cleanly (deferred decision — see [`roadmap.md`](./roadmap.md) §"Open later").

- Re-shape Terraform into **modules**: `modules/network`, `modules/storage`, `modules/iam`, `modules/etl-lambda`, `modules/etl-glue`, `modules/orchestration`, `modules/observability`, `modules/catalog`, `modules/lake-formation`.
- One root caller at `terraform/` (replaces `terraform-lottery/Prod/`) that consumes the modules with a single `terraform.tfvars`.
- Replace hard-coded ARNs/names with **data sources or module outputs**.
- Move secrets into Terraform with a **clear bootstrap script** (one-time `make secrets` that creates `scrape.do` token, etc., in Secrets Manager).
- Add **`outputs.tf`** for every module.
- Codify **Lake Formation** permissions (the manual setup from `challanges_faced.md` §5).
- Remove the duplicate EventBridge rule. Remove `null_resource` crawler starters (Step Function already starts them).
- Delete `temp_tf_files/`, the `s3_bucket_objects_arn` variable, the dead `lambda/transformer/`.

### Phase 2 — Code cleanup
- Single source of truth for ETL code under `src/` (`src/extractor/`, `src/transformer/`, `src/parser/`, `src/common/`).
- Add **`pyproject.toml`** (Poetry or uv), pin Python 3.12.
- Build artifacts via a single `Makefile` (`make build-extractor`, `make build-glue-job`).
- Introduce a **Lambda Layer** for `requests` + `beautifulsoup4` so the function code stays under 5 MB.
- Remove `print(...)` debug, switch to `logging` with a JSON formatter (CloudWatch-friendly).
- Parameterize the secret name and region (env vars, not hard-coded).
- Drop `miscellaneous/` and `modules/ETL/Prod/temp_files/` from the repo (move to `archive/` branch if you want the history).

### Phase 3 — Gold layer (this is the "wow" part for the reviewer)
Proposed business-metric tables, written by a second Glue job and registered in the catalog as `lottery_santalucia_db.gold_*`:

| Table | Grain | Why it's interesting |
|-------|-------|----------------------|
| `gold_draw_summary` | one row per `numero_sorteo` | totals: # premios, total monto pagado, % vendido vs no-vendido, top prize amount |
| `gold_winning_number_frequency` | one row per `numero_premiado` | how often each 4-digit number has won; statistical baseline vs. uniform distribution |
| `gold_terminations` | one row per last-2-digit termination | frequency of ending digits (the "terminación" superstition) |
| `gold_letters_distribution` | one row per `letras` | which letter combinations win more often |
| `gold_geo_winnings` | one row per `(departamento, ciudad)` per year | total monto + count winners per location |
| `gold_vendor_leaderboard` | one row per `vendedor` per year | top sellers by # of winning tickets & total prize money |
| `gold_time_series` | one row per `(year, month)` | monthly totals to feed QuickSight time-series charts |

Decision needed: **Glue Python Shell Job** (consistent with Silver) vs. **Athena CTAS** (cheaper, simpler, no extra IAM). Recommendation: **Athena CTAS via Step Function** — it keeps the IAM surface small and re-uses the existing crawler.

### Phase 4 — Observability
- One **CloudWatch dashboard** per env: Step Function success rate, Glue Job duration, Lambda errors, scraper HTTP status codes, S3 object counts per layer.
- **Alarms** → SNS topic → email (the owner's address, set via the gitignored `terraform.tfvars` — never committed):
  - Step Function execution failed
  - No successful run in the last 8 days (catches "the Monday cron didn't fire")
  - Glue Job duration > p95 baseline
  - Lambda 5xx / throttles
- **Log retention** = 30 days on all log groups.
- Structured JSON logs with a correlation ID per Step Function execution (passed as an env var into the Lambda + Glue Job).

### Phase 5 — QA / Testing (your highlight)
Three layers, all runnable locally and in CI:

1. **Unit tests (`pytest`)**
   - `parser.py`: feed it 5–10 real `.txt` fixtures (anonymized historical draws), assert the parsed dicts. Edge cases: missing reintegros, "NO VENDIDO", "DE ESTA CAPITAL".
   - `transformer.py`: feed it a fixture, assert resulting DataFrame schema, dtypes, partition values.
   - `s3_utils.py`: mocked with `moto`.

2. **Integration tests**
   - **Scraper contract test**: pull a known-good page via `scrape.do` (or a cached HTML fixture) and assert the selectors still find HEADER/BODY. This catches the website changing layout *before* a Monday run fails silently.
   - **End-to-end on LocalStack** (S3 + Lambda) — run extractor → run transformer → assert Parquet files appear.

3. **Data-quality tests** (Great Expectations or Soda Core)
   - Silver: `numero_sorteo` not null, monotonically increasing-ish, `monto >= 0`, `fecha_sorteo` parseable, `departamento` in a known list (the 22 Guatemalan deptos).
   - Gold: row counts within expected ranges, no nulls in key dimensions.
   - Run as the **last Step Function step**; failure → SNS alert + state machine fails (so you see it).

4. **CI (GitHub Actions)** on every PR:
   - `ruff` + `black` + `mypy` (optional)
   - `pytest --cov` (fail under 80%)
   - `terraform fmt -check`, `terraform validate`, `tflint`, `tfsec`, `checkov`
   - `bandit` for Python security
   - Build Lambda zip + Glue zip as artifacts

### Phase 6 — Documentation & diagrams
- Rewrite README: problem → architecture → how to deploy → how to test → cost → roadmap.
- Update the 4 existing diagrams in **draw.io** (`docs/diagrams/*.drawio`, committed as XML so they're diffable) and export to PNG for the README:
  1. Network (NAT ON/OFF) — keep
  2. End-to-end ETL with Step Functions, EventBridge, Glue, Crawlers, Athena, QuickSight
  3. **Medallion layers** Bronze → Silver → Gold (NEW)
  4. **Observability** (CloudWatch + SNS + alarms) (NEW)
  5. **CI/CD** (GitHub Actions → Terraform → AWS) (NEW)
- Add **ADRs** under `docs/adr/`:
  - ADR-001 VPC separation (exists)
  - ADR-002 Glue Python Shell vs. Lambda for transform (lift from §7 of `challanges_faced.md`)
  - ADR-003 scrape.do proxy with MX geo-routing
  - ADR-004 Athena CTAS for Gold (assuming we go that route)
  - ADR-005 Data-quality gating in Step Function
- Replace `aws_etl_setup.md` (it describes a design that no longer exists).

### Phase 7 — Developer experience
- `Makefile` with: `bootstrap`, `secrets`, `build`, `deploy`, `test`, `destroy`, `lint`, `fmt`, `tf-plan`.
- `README` "Quick Start" → 5 commands max.
- `.envrc.example` and a `direnv` pattern for AWS profile / region.
- `pre-commit` hooks for `ruff`, `terraform fmt`, `tfsec`.

---

## 4. Technical decisions (LOCKED)

Signed off by the owner on 2026-06-28.

| # | Decision | Chosen | Notes |
|---|---------|--------|-------|
| D1 | Gold layer engine | **Athena CTAS** via Step Function | Cheap, no extra IAM, reuses crawler. dbt deferred. |
| D2 | Terraform layout | **Modules** (no `envs/` folders) | Single root caller in `terraform/`. Multi-env, if ever needed, will be done via *separate AWS accounts* — not folders. |
| D3 | Remote state backend | **S3 + DynamoDB** in same account | No Terraform Cloud. |
| D4 | Test framework | **pytest + moto + Great Expectations** | GE is the recognizable DQ name on a resume. |
| D5 | Existing buckets | **`terraform import` + `prevent_destroy`** | Non-negotiable; Phase 0 work. |
| D6 | Secrets bootstrap | **Manual `make secrets`** | Keeps secrets out of TF state. |
| D7 | CI provider | **GitHub Actions** | Free, universal. |
| D8 | Lambda packaging | **Lambda Layer for deps + thin function zip** | Faster cold starts. |
| D9 | Notebooks | **Move to `docs/notebooks/` + render to HTML in CI** | Portfolio artifacts, clean diffs. |
| D10 | SageMaker Studio domain | **Remove from default deploy**, optional `make sagemaker` | Reduces day-1 complexity for reviewer. |
| D11 | Region | **`us-east-1`** | Matches existing data location. |
| D12 | Branching | **Stay on `master`** with PR-gated CI | Owner preference; do not rename. |

### Process decisions (also locked)
- **Granularity:** **many small PRs**, one logical change per PR. Each PR has a clear acceptance criterion and is independently revertible. Optimizes for visible GitHub activity *and* surgical review.
- **No multi-env Terraform folders.** If we ever need a non-prod environment, we deploy this exact stack into a *separate AWS account* and rely on AWS billing tags / Cost Explorer to measure each account's spend.
- **AWS profile:** owner default region is `us-east-1`. Profile name TBD — Makefile will read `AWS_PROFILE` from the environment, with a placeholder default to be filled in `.envrc` later.

---

## 5. Explicit non-goals (so we stay focused)

- **No multi-account / Control Tower / Organizations** setup. Single account, two envs (`dev`, `prod`).
- **No ML / forecasting.** The dataset is interesting *because it's clean and historical*, not because we'll train models on it (yet). Keep it as a Phase 8 "future work" bullet.
- **No real-time / streaming.** Weekly batch is the right cadence for a weekly lottery.
- **No Kubernetes / ECS.** Fully serverless is the story.
- **No QuickSight Terraform automation** (the AWS provider for QS is painful). We'll deploy QS by hand and just commit the dashboard JSON export.

---

## 6. Risks & how we mitigate

| Risk | Mitigation |
|------|-----------|
| Losing historical raw data while refactoring | Phase 0 inventory + `prevent_destroy` + S3 Versioning before any TF apply |
| Importing existing buckets into TF triggers a recreate | Use `terraform plan` extensively; import one bucket, plan, sanity-check, then the second |
| scrape.do token leaked in CI logs | Use `${{ secrets.SCRAPE_DO_TOKEN }}`, never echo, add `bandit` to CI |
| Lake Formation permissions wipe on `terraform apply` | Codify them; test in `dev` env first |
| Glue Job version pinned to 3.0 / Py 3.9 going EOL | Schedule an upgrade-to-Glue-4.0/Py3.10 spike in Phase 2 |
| Existing IAM users referenced by name (`santa-lucia-dev`, `angel-adming`) break in another account | Gate that block behind a `var.enable_personal_iam_attachments = false` default |

---

## 7. Estimated effort (rough, in focused half-days)

| Phase | Half-days |
|-------|-----------|
| 0 Safety net | 1 |
| 1 Terraform modules + envs + import | 4 |
| 2 Code cleanup + packaging | 2 |
| 3 Gold layer + Athena CTAS | 3 |
| 4 Observability | 2 |
| 5 QA + tests + CI | 4 |
| 6 Docs + diagrams + ADRs | 2 |
| 7 DevX (Makefile, pre-commit) | 1 |
| **Total** | **~19 half-days** (≈2 calendar weeks at part-time pace) |

---

## 8. Next step

Granular execution plan lives in [`roadmap.md`](./roadmap.md). It breaks each Phase into atomic, prompt-ready PRs that can be handed one at a time to Claude Code or Codex. Start with **PR-001** (repo hygiene baseline).
