# The architecture-diagram prompt

This is the prompt that produced [`layouts/diagram.html`](../../layouts/diagram.html) (PR #47),
kept in the repo so the diagram can be *re-derived* rather than patched forever. Phase 3 is
the part that did not exist when it was first run, and is what the diagram actually needs
most of the time.

Provenance: first run 2026-09-14, against the state of the account that day. Updated
2026-09-20 to match where the files really landed and how the result gets verified.

---

## PHASE 1 — Investigation, read-only

Hard rules:

**Do NOT** execute the pipeline, trigger jobs, consume paid API quotas, or write to any cloud
resource. Read-only AWS calls (`describe-*`, `list-*`, `get-*`, `s3 ls`) are not only allowed
but expected — see the next rule.

**Do NOT trust the README, the roadmap, or the existing diagram.** They are the hypothesis,
not the evidence. Verify every claim against the code, the IaC, and — this is the part that
gets skipped — **the live account**. In this repo, `merged` has repeatedly meant *"the code
is on master and nothing is deployed"*. A tracker row is not a deployment. If the docs and
the code contradict each other the code wins; if the code and the account contradict each
other **the account wins**, and either contradiction is a finding that must be recorded.

Always distinguish three states, which are often confused:

- **(a)** deployed and running
- **(b)** written in the repo but NOT deployed
- **(c)** deployed but turned off, or with no consumer

Actively look for (c): feature flags set to false, resources with `count = 0`, modules whose
only consumer is disabled, log groups nothing writes to, tables nothing queries, and dead
code. A thing that exists and does nothing costs money and reads as working.

Answer with evidence (file and line number, or the read-only command and its output):

1. What is the real trigger for the ingestion, and at what frequency? If it is streaming,
   what pushes it and what consumes it?
2. What delivery guarantee is actually provided: at-most-once, at-least-once, or
   exactly-once? Not what the README says — what the code and configuration imply. Where does
   the checkpoint/offset live, and what happens if the consumer dies midway?
3. Is there backpressure? If the producer runs faster than the consumer, does it buffer, drop
   or crash?
4. What happens to a record that cannot be parsed? Is there a DLQ or quarantine, or is it
   lost silently? **Silent data loss is the worst possible defect** — look for it specifically.
5. Is there schema enforcement, and what happens when the source changes a field?
6. How are late-arriving data and event time vs. processing time handled?
7. Are there tests, and what executes them? Does CI exist, what gates does it have, and are
   those gates actually red/green — or is there one that never runs?
8. What observability exists: metrics, alarms, who they notify, and in what detail. Does an
   alarm say "something failed", or does it say **what** failed? And for each log
   destination: is anything actually landing in it?
9. Is there orphaned work? Check unmerged remote branches, closed-unmerged PRs, and
   gitignored files that look like half-finished artifacts. Finished work that never reached
   master often lives there.
10. Which medallion layers actually exist, and what is the final downstream consumer — if any?

Before drawing, show a summary of findings and **every** contradiction between the
documentation and reality.

## PHASE 2 — The diagram

It lives in `layouts/`, split into four files (it started as one; the split is what made it
editable):

| File | Holds |
|---|---|
| `layouts/diagram.html` | the page: header, controls, side panel, the defects tables |
| `layouts/css/diagram.css` | every style, with light/dark tokens on `:root` |
| `layouts/js/diagram.data.js` | **the architecture**: nodes, edges, notes, the run script |
| `layouts/js/diagram.js` | render and interaction only — it knows no resource names |

No CDNs, no libraries, no network requests, no build step: it must open with a double-click,
offline. The SVG is written by hand from the data file.

Requirements:

- The diagram **is** the page, not an appendix to a document. Large and readable on open.
- Colour-code by state: deployed / written-not-deployed / defect / turned off. What is alive
  must be clear at a glance.
- Clicking a component opens a side panel with its **real** resource names, its state, and
  the gotcha that piece carries.
- A button replays the end-to-end run step by step, with an explanation per step. Where
  something is missing — a gate, a DLQ, a consumer — the step says so explicitly instead of
  skipping it.
- Separate the control plane (CI/CD) from the data plane, and draw what connects them. **If
  they do not touch, draw that absence**: it is a design decision, not an omission.
- Label the arrows that carry a decision. An unlabeled arrow only says "something happens".
- Light and dark mode via CSS tokens, `prefers-color-scheme` plus an explicit override.

## PHASE 3 — Keeping it true

A diagram that drifts is worse than none: it is a confident lie about production.

**To change what it says, edit `diagram.data.js`.** Only reach for `diagram.js` when the
*behaviour* changes (a new toggle, a new edge routing). Resource names never belong in
`diagram.js`.

**Verify the geometry by rendering it, not by reading the SVG.** Overlaps are invisible in
the source and obvious in a picture:

```bash
google-chrome --headless --no-sandbox --disable-gpu --hide-scrollbars \
  --virtual-time-budget=4000 --window-size=1500,1150 \
  --screenshot=/tmp/diagram.png file://$PWD/layouts/diagram.html
```

Then look at it. Two real defects were found exactly this way, both invisible in the code:
the prefix chips were painted *before* the node boxes and therefore hidden under an opaque
rect, and the "sin conexión" label was wider than the 24 px channel it sat in, so it spilled
across two zone borders.

**Verify the behaviour headlessly too.** Append a script that clicks the controls and writes
the result into `document.title`, then read it back with `--dump-dom`. A toggle that dims
every node is not something a screenshot of the idle page will show.

**Re-check the claims against the account before publishing**, at least: the schedule of
every trigger, the state machine's actual `States` graph, the row and file counts, the alarm
list (mind alarms belonging to *other* projects in the same account), and the newest
partition in the lake. Those are the numbers that rot first.

Finish by stating what contradictions were found between the documentation and reality, and
propose the fixes — without applying them.
