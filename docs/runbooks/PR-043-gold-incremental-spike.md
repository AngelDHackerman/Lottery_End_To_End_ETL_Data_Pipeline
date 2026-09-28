# PR-043.1 — Gold rebuild spike: keep the full rebuild

**Verdict: keep the full weekly rebuild for all seven Gold tables. Do not build the
incremental machinery.** The roadmap allows this outcome explicitly ("*'Keep the full
rebuild' is a valid verdict per table*"), and the numbers below are what make it the right
one rather than the lazy one.

The short version, measured against the live account on 2026-09-27:

| | |
|---|---|
| Bytes scanned by all 7 CTAS, one run | **5,076,040** (4.84 MiB) — 1.86× the entire Silver layer |
| Growth per draw | **~36.6 KB** scanned, measured over four consecutive weekly runs |
| Billed bytes per run | **70 MiB** — because Athena charges a **10 MiB minimum per query**, and 7 of 7 tables are under it |
| Athena cost | **$0.00037 per run · $0.019 per year** (52 runs, at $5 per TB scanned) |
| Same cost at 10× Silver | **$0.019 per year** — the floor absorbs the growth |
| `BuildGold` stage, wall clock | **179 s**, of which **16.3 s (9.1%)** is Athena executing |

Fault C is real as a *design* observation — the work scales with history, not with arrivals,
and that is measurable and monotone. It is not real as a *cost* defect, and the reason is
not "it is cheap today": it is that the per-query minimum is 2× the whole workload, so
**bytes saved are not dollars saved at any scale this project will reach by waiting.**

---

## 1. Method, and what it cannot see

Athena records `DataScannedInBytes` and timing per query execution. The whole history of the
`lottery-wg` workgroup was pulled read-only and grouped by run:

```bash
# every execution id the workgroup still retains (paginate NextToken)
aws athena list-query-executions --work-group lottery-wg --max-results 50

# statistics, 25 ids at a time
aws athena batch-get-query-execution --query-execution-ids <id> [<id> ...] \
  --query 'QueryExecutions[].{q:Query,b:Statistics.DataScannedInBytes,
           ms:Statistics.TotalExecutionTimeInMillis,t:Status.SubmissionDateTime}'
```

**The limitation, stated up front: the API window held 64 executions, spanning
2026-08-27 → 2026-09-27.** That is four untouched weekly runs plus six manual runs from the
PR-031.3 / PR-042 / PR-045.1 work. There is no longer-baseline available — Athena's query
history is not archived anywhere, which is itself worth knowing: **any future re-measurement
must be taken within ~45 days of the runs it describes.** Four consecutive weekly runs are
enough for a growth rate because the series is monotone and the deltas agree to within 1%.

No query was run for this spike. The measurement is entirely read-only metadata about
queries the pipeline had already run, so it cost nothing and changed nothing.

## 2. The growth is real, monotone, and tiny

Four consecutive weekly runs, before PR-042 renamed the tables to staged generations. One
draw arrived between each pair.

| table | 08-27 | 09-03 | 09-10 | 09-17 | bytes per draw |
|---|---|---|---|---|---|
| `gold_draw_summary` | 1,064,983 | 1,073,026 | 1,080,985 | 1,089,025 | **+8,014** |
| `gold_time_series` | 807,219 | 813,321 | 819,418 | 825,524 | +6,102 |
| `gold_terminations` | 774,336 | 780,147 | 785,953 | 791,768 | +5,811 |
| `gold_winning_number_frequency` | 774,336 | 780,147 | 785,953 | 791,768 | +5,811 |
| `gold_geo_winnings` | 705,560 | 710,974 | 716,071 | 721,455 | +5,298 |
| `gold_vendor_leaderboard` | 591,427 | 595,907 | 600,204 | 604,656 | +4,410 |
| `gold_letters_distribution` | 155,185 | 156,397 | 157,515 | 158,645 | +1,153 |
| **total** | **4,873,046** | **4,909,919** | **4,946,099** | **4,982,841** | **+36,598** |

Two things fall out of the table that are not in the roadmap:

- **`gold_terminations` and `gold_winning_number_frequency` scan byte-identical amounts, in
  every run.** Both read exactly `numero_premiado` from `silver_premios_premios`; the
  difference is only in the `GROUP BY`. A shared intermediate would halve one of them —
  and halving 0.8 MiB of a 10 MiB minimum buys nothing. Recorded so nobody "optimises" it.
- **The scan per run is 1.86× the whole Silver layer** (Silver: 236 objects, 2,725,997 bytes,
  118 sorteos + 124,447 premios rows). Seven CTAS reading two tables scan less than two full
  copies of the layer, because Parquet column projection already does most of the work an
  incremental rewrite is supposed to do.

## 3. Why bytes are not dollars here: the 10 MiB floor

Athena bills data scanned, **rounded up, with a 10 MiB minimum per query**, at $5 per TB.
Every one of the seven CTAS is an order of magnitude under that minimum, so the *billed*
figure is flat at 7 × 10 MiB regardless of what the queries actually read:

| | scanned | billed | $/run | $/year (52 runs) |
|---|---|---|---|---|
| today | 4.84 MiB | 70.0 MiB | $0.000367 | **$0.0191** |
| 2× Silver | 9.68 MiB | 70.0 MiB | $0.000367 | $0.0191 |
| 10× Silver | 48.4 MiB | 70.6 MiB | $0.000370 | $0.0192 |

At 10× Silver **six of the seven tables are still under the minimum**; only
`gold_draw_summary` (11.1 MiB) crosses it. The full rebuild's entire annual Athena bill is
**under two cents, and stays under two cents at ten times the data.**

**The incremental rewrite would not reduce this, and could increase it.** Every Athena
statement carries its own 10 MiB floor, and the plan at PR-043.2 needs *more* statements
than the CTAS it replaces: an `INSERT INTO` per table, plus the idempotency read the plan
itself mandates (`MAX(numero_sorteo)` / the set of years present — "*idempotency comes from
querying the target*"). Each of those reads is another minimum-billed query. Trading one
1.1 MiB query for two 10 MiB-floored ones is a cost *regression* dressed as an optimisation.

## 4. Runtime: the stage is 91% orchestration

From the `verify-045-1-044-1-1790540548` execution (2026-09-27, SUCCEEDED, 9m17s end to end):

| stage | wall clock |
|---|---|
| `RunExtractorLambda` | 15 s |
| `RunTransformerGlueJob` | 66 s |
| silver crawlers (start + poll) | 122 s |
| `RunSilverDQ` | 175 s |
| **`BuildGold` (Map, MaxConcurrency 3)** | **179 s** |

Inside those 179 s the Map ran 7 `RunCTAS` tasks **and 21 Lambda invocations** (`PrepareGold`,
`PromoteGold`, `RetireGold`, one each per table). Athena's own execution time summed to
**16.3 s — 9.1% of the stage.** Per-query execution across the four weekly runs was
1.6–7.0 s with no visible trend, which is expected: scanned bytes grew 2.3% over that month
while per-query times varied by 3×, so the signal is fixed overhead and noise, not scanning.

That reframes the performance argument completely. **An incremental rebuild optimises 9% of
the stage and leaves the 91% — Step Functions transitions, three Lambda cold-ish starts per
table, and Athena's own queue/planning time — exactly where it is.** A rewrite that removes
scanning cannot make `BuildGold` meaningfully faster; it can only make it more complex.

## 5. Projection: 2× and 10× Silver are 3 and 24 years away

The scan is linear in Silver rows (columnar, no indexes, no data skipping beyond partition
pruning that the Gold reads do not use). Silver grows by **895 rows per draw** (1 sorteo +
~894 premios), one draw per week:

| | Silver rows | when, at 1 draw/week | total scan | billed/year |
|---|---|---|---|---|
| today | 124,565 | — | 4.84 MiB | $0.0191 |
| 2× | 249,130 | ~139 draws ≈ **2.7 years** (≈2029) | 9.68 MiB | $0.0191 |
| 10× | 1,245,650 | ~1,253 draws ≈ **24 years** (≈2050) | 48.4 MiB | $0.0192 |

For the rebuild to cost even **$1/year** the run would have to scan ~3.8 GB — **about 760× today's
volume, roughly 2,000 years of weekly draws.**

**The honest caveat: the realistic trigger is a scope change, not time.** Ten times the data
by waiting is absurd; ten times the data by *backfilling* — importing decades of historical
draws, or adding a second lottery — is a normal Tuesday. That is the scenario to watch, and
it arrives as a decision someone makes, not as a gradual drift. It is also the scenario in
which this spike should simply be re-run: the commands in §1 are the whole method.

## 6. The three-group classification, verified against `GROUP BY`

The roadmap asked for this to be checked against each file's `GROUP BY` "rather than against
its name". It holds — all seven:

| file | `GROUP BY` | roadmap group | verdict |
|---|---|---|---|
| `01_gold_draw_summary` | `s.numero_sorteo, s.tipo_sorteo, s.fecha_sorteo` | append-only grain | ✅ grain **is** the arrival unit |
| `05_gold_geo_winnings` | `p.departamento, p.ciudad, YEAR(s.fecha_sorteo)` | current-year partition | ✅ `year` in the grain |
| `06_gold_vendor_leaderboard` | `p.vendedor, YEAR(s.fecha_sorteo)` | current-year partition | ✅ `year` in the grain |
| `07_gold_time_series` | `YEAR(s.fecha_sorteo), MONTH(s.fecha_sorteo)` | current-year partition | ✅ `year` in the grain |
| `02_gold_winning_number_frequency` | `p.numero_premiado` | global aggregate | ✅ every row depends on all history |
| `03_gold_terminations` | `LPAD(CAST(p.numero_premiado % 100 AS VARCHAR), 2, '0')` | global aggregate | ✅ |
| `04_gold_letters_distribution` | `p.letras` | global aggregate | ✅ |

**One correction to how the roadmap phrases the first group.** It calls those three "already
partitioned by `year`" — which describes the **output**, not the scan. The measurement shows
all three grow every single week (`+6,102`, `+5,298`, `+4,410` bytes per draw), because
`partitioned_by = ARRAY['year']` prunes nothing on the *read* side: the `SELECT` still joins
both Silver tables in full. Output partitioning is what would make `INSERT INTO` a single
year cheap *if* it were built; it is not something already saving bytes today.

## 7. Two of the roadmap's four arguments are now retired

Fault C's section gives four reasons the full rebuild matters. After the measurement:

- *"The work scales with history, not with arrivals"* — **confirmed, and quantified**:
  +36.6 KB scanned per draw, monotone, against a constant one-draw input. This is the one
  argument that survives intact, and it is a design observation, not a cost.
- *"It compounds fault B — the longer the rebuild, the longer each table sits empty"* —
  **retired by PR-042.** Gold is built beside the live generation and swapped atomically; no
  table is empty for any part of the rebuild, so its duration no longer has a correctness
  cost.
- *"The single largest recurring query cost in the project"* — **false, and it was never
  checked.** It is $0.019 a year. The project's largest recurring compute cost is the DQ
  gate's Glue start-up (~21 min in its worst observed case, PR-033.1), which is tracked as
  Open later **L7**.
- *"It is the thing a reviewer will ask about"* — **true, and this document is the answer.**
  "Why do you recompute 2024 every week?" now has a numeric reply: because the query that
  recomputes it scans 1.1 MiB and bills the 10 MiB minimum either way, and the alternative
  needs two minimum-billed statements to save 1 MiB.

## 8. What would change the verdict (the tripwires)

Do not revisit this on a feeling. Any one of these is a real signal, and each is a number
that the existing tooling already produces:

1. **`gold_draw_summary` scans more than 10 MiB** (`DataScannedInBytes` in the query
   history). It is the largest scanner and the first table for which a saved byte becomes a
   saved cent. ~9.5× Silver, ~23 years of organic growth — or one backfill.
2. **The `BuildGold` Map exceeds ~10 minutes of wall clock**, or any single `RunCTAS` exceeds
   60 s. Today: 179 s and ≤7 s. This is the axis that would hurt first, and note that
   crossing it does *not* on its own imply incremental — check §4's split first, because
   orchestration overhead is the likelier culprit.
3. **The arrival rate or the history changes by design** — a historical backfill, a second
   lottery, daily draws. This is the trigger that actually plausibly fires.

When one does fire, the plan is already written at **PR-043.2 / .3**, deferred as **Open
later L8**. The part not to lose, repeated here so it survives this document too:
**`INSERT INTO` collides with PR-042's generations** — writing into a published generation
writes into live data. Either the generation becomes copy-then-append, or the incremental
tables opt out of the generation mechanism with a stated reason. That has to be resolved in
writing before any SQL changes.

## 9. What this PR changed

Documentation only. No SQL, no Terraform, no Python, no behaviour:

- this runbook,
- a pointer in `sql/gold/README.md`, so the decision is visible where someone reads the
  queries rather than only in a runbook they may not know exists,
- `roadmap.md`: PR-043.1's outcome and the tracker row.

Deliberately **not** added: a script for the measurement. It would be code with exactly one
caller — this document — and the repo already treats that as a defect. The four commands in
§1 are the method; git has this file if the numbers are ever needed again.

**Rollback:** nothing to roll back. Reverting the commit removes three documents.
