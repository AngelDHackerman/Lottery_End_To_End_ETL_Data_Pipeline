# Lottery data pipelines on AWS: Santa Lucía (Guatemala) and DNLQ (Uruguay)

A serverless ETL pipeline that scrapes the results of **Lotería Santa Lucía**, Guatemala's
largest lottery, every week and builds the only historical dataset of its draws: raw pages,
typed Parquet and query-ready aggregates in S3, with a data-quality gate that blocks bad data
before it reaches the tables people query. Everything is Terraform, and every claim below was
checked against the deployed account, not against the documentation. A second pipeline in the
same repository does the same for Uruguay's official draws
([Uruguay extension](#uruguay-extension-dnlq)).

**Start here: the [interactive architecture diagram](https://angeldhackerman.github.io/Lottery_End_To_End_ETL_Data_Pipeline/)** ([source](./layouts/diagram.html)).
Click any component for its real AWS resource names and its state, or replay the weekly run
step by step.

## Contents

1. [Why it exists](#why-it-exists)
2. [Quick start](#quick-start)
3. [Architecture](#architecture)
4. [Data quality](#data-quality)
5. [Observability](#observability)
6. [Tests](#tests)
7. [Cost](#cost)
8. [Uruguay extension (DNLQ)](#uruguay-extension-dnlq)
9. [Roadmap and future work](#roadmap-and-future-work)
10. [Decisions](#decisions)
11. [Analysis](#analysis)

## Why it exists

Lotería Santa Lucía was founded in 1956, and its website shows only the latest draws. Once a
draw leaves the page, its results are gone: the alternatives are old printed newspapers, some
Facebook videos (since 2018) or paid PDFs from Guatemala's national newspaper archive. No
public dataset exists, on Kaggle or anywhere else, and no audit of the lottery is possible
without one.

This pipeline captures each draw while it is still online and keeps it. On 2026-10-22 the lake
held 121 draws and 127,837 prize rows.

## Quick start

You need an AWS account, Terraform, Python 3.12 and a [scrape.do](https://scrape.do) token
(the lottery's site sits behind Cloudflare and only answers through a proxy).

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev,dq]"
make bootstrap    # the remote Terraform state (S3 bucket + lock table)
cp terraform/backend.hcl.example terraform/backend.hcl && cp terraform/terraform.tfvars.example terraform/terraform.tfvars
make secrets      # the one secret: the bucket name and the scrape.do token
make deploy       # build the artifacts, terraform apply, upload the Glue code
```

Edit the two copied files before `make secrets`: the state bucket goes in `backend.hcl`, and
your alert e-mail in `terraform.tfvars`. After the deploy, confirm the SNS subscription from
the e-mail AWS sends, or no alarm will reach you.

This stack was built by importing a pipeline that was already running, so it has not yet been
deployed into an empty account from scratch. Expect to adjust something on a first deploy.

Every target is documented in the [`Makefile`](./Makefile).

## Architecture

One S3 bucket, three layers, one state machine. EventBridge starts the Step Functions state
machine `lottery-etl-pipeline-prod` every Thursday at 18:00 UTC:

| Step | What runs | What it does |
|---|---|---|
| Extract | Lambda (Python 3.12) | Fetches the results page through the proxy and stores one `.txt` per draw in `raw/year=<YYYY>/sorteo=<N>/`. Skips draws already in Silver. Proxy errors (429, 5xx) are retried after 5, 15 and 35 minutes |
| Transform | Glue Python Shell job | Splits header and body, types every column and writes Parquet to `silver/sorteos/` and `silver/premios/`. Rows the parser cannot read go to `quarantine/`, counted and classified |
| Catalog | Two Glue crawlers | Register the new partitions. The table schemas themselves live in Terraform |
| Validate | Glue 5.0 job with Great Expectations | The quality gate. If it fails, Gold is not rebuilt and an alert is sent |
| Gold | Lambda and Athena CTAS | Builds seven aggregate tables next to the published ones, swaps them in with one catalog update, then retires old generations |

| Layer | Prefix | Contents |
|---|---|---|
| Raw | `raw/` | The scraped text, byte for byte |
| Silver | `silver/` | Typed Parquet, partitioned by `year` and `sorteo`, with lineage columns (`run_id`, `ingested_at`). The source of truth |
| Gold | `gold/` | Seven Athena tables ([`sql/gold/`](./sql/gold/)): draw summary, winning-number frequency, terminations, letters, geography, vendors and a time series |

Lake Formation and IAM both guard the data, and a bucket policy denies every delete except to
the account root and the one role that retires old Gold generations.

The pipeline runs entirely outside the VPC. A network module is still deployed with NAT off,
but nothing uses it.

The infrastructure is in [`terraform/`](./terraform/), split into modules (`storage`,
`network`, `iam`, `etl-lambda`, `etl-glue`, `catalog`, `orchestration`, `lake-formation`,
`observability`). The code is in [`src/loteria/`](./src/loteria/).

## Data quality

Two checks work together, one before the weekly run and one inside it.

- **The scraper canary** ([`scraper-canary.yml`](./.github/workflows/scraper-canary.yml)) runs
  in GitHub Actions every Wednesday, the day before the pipeline. It fetches the live site
  through the proxy and checks that the page still has the shape the parser expects. If the
  site or the proxy changed, it opens an issue a day ahead of the real run.
- **The gate** runs inside the state machine, after Silver is written and before Gold is
  built. It validates the whole Silver layer with Great Expectations: 29 expectations over
  the two tables, including that every prize points to a draw that exists. A failure stops
  the run, leaves last week's Gold published and sends an alert.

The expectations were profiled from the real data first, and the suites are generated from
code ([`src/loteria/dq/suites.py`](./src/loteria/dq/suites.py)) into
[`qa/great_expectations/`](./qa/great_expectations/). A test fails if the two drift apart.
`make dq` runs the same gate from a laptop against the bucket.

Bad rows are never dropped silently. The transformer counts and classifies everything it
rejects, and stores the rows that matter in `quarantine/`. An alarm fires on the one class
that signals a real change in the source.

## Observability

- **Dashboard:** `loteria-pipeline-prod` in CloudWatch.
- **Logs:** every log group is declared in Terraform with a retention period. The execution
  name travels from Step Functions into the Lambda and Glue logs as a correlation id, and
  into Silver as `run_id`.
- **Alarms:** nine, all to one SNS topic.

| Alarm | Fires when |
|---|---|
| `loteria-sfn-execution-failed-prod` | A run of the state machine fails |
| `loteria-sfn-no-success-7d-prod` | A week passes without a successful run |
| `loteria-extractor-errors-prod` | The extractor Lambda errors |
| `loteria-scrapedo-failed-prod` | The proxy returns an HTTP error |
| `loteria-glue-transform-failed-prod` | The transform job fails |
| `loteria-crawler-start-failed-prod` | A crawler cannot be started |
| `loteria-quarantined-unrecognised-prod` | The parser meets a line it does not recognise |
| `loteria-quarantine-write-failed-prod` | A quarantined row could not be stored |
| `loteria-gold-retention-failed-prod` | Old Gold generations could not be retired |

A failed quality gate sends its own alert from inside the state machine.

## Tests

```bash
make test    # pytest with coverage; fails under 98 %
make lint    # ruff and terraform fmt, exactly as CI does
```

CI ([`ci.yml`](./.github/workflows/ci.yml)) runs both on every pull request, plus
`terraform validate`, checkov against a baseline, bandit, and a reproducible-build check: the
Lambda layer must come out byte-identical from its lock file. AWS is mocked with moto, so the
suite needs no credentials.

## Cost

**About $3 a month in AWS for both pipelines.** This is an estimate from public prices, not a
figure read from a bill. Nothing runs between executions, so compute is billed for a few
minutes a week (Santa Lucía) or a night (Uruguay).

| What | Approximate monthly cost |
|---|---|
| CloudWatch alarms (14, at $0.10 each) | $1.40 |
| Glue crawlers (two a week, billed a 10-minute minimum each) | $0.60 |
| Uruguay's nightly validation job in Glue (2 DPUs for about 80 billed seconds, at $0.44 per DPU-hour) | $0.60 |
| Secrets Manager (one secret) | $0.40 |
| Santa Lucía's weekly Glue jobs | $0.10 |
| Lambda, Step Functions, Athena, S3, DynamoDB | cents |

Three details behind those numbers:

- **Athena:** rebuilding all seven Gold tables scans 4.84 MiB per run. With Athena's 10 MiB
  minimum per query, that is about $0.02 a year, and it stays there at ten times the data
  ([measured in PR-043.1](./sql/gold/README.md)).
- **Proxy:** about 175 of the 1,000 scrape.do credits in the monthly plan, counting the
  weekly run and the canary.
- **Network:** $0 with `enable_internet = false`, the default. Turning the NAT gateway on
  costs about $32 a month and the pipeline does not need it.

## Uruguay extension (DNLQ)

The same repository also ingests the official draws of Uruguay's **Dirección Nacional de Loterías
y Quinielas** (`www.loteria.gub.uy`): **5 de Oro** (with Revancha), **Quiniela** (Vespertina and
Nocturna) and **Tómbola**. It is a second pipeline with its own code, data prefix and Terraform
stack, so nothing in the Santa Lucía pipeline depends on it. Like the rest of the project, it is
about ingesting an undocumented source, backfilling it and checking its quality. It does not try
to predict anything.

| | Santa Lucía (Guatemala) | Uruguay (DNLQ) |
|---|---|---|
| History | Only the latest draw is online, so the lake grows from the first scrape | The site keeps every day since 2006: about 13,000 draws backfilled |
| Schedule | Weekly | Nightly at 23:30 `America/Montevideo` |
| Access | Through a scraping proxy (Cloudflare) | Direct, at one request per second with an identifiable User-Agent |
| Code | `src/loteria/` | `src/sorteos/core/` (country-agnostic) and `src/sorteos/uy/` |
| Infrastructure | `terraform/` | `terraform/uy/` (separate state) |
| Data | `raw/`, `silver/`, `gold/` | `uy/raw/`, `uy/silver/`, `uy/gold/` in the same bucket, database `lottery_uy_db` |

### How it runs

An EventBridge Scheduler starts the Step Functions state machine `lottery-uy-pipeline-prod` every
night:

1. **Fetch** (Lambda). Asks the site only for what is new or still open and stores the pages
   byte for byte in `uy/raw/`. A DynamoDB table (the manifest) records what each page showed, so
   a page that has settled is never requested again.
2. **Silver** (Lambda, container image). Parses the results page and the per-draw extract,
   compares the two sources field by field, and rewrites the Parquet files of the years that
   changed. A draw that does not parse goes to a quarantine table, not to the data.
3. **Validate** (Glue 5.0 job). Great Expectations runs over the whole silver layer. A failed
   suite fails the execution.
4. **Gold** (Lambda). Six Athena tables are built next to the published ones and swapped in
   together only if all six have rows.

Draws that should have happened and did not are detected from the site's own "next draw"
announcements and written to a `draw_gaps` table. CloudWatch alarms cover a failed run, an open
gap, quarantined rows, fetch errors and two days without a successful run.

### Privacy decision

Under some draws the site links PDF files named `*_DET_INVALIDAS_*`. They list cancelled
telephone bets and include a column that appears to hold national identity numbers (cédulas).
Uruguay has a personal data protection law, **Ley N.º 18.331**. This project draws no legal
conclusion about those files or about the site. It simply does not touch them:

- Any URL that matches `DET_INVALIDAS` is **never requested, downloaded, parsed, stored or
  logged**. The HTTP client refuses it before the request leaves, including when a redirect ends
  there, and logs only the pattern, not the URL.
- The rule lives in code (`src/sorteos/uy/privacy.py`), not in configuration, so a mistake in a
  YAML file cannot switch it off. The client cannot be built without a blocklist.
- Tests fail if a request matches the pattern, and a scanner fails the build if a test fixture
  contains such a link or an identity-number column. Fixtures are redacted with
  `scripts/uy_redact_fixture.py` before they are committed.
- Winning coupon numbers do not identify a person, but they are kept in the raw layer only. The
  silver layer stores how many coupons won each prize, and the committed fixtures carry fake
  coupon numbers.

We found no terms of use, legal notice or privacy policy on the site (checked on 2026-10-14; see
Q9 in the findings below).

### Where to read more

- [`layouts/diagram-uruguay.html`](./layouts/diagram-uruguay.html): an interactive diagram of the
  nightly run and of what the two pipelines share. It opens in any browser, with no server.
- [`roadmap-uruguay.md`](./roadmap-uruguay.md): the plan, PR by PR, with what each one measured.
- [`docs/uruguay/FINDINGS.md`](./docs/uruguay/FINDINGS.md): what the exploration of the site found.
- [`docs/uruguay/DESIGN.md`](./docs/uruguay/DESIGN.md): the design decisions and why.
- [`sql/uy/gold/`](./sql/uy/gold/): the gold tables and the metrics behind them.
- Runbooks: [`UY-044-gold.md`](./docs/runbooks/UY-044-gold.md) and
  [`UY-045-alarmas.md`](./docs/runbooks/UY-045-alarmas.md).

These documents are written in Spanish.

## Roadmap and future work

The work was planned and tracked one pull request at a time in [`roadmap.md`](./roadmap.md),
with [`DoD.md`](./DoD.md) as the definition of done. Each PR section there ends with an
**Outcome** that says what was measured, not only what was built.

Deferred on purpose (the "Open later" table in the roadmap): separate AWS accounts for dev and
prod, dbt on Athena, a forecasting feature, QuickSight as code, Iceberg for Silver, moving the
transform off Glue Python Shell, and incremental Gold. For Uruguay: more games, more
countries, and prize pools adjusted for inflation.

**Next, and last: the ML phase,** planned in [`roadmap-ml.md`](./roadmap-ml.md) (in Spanish). It
asks whether the draws can be told apart from chance, and looks for anomalies in the draws and
around them (prize pools, sellers, prizes sold). It does not try to predict numbers. Uruguay
goes first, with local statistics before any new infrastructure, then Amazon SageMaker.

## Decisions

Six decisions shaped the project. Each links to where it was made and why.

| Decision | Why | Where |
|---|---|---|
| The pipeline runs outside the VPC | Lambda, Glue, Athena and S3 reach each other over AWS-managed paths. A VPC would add interface endpoints and cost, and protect nothing here | [`vpc-separation.md`](./vpc-separation.md) |
| Glue, not Lambda, for the transform | pandas and pyarrow did not fit comfortably in a Lambda package | [`docs/challenges.md`](./docs/challenges.md), section 7 |
| A scraping proxy (scrape.do) | The site is geo-restricted and behind Cloudflare. The proxy profile that works has changed twice, so it is treated as a live negotiation, with a canary | [`docs/challenges.md`](./docs/challenges.md), section 6, and PR-031 in the roadmap |
| Athena CTAS for Gold, rebuilt in full | Measured, not assumed: the full rebuild costs cents a year, and an incremental version would cost more | [`sql/gold/README.md`](./sql/gold/README.md) |
| The quality gate blocks the run | A gate that only warns lets bad data reach Gold. It was proven in both directions in production | [`docs/runbooks/PR-033-dq-gate.md`](./docs/runbooks/PR-033-dq-gate.md) |
| One AWS account | Two accounts are the better design and are deferred until there is a reason to pay for them | [`DoD.md`](./DoD.md), section 4 |

The runbooks in [`docs/runbooks/`](./docs/runbooks/) record every migration and every defect
that only appeared when the pipeline ran for real.

## Analysis

- [Insights from the 2024 – January 2025 draws](./eda_2024-01_2025.md), with the notebooks in
  [`notebooks/`](./notebooks/).
- [Challenges faced and how they were overcome](./docs/challenges.md).

Licensed under the [MIT License](./LICENSE).
