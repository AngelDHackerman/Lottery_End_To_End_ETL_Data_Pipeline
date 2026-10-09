# PR-049 — The DQ gate checks referential integrity

**Filed in PR-032's outcome as "the one high-value check missing".** Built 2026-10-09.
**Deploy on Thursday 2026-10-15, after that day's scheduled run has finished and verified
PR-047/048.** That way the 10-15 run judges those two alone and the first run carrying this
gate is 2026-10-22.

---

## 1. The defect

Nothing asserted that every `premios.numero_sorteo` exists in `sorteos`. A premio whose
sorteo row was rejected, or never written, passed the gate and reached the seven gold
tables. There it either vanished from a join or showed up as a draw with no date. Each
dataset's suite only looked at its own frame, so the gate could not see the gap between
them.

## 2. The fix

The value set is "the sorteos present in this Silver", which is known only at run time. So
the rule cannot live in the static suite, which is synced to
`qa/great_expectations/expectations/*.json` and drift-tested. A committed list of 119 draw
numbers would be wrong a week later.

| Piece | Where | What |
|---|---|---|
| `referential_expectations(sorteo_numbers)` | `dq/suites.py` | `ExpectColumnValuesToBeInSet(column="numero_sorteo", value_set=<distinct sorteos, sorted ints>)` |
| `REFERENCES = {"premios": ("sorteos", "numero_sorteo")}` | `dq/runner.py` | child → (parent, key) |
| `run_dq` | `dq/runner.py` | loads every selected dataset **plus any parent it needs**, then validates; the premios validation gets the run-time expectation appended |
| `validate_dataframe(..., extra_expectations=)` | `dq/runner.py` | appends run-time rules for one validation, rebuilding through the constructor (not `add_expectation`, which needs an ambient GX context) |

**Why `be_in_set` and not an anti-join count.** GX reports the offending values itself
(`partial_unexpected_list`), so the verdict line and the SNS alert name the orphan sorteo
numbers instead of only a count. For example:
`silver_premios.numero_sorteo: expect_column_values_to_be_in_set [2 rows]`, with `e.g.
[3048, 3048]` in the job log.

**A premios-only run still applies it.** `run_dq(datasets=["premios"])` loads sorteos
anyway. If sorteos is missing, the run raises `SilverDatasetEmpty` (exit "no data")
instead of passing a gate it never applied.

**Not done, deliberately:** the reverse direction (a sorteo with no premios). It was not in
the roadmap's scope. Today it would show up as a draw with zero rows in the gold tables
rather than a wrong number, and it needs its own threshold decision. File it if wanted.

## 3. Both directions, as PR-033 did

**Green on real Silver, before any test was written.** `scripts/run_dq.py --bucket
lottery-partitioned-storage-prod` from a checkout, 2026-10-09 (read-only: the gate only
reads S3):

```
[PASS] silver_sorteos: 15 expectations, 119 rows from 119 files
[PASS] silver_premios: 14 expectations, 125337 rows from 119 files

DQ RESULT: PASS
```

Premios went from 13 to 14 expectations, and the gate stays green, so it is not red on
arrival. It is also green on real transformer output: `TestAgainstRealTransformerOutput`
runs the transformer over the three fixture draws, which cover both numbering sequences
(ordinario 3046/3132, extraordinario 413).

**Red on an orphan.** `TestReferentialIntegrity` seeds sorteo 3046 and a premios file for
3048:

- The gate fails, and the check reports `unexpected_count 2`, `partial_unexpected [3048, 3048]`.
- **It is the only failure.** Every other premios expectation passes on that file, so this
  rule is the one doing the catching.
- The sorteos suite stays green.
- The alert summary names the check.

**Mutation-checked:** with `referential_checks()` returning `[]`, six tests fail.

Three existing tests had been putting a premio for 3047 next to only sorteo 3046. They now
seed sorteo 3047 too, so each still fails for the one defect it is about and not also
for an orphan. `--sync-suites` leaves `qa/` unchanged: the static suite did not move.

520 tests, ruff clean.

## 4. Apply — Thursday 2026-10-15, after the run

```bash
make deploy
```

Plan measured read-only on 2026-10-09 after `make build`: **`0 to add, 3 to change, 0 to
destroy`**, all known churn: `lambda_package` + the extractor (the zip ships all of
`loteria/`), and the `gold_purge` phantom. **The change is not in the plan.** It ships in
`loteria_dq_lib.zip`, uploaded by `make upload-glue` (the third step of `make deploy`). A
bare `terraform apply` leaves the old gate running. A `destroy` on anything means STOP.

## 5. Verify

```bash
# 1. The deployed DQ library carries the check.
aws s3 cp --quiet s3://lambda-code-zip-prod/loteria_dq_lib.zip /tmp/dq.zip
unzip -p /tmp/dq.zip loteria/dq/runner.py | grep -n "REFERENCES = \|def referential_checks"
# expect: both lines

# 2. Optional, free and immediate: run the same gate from a checkout against prod Silver.
#    It only reads S3, so it is safe at any time.
python scripts/run_dq.py --bucket lottery-partitioned-storage-prod
# expect: silver_premios with 14 expectations, DQ RESULT: PASS
```

Then the scheduled run of **Thursday 2026-10-22** is the first to use it:

```bash
aws logs filter-log-events --log-group-name /aws-glue/jobs/loteria-silver-dq-prod \
  --filter-pattern '"silver_premios"' \
  --start-time $(( ($(date +%s) - 7200) * 1000 )) --query 'events[].message' --output text
# expect: [PASS] silver_premios: 14 expectations, … rows from 121 files (119 + 3139 + 3140)
```

## 6. Rollback

`git revert` + `make deploy`. The gate reads Silver and writes nothing, so a rollback never
touches data. If the check ever goes red on a real draw, **read it before rolling back**:
an orphan premio is exactly the defect this exists to stop reaching Gold, and the previous
Gold stays intact while the gate is red.
