# PR-047 — Retry the proxy failure that actually happens

**Filed in PR-031.2 (2026-09-24), held until the 2026-10-08 run had verified 044/045 alone.**
`RunExtractorLambda` has had a `Retry` since PR-031.1, but it never engaged on the failure
that keeps happening. This PR makes it engage, and only on that failure, and rewrites the
alarm text that told a responder there was no retry at all.

---

## 1. The defect

The deployed retrier lists transport faults only: `ReadTimeout`, `ConnectTimeout`,
`ConnectionError` and four `Lambda.*` service errors. A proxy 502 is not a transport fault:
scrape.do **answers**, with an HTTP 502 after ~57 s:

```
[PROXY] https://loteria.org.gt/site/award -> HTTP 502 | Preview: {"StatusCode":502,
"ErrorCode":90,"ErrorType":"ROTATION_FAILED", … "Occasional failures on protected domains
are expected.","Request failed and not charged. Please try again."]}
```

`fetch_via_proxy` turned that into a bare `ValueError`, which matched none of those names.
So the 2026-09-24 run got **one attempt** and died, although scrape.do's own message says to
try again.

**Why not just add `ValueError` to the list.** Every parsing failure in `scraping.py` also
raises `ValueError`: a missing prize container, an unreadable sorteo number, a link that is
not there. Retrying a deterministic bug burns 10 credits per listing fetch to fail four
times instead of once, and delays the alert by ~41 minutes.

## 2. The fix

| Piece | What it does |
|---|---|
| `ProxyHTTPError(Exception)` | Any non-200 from scrape.do. Carries `status_code` and `target_url`; same message text as before. **Not** a `ValueError`, so no `except ValueError` aimed at parsing can swallow an outage. |
| `ProxyRetryableError(ProxyHTTPError)` | 429 or any 5xx. `is_retryable_status()` decides. |
| Second retrier on `RunExtractorLambda` | `ErrorEquals = ["ProxyRetryableError"]`, `IntervalSeconds 300`, `MaxAttempts 3`, `BackoffRate 2.0` |

**Step Functions matches the class NAME.** A Lambda failure reaches the state machine as its
`errorType`, which is `type(exc).__name__`. Base classes are not considered, which is why the
split needs two distinct names instead of one class with a flag. Rename the class and
nothing fails: the retry just stops engaging. `test_retryable_error_is_in_the_asl` reads the
name out of `main.tf` and compares it to the Python class.

**Which statuses.** Transient by scrape.do's documentation: 429 (concurrency/rate limit) and
5xx (502 `ROTATION_FAILED` being the one seen in production). Permanent: 400, 401 (bad
token or quota spent), 402, 403, 404. A fourth attempt with a spent quota is still a spent
quota.

**Timing: minutes, not seconds.** What fails is a proxy rotation against Cloudflare, and a
rotation 60 s later lands on the same pool. Attempts at **t+0, +5, +15, +35 min**. Each one
is bounded by the Lambda's 120 s timeout (a 502 uses ~57 s of it), so the window is ~41 min
worst case. Nothing downstream has a deadline: the run is weekly and Gold is rebuilt
whenever it gets there.

**The two retriers count separately.** Step Functions keeps one attempt counter per
retrier, so a run that hits both kinds of error can make at most 1 + 2 + 3 attempts.

## 3. What it costs

On today's profile (`geoCode=GT&super=true`, no render: 10 credits per request, 2 requests
per run, from PR-031.2):

| Case | Credits |
|---|---|
| 502 on the **listing** fetch | 0 per failed attempt (scrape.do does not charge a failed request) |
| Listing OK, 502 on the **detail** fetch | 10 per failed attempt (the listing was charged) |
| Worst case: 3 retries all failing on the detail page, then success | 30 + 20 = **50** |
| Plan | 1000 / month; a normal month is ~175 including the canary |

Retrying is free while the 502 persists, and it costs real credits only in the one case
where it is also the most likely to work.

## 4. Scope: what this does NOT fix

- **The eight-failure outage of 2026-09-24.** That was a profile problem (`render=true` had
  become the thing Cloudflare rejected). Three more attempts on the same profile would also
  have failed. The fix there was PR-031.2.
- **Cloudflare's Waiting Room.** It answers **200**, so it never reaches this code path; it
  fails later, in parsing, as a `ValueError`, and is correctly *not* retried.
- **Credits on retries.** `check_if_sorteo_exists()` still runs after both fetches
  (PR-035.1 A), so a retry pays for its listing fetch.

