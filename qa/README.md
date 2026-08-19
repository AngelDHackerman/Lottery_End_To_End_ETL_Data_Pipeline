# Data quality — Silver layer

Great Expectations project for the Silver layer (PR-032). PR-033 wires this in as a gate
between the Silver crawlers and the Gold CTAS build, so a failure here is what stops bad
data from being aggregated.

## Running it

```bash
make dq PARTITIONED_BUCKET=lottery-partitioned-storage-prod   # validate Silver
python scripts/run_dq.py --bucket <bucket> --dataset premios  # one dataset
python scripts/run_dq.py --bucket <bucket> --json-report dq.json
```

Needs AWS credentials with read access to the partitioned bucket, and `great-expectations`
installed (`pip install -e '.[dq]'`, or `pip install -r requirements/dq.txt`). It reads only.

Exit codes, which PR-033 depends on:

| Code | Meaning |
|------|---------|
| 0 | every expectation passed |
| 1 | an expectation failed — the data is wrong |
| 2 | no Parquet found — wrong bucket/prefix, or the transformer never ran |
| 3 | usage error (no bucket given) |

`2` is deliberately separate from `1`: "there is no data" and "the data is bad" need
different responses, and a zero-row dataset would otherwise be reported as a quality failure.

## Where things live

| Path | Role |
|------|------|
| `src/loteria/dq/suites.py` | **source of truth** — the expectations, in Python |
| `src/loteria/dq/runner.py` | loads Silver Parquet from S3 and validates it |
| `scripts/run_dq.py` | CLI + `--sync-suites` |
| `qa/great_expectations/expectations/*.json` | **generated** — the contract, readable without running anything |

## Changing an expectation

Edit `src/loteria/dq/suites.py`, then:

```bash
make dq-sync    # regenerates the JSON below
```

and commit the result. `tests/unit/test_dq_suites.py` fails if the two ever disagree, so a
forgotten sync cannot leave a committed contract that says something the pipeline no longer
enforces.

Do not hand-edit the JSON. It is overwritten on the next sync.

## Two things that will look like bugs

**`ALTA VERAPÁZ` and `BAJA VERAPÁZ` are misspelled on purpose.** loteria.org.gt writes them
with an accent that does not belong on "Verapaz", and the value set has to describe what the
site emits — the expectation exists to notice when the *source* changes. Correcting the
spelling breaks the check against every real batch. A test guards this.

**`departamento` has no not-null expectation.** About 91% of premios rows have no geography,
because most prizes have no `VENDIDO POR` line. GX column-map expectations skip nulls, so the
value set applies only to the rows that have one.

## Adding a dataset

Add a builder to `SUITE_BUILDERS` in `suites.py` and an entry to `DATASET_SUITES` in
`runner.py`. Both the sync and the drift test iterate those registries, so nothing else needs
touching.
