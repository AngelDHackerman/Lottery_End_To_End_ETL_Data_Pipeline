# Does anything read `lottery-data-simple-prod`?

**Taken 2026-09-20, read-only, before PR-041.1 gated the writes.** The roadmap requires this
evidence *before* the flag, not after, because "nothing reads it" is the entire justification
for fault A — and it is a claim about the world, not about the code.

**Answer: nothing in this system reads it, and nothing has read it through Athena in the
45 days the query history covers. What cannot be ruled out is a human with console access
downloading a file.** That gap is why PR-041.3 keeps a ≥30-day grace period between stopping
the writes and deleting the bytes: a reader nobody knew about gets a month to notice and
complain, at a cost of one unchanging bucket.

---

## What is in there

| | |
|---|---|
| Current objects | **347** — 232 under `processed/`, 115 under `raw/` |
| Versions + delete markers | 540 + 2 (versioning is on, so a plain delete would only add markers) |
| Size | 9,275,153 B of versions · 9,302,633 B billed as StandardStorage |
| Oldest | `raw/sorteo_3046.txt`, 2025-06-16 |
| Newest | `processed/sorteos_3136.parquet`, **2026-09-17** — last Thursday's run |

The count moved 539 → 542 on 2026-09-17. The write path is live; this is not an abandoned
bucket that stopped filling by itself.

```bash
aws s3api list-object-versions --bucket lottery-data-simple-prod \
  --query '{Versions:length(Versions),DeleteMarkers:length(DeleteMarkers),Bytes:sum(Versions[].Size)}'
aws s3 ls s3://lottery-data-simple-prod/ --recursive | awk '{n=split($4,a,"/"); print a[1]}' | sort | uniq -c
```

## Evidence that nothing reads it

### 1. The code — conclusive, and the strongest item here

A repo-wide grep outside `docs/` and `scripts/policies/` returns **23 references and not one
reader**:

| Kind | Where |
|---|---|
| Writers | `transformer.py:257-258` (two Parquet copies) · `scraping.py:259` (the raw `.txt`) |
| Bucket-name plumbing | `transformer.py:48,306,312` · `scraping.py:23` · `main.tf:58,102,120` · `etl-glue/main.tf:80` |
| IAM write grants | `modules/iam/main.tf:245,326,471` |
| Secret payload | `aws_secrets.py` exposes the `"simple"` key; `test_common.py` asserts it |
| Protection policy | `scripts/policies/lottery-data-simple-prod_protect.json` (PR-002's Deny) |
| Inventory script | `scripts/00_inventory_and_protect.sh:28` |

No `get_object`, no `download_file`, no read path of any kind. This is the one line of
evidence that is *proof* rather than inference: the pipeline cannot read what it never asks
for.

### 2. The Glue catalog — no table points at it

```
premios_premios        -> s3://lottery-partitioned-storage-prod/processed/premios/
sorteos_sorteos        -> s3://lottery-partitioned-storage-prod/processed/sorteos/
silver_premios_premios -> s3://lottery-partitioned-storage-prod/silver/premios/
gold_*                 -> s3://lottery-partitioned-storage-prod/gold/*
```

Every table in `lottery_santalucia_db` resolves to the **partitioned** bucket. Note the trap:
the two legacy tables are named for a `processed/` prefix, and the simple bucket also has a
`processed/` prefix — different buckets, same word. Anyone checking this quickly could read
those two rows as evidence of a reader. They are not.

The seven Gold `.sql` files mention the simple bucket nowhere (`grep -rl data-simple sql/`).

### 3. Athena query history — 44 queries, none of them

```
44 queries in workgroup lottery-wg, 2026-08-09 → 2026-09-17
mentioning "data-simple": 0
```

**Limits worth stating.** Athena keeps roughly 45 days of history, this covers one workgroup,
and a query cannot name the bucket anyway unless a table pointed at it — which none does. It
corroborates item 2; it does not extend it.

### 4. CloudTrail data events — **not enabled for this bucket**

The account's only trail (`lottery-cloudtrail-dev`, multi-region) logs S3 data events for
exactly one bucket:

```
DataResources: AWS::S3::Object -> arn:aws:s3:::lottery-cloudtrail-logs-dev/*
```

So there are **no `GetObject` records for `lottery-data-simple-prod`, and there never were**.
Per the roadmap's own instruction: absent logging is not evidence of absent readers. This
item proves nothing either way, and it is written down so that nobody later mistakes an empty
CloudTrail query for a clean bill of health.

### 5. S3 request metrics — not configured

`list-bucket-metrics-configurations` is empty, so `BytesDownloaded` has no datapoints (0 over
the last 30 days). Same caveat as item 4: the metric is opt-in and costs money per request, so
its absence is a configuration fact, not a usage fact.

---

## What this does and does not license

**Licensed:** stopping the writes (PR-041.1). It is reversible with one Terraform value, and
until the flag is flipped it changes nothing at all.

**Not licensed yet:** deleting anything. Items 4 and 5 are blind, and a person with console
access is outside every signal above. PR-041.3 answers that with time rather than with
certainty — ≥30 days after the flip, with the abort condition that the object count must
match this snapshot exactly. If it moved, a writer nobody knew about is still running, and
that has to be found before a single byte goes.

## Status

**The writes stopped 2026-09-20 22:31 UTC** (PR #53 applied). The count below is therefore
frozen, and that is the thing to check: every number here is a baseline for PR-041.3's abort
condition, not a historical note.

| | |
|---|---|
| Flip applied | 2026-09-20 22:31 UTC |
| Earliest teardown | **2026-10-20** (≥30 days) |
| Weekly runs inside the window | 09-24, 10-01, 10-08, 10-15 |
| Object count that must not move | **347** |

## Re-running this

Every command here is read-only and safe to repeat; that is the point of writing them down
rather than pasting their output alone. The one to run before PR-041.3 is the object count:

```bash
aws s3 ls s3://lottery-data-simple-prod/ --recursive | wc -l   # expect 347
```
