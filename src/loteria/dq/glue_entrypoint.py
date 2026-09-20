"""Glue entry point for the Silver data-quality gate (PR-033).

This is the file Glue runs as the job script. It is deliberately thin: everything it does
lives in ``loteria.dq``, which PR-032 already covers with tests. Its whole job is to bridge
Glue's calling convention to that library and to fail in a way the pipeline can act on.

**Why this is a Spark (``glueetl``) job when it never touches Spark.** PR-032 found that
``great-expectations`` 1.x requires Python >= 3.10, and Glue Python Shell offers only 3.6 and
3.9 (PR-020's runtime spike) — so the roadmap's "Python Shell job that pip-installs
great-expectations" cannot work: on 3.9 pip resolves back to the GX 0.18 line, whose API is
unrelated to the one ``loteria.dq`` is written against, and the job would install cleanly and
then fail at import. Glue 5.0 is the runtime that gives us Python 3.11. This script never
creates a ``SparkContext``, so it runs as an ordinary Python process on the driver; the Spark
cluster is the price of the interpreter version, and at one weekly run it is a few cents.

**Why the arguments are parsed here instead of with ``awsglue.utils.getResolvedOptions``.**
Two reasons, and the second is the one that matters. First, ``getResolvedOptions`` raises for
any name in its list that was not supplied, so a genuinely optional argument cannot go through
it — the optional half would need hand-rolled parsing anyway, and one parser is better than
two that disagree. Second, ``awsglue`` exists only inside Glue, so importing it at module
scope would make this module unimportable in a test run. Glue passes job arguments as ordinary
``--NAME value`` tokens in ``sys.argv``; that is all ``getResolvedOptions`` reads, and it is
all this reads.

**How a failure reaches a human.** Raising is the whole contract. The Glue run fails, the
Step Function's ``Catch`` on ``RunSilverDQ`` publishes to the SNS alerts topic, and Gold is
never built — a CTAS over a Silver layer we know is wrong would bake the bad data into seven
tables and, with the purge in ``loteria.gold.purge_and_load``, would do it by first deleting
the last known-good copy. The message in the exception is what the owner actually reads in the
alert, so it names the suite, the expectation and the column rather than saying "DQ failed".
"""

from __future__ import annotations

import logging
import os
import sys

#: The only argument the job cannot run without.
REQUIRED_ARGS = ("PARTITIONED_BUCKET",)

#: Arguments with a sensible default. ``SILVER_PREFIX`` lets the job be pointed at a copy of
#: the layer without a redeploy; ``CORRELATION_ID`` is PR-018's per-execution id;
#: ``DQ_LOG_GROUP`` is PR-033.1's per-job log group, passed by Terraform so the group's name
#: has exactly one source of truth; ``JOB_RUN_ID`` is what the Glue console shows, recorded
#: on the opening log line so a CloudWatch stream can be tied back to a run in the console.
OPTIONAL_ARGS = ("SILVER_PREFIX", "CORRELATION_ID", "DQ_LOG_GROUP", "JOB_RUN_ID")


class SilverDataQualityFailed(Exception):
    """Raised to fail the Glue run when an expectation fails.

    A distinct exception type so the Glue log makes it obvious that the job did its work and
    found bad data, rather than crashing on the way there.
    """


def parse_args(argv: list[str]) -> dict[str, str]:
    """Pull the ``--NAME value`` / ``--NAME=value`` job arguments this job knows about.

    Glue hands Spark jobs a good deal more than we asked for (``--JOB_NAME``,
    ``--job-language``, the continuous-logging flags), so this scans for the names it wants
    instead of parsing positionally. Unknown arguments are ignored, which is what keeps the
    job working when AWS adds another one.
    """
    found: dict[str, str] = {}
    for name in (*REQUIRED_ARGS, *OPTIONAL_ARGS):
        flag = f"--{name}"
        for index, token in enumerate(argv):
            if token == flag and index + 1 < len(argv):
                found[name] = argv[index + 1]
                break
            if token.startswith(f"{flag}="):
                found[name] = token.split("=", 1)[1]
                break

    missing = [name for name in REQUIRED_ARGS if not found.get(name)]
    if missing:
        raise SystemExit(f"Missing required job argument(s): {', '.join(missing)}")

    return found


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv if argv is None else argv
    args = parse_args(argv)

    # PR-018: carry the same correlation id as every other stage of the run, so the DQ
    # verdict can be stitched to the extractor and transformer logs it is judging.
    # configure_logging reads it from the environment and Glue delivers arguments on the
    # command line, so bridge it — before configure_logging, which snapshots it.
    # setdefault, so a real environment variable still wins.
    if args.get("CORRELATION_ID"):
        os.environ.setdefault("CORRELATION_ID", args["CORRELATION_ID"])

    # Imported here, not at module scope. These pull in great-expectations and pandas, which
    # on Glue arrive via --additional-python-modules and take seconds to resolve; doing it
    # after argument validation means a misconfigured job fails in a second with a legible
    # message instead of after the dependency install.
    from loteria.common.cloudwatch_logging import attach_cloudwatch_handler
    from loteria.common.logging_setup import configure_logging, resolve_correlation_id
    from loteria.dq.runner import (
        SILVER_PREFIX_DEFAULT,
        SilverDatasetEmpty,
        format_report,
        run_dq,
        summarize_failures,
    )

    logger = configure_logging("silver-dq")

    # PR-033.1. Continuous logging leaves this job's own log group empty — it ships Spark's
    # log4j output and this job runs no Spark — so the group is written to directly. After
    # configure_logging, which replaces the root handler list. A no-op when the argument is
    # absent, which is every run outside Glue.
    cw_handler = attach_cloudwatch_handler(args.get("DQ_LOG_GROUP"), resolve_correlation_id())

    logger.info(
        "Silver DQ starting",
        extra={"job_run_id": args.get("JOB_RUN_ID") or "-"},
    )

    bucket = args["PARTITIONED_BUCKET"]
    silver_prefix = args.get("SILVER_PREFIX") or SILVER_PREFIX_DEFAULT

    try:
        report = run_dq(bucket=bucket, silver_prefix=silver_prefix)
    except SilverDatasetEmpty as exc:
        # Re-raised rather than reported as a DQ failure. "There is no Silver data" means the
        # bucket or prefix is wrong, or the transformer never ran — a different problem, and
        # one the alert must not describe as bad data. The CLI draws the same distinction
        # with its own exit code (EXIT_NO_DATA), for the same reason.
        raise SilverDataQualityFailed(
            f"No Silver data to validate at s3://{bucket}/{silver_prefix} — "
            f"this is a wiring problem, not a data-quality one: {exc}"
        ) from exc

    # Printed, not logged: this is the full human-readable verdict and it belongs in the Glue
    # driver log in one piece, not split across JSON envelopes one line at a time.
    verdict = format_report(report)
    print(verdict)

    # PR-033.1: and once more into the per-job group, which is the place the runbook now
    # sends a woken-up human. Through a non-propagating logger carrying only the CloudWatch
    # handler, so the verdict does not also arrive on stdout a second time — JSON-escaped,
    # which is what logging it normally would produce.
    if cw_handler is not None:
        verdict_logger = logging.getLogger("silver-dq.verdict")
        verdict_logger.propagate = False
        verdict_logger.handlers = [cw_handler]
        verdict_logger.setLevel(logging.INFO)
        verdict_logger.info(verdict)

    if not report.success:
        raise SilverDataQualityFailed(
            f"Silver DQ failed — Gold was NOT built. {summarize_failures(report)}"
        )


if __name__ == "__main__":
    main()
