"""Glue entry point for the Silver data-quality job (PR-033).

This is the file Glue runs as the job script. It is deliberately thin: everything it does
lives in ``loteria.dq``, which PR-032 already covers with tests. Its whole job is to bridge
Glue's calling convention to that library and to fail in a way the pipeline can act on.

**Why this is a Spark (``glueetl``) job when it never touches Spark.** PR-032 found that
``great-expectations`` 1.x requires Python >= 3.10, and Glue Python Shell offers only 3.6 and
3.9 — so the roadmap's "Python Shell job that pip-installs great-expectations" cannot work
(pip falls back to the 0.18 line, whose API is unrelated). Glue 5.0 is the runtime that gives
us Python 3.11. The script never creates a SparkContext, so it runs as an ordinary Python
process on the driver; the Spark cluster is the price of the interpreter version, and at one
weekly run it is a few cents.

**How a failure reaches a human.** Step Functions catches this job's failure and publishes to
the SNS alerts topic. The message body is Glue's ``ErrorMessage``, which for a Python error is
the exception's string — so the summary raised below is what the owner actually reads in the
alert. "DQ failed" with no detail would send them to the console to find out what broke, so
the message names the suite, the expectation and the column.
"""

import sys

from awsglue.utils import getResolvedOptions

from loteria.common.logging_setup import configure_logging
from loteria.dq.runner import (
    SILVER_PREFIX_DEFAULT,
    SilverDatasetEmpty,
    format_report,
    run_dq,
    summarize_failures,
)

# Only PARTITIONED_BUCKET is required. The other two are optional, and `getResolvedOptions`
# raises rather than defaulting when an argument it was told to expect is absent — so they
# are resolved separately below.
REQUIRED_ARGS = ["PARTITIONED_BUCKET"]
OPTIONAL_ARGS = ["SILVER_PREFIX", "CORRELATION_ID"]


class SilverDataQualityFailed(Exception):
    """Raised to fail the Glue run when an expectation fails.

    A distinct exception type so the Glue log makes it obvious that the job did its work and
    found bad data, rather than crashing on the way there.
    """


def _optional_args(argv: list[str]) -> dict[str, str]:
    """Read the optional ``--NAME value`` arguments without tripping getResolvedOptions.

    Glue delivers arguments as command-line tokens. ``getResolvedOptions`` raises
    ``GlueArgumentError`` for any name in its list that was not supplied, so an argument that
    is genuinely optional cannot go through it.
    """
    found = {}
    for name in OPTIONAL_ARGS:
        flag = f"--{name}"
        for index, token in enumerate(argv):
            if token == flag and index + 1 < len(argv):
                found[name] = argv[index + 1]
                break
            if token.startswith(f"{flag}="):
                found[name] = token.split("=", 1)[1]
                break
    return found


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv if argv is None else argv

    args = getResolvedOptions(argv, REQUIRED_ARGS)
    optional = _optional_args(argv)

    # PR-018: same correlation id as every other stage of the run, so the DQ verdict can be
    # stitched to the extractor and transformer logs it is judging. configure_logging reads
    # it from the environment, and Glue passes arguments on the command line, so bridge it.
    if "CORRELATION_ID" in optional:
        import os

        os.environ.setdefault("CORRELATION_ID", optional["CORRELATION_ID"])

    configure_logging("silver-dq")

    bucket = args["PARTITIONED_BUCKET"]
    silver_prefix = optional.get("SILVER_PREFIX", SILVER_PREFIX_DEFAULT)

    try:
        report = run_dq(bucket=bucket, silver_prefix=silver_prefix)
    except SilverDatasetEmpty as exc:
        # Re-raised rather than mapped to a DQ failure. "There is no Silver data" means the
        # bucket/prefix is wrong or the transformer never ran — a different problem, and one
        # the alert should not describe as bad data.
        raise SilverDataQualityFailed(f"No Silver data to validate: {exc}") from exc

    # Printed, not logged: this is the full human-readable verdict and it belongs in the Glue
    # driver log in one piece, not wrapped in a JSON envelope per line.
    print(format_report(report))

    if not report.success:
        raise SilverDataQualityFailed(
            f"Silver DQ failed — Gold was NOT built. {summarize_failures(report)}"
        )


if __name__ == "__main__":
    main()