## 5. The alarm text

`loteria-sfn-execution-failed-prod` used to begin *"Because the machine has no Retry/Catch,
this fires for a failure in ANY stage"*. That has been false since PR-031.1 (extractor
retries) and PR-033 (the DQ gate's Catch). It is the first sentence of the alert email, and
it sent the 09-24 investigation looking in the wrong place. Now it says what the alarm means
today: the execution failed **after** its retries, or the Silver DQ gate stopped it on
purpose.

Two neighbours gained one sentence each, because retries change what they mean:

- **`extractor-errors`** counts every failed *attempt*. An email from it with no
  `sfn-execution-failed` after it means a retry absorbed the failure and the run went on.
- **`scrapedo-failed`** fires on any non-200, including a 502 that the next attempt recovers.

## 6. Apply

```bash
make deploy
```

Expected plan, measured read-only on 2026-10-08 with
`-target=module.orchestration -target=module.observability`: **`0 to add, 4 to change, 0 to
destroy`**. That is the state machine plus the three alarm descriptions. The full `make
deploy` adds the extractor Lambda (`src/` changed, so `lambda_package.zip` changes) and
whatever build churn the day brings. **Re-measure at apply time.** A `destroy` on anything
means STOP.

The rendered ASL from that plan, which is the acceptance bar:

```
~ RunExtractorLambda = {
    ~ Retry = [
          { ErrorEquals = ["ReadTimeout", "ConnectTimeout", "ConnectionError", "Lambda.…"], … },
        + {
        +   BackoffRate     = 2
        +   ErrorEquals     = ["ProxyRetryableError"]
        +   IntervalSeconds = 300
        +   MaxAttempts     = 3
        + },
      ]
```

## 7. Verify

A real 502 cannot be scheduled, so the bar is the unit suite plus the deployed definition:

```bash
# 1. The deployed machine carries the retrier.
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod \
  --query definition --output text \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["States"]["RunExtractorLambda"]["Retry"], indent=1))'
# expect: two retriers, the second with ErrorEquals ["ProxyRetryableError"], 300 / 3 / 2.0

# 2. The deployed Lambda has the classes (the zip, not a timestamp, is the proof).
aws lambda get-function --function-name lottery-extractor-prod --query Code.Location --output text \
  | xargs curl -s -o /tmp/extractor.zip
unzip -p /tmp/extractor.zip loteria/extractor/scraping.py | grep -n "class Proxy"
# expect: ProxyHTTPError and ProxyRetryableError

# 3. The alarm text.
aws cloudwatch describe-alarms --alarm-names loteria-sfn-execution-failed-prod \
  --query 'MetricAlarms[0].AlarmDescription' --output text
# expect: begins "The ETL state machine failed an execution, AFTER its retries."
```

### ✅ Result, 2026-10-09 (after the owner's `make deploy`)

1. **Deployed ASL:** `RunExtractorLambda.Retry` holds two retriers. The first is unchanged
   (7 transport/Lambda names, 60 s × 2). The second is `["ProxyRetryableError"]`,
   `IntervalSeconds 300`, `MaxAttempts 3`, `BackoffRate 2`.
2. **Deployed Lambda:** `LastModified 2026-10-09T01:08:21Z`, `CodeSha256
   CmpKbabudbEw3C5AYoqRWb269uO8IQDlSS86vmC6WI4=`. The zip's `scraping.py` has
   `class ProxyHTTPError` (l.91), `class ProxyRetryableError` (l.105) and the raise of the
   latter (l.165). Layer `loteria-deps-prod:6`.
3. **Alarm text:** `sfn-execution-failed` begins "…failed an execution, AFTER its retries."
   `extractor-errors` carries "Counts EVERY failed attempt", and `scrapedo-failed` carries
   "retried by the state machine (PR-047)". All three are `OK`.

No execution has run since the deploy; the last one is still 2026-10-08's.

Then let the scheduled run of **Thursday 2026-10-15** (sorteo 3139, drawn Saturday 10-10)
go through. It will almost certainly not see a 502, so it proves only that nothing regressed:
the extractor still succeeds and returns its file. The retry path stays proven by the tests
until the day scrape.do has a bad minute. On that day, the execution history should show
`RunExtractorLambda` failing with `ProxyRetryableError` and then succeeding 5 minutes later.

## 8. Rollback

`git revert` + `make deploy`. The previous definition simply lacks the second retrier, and
the extractor would go back to raising `ValueError`. Nothing stored changes.
