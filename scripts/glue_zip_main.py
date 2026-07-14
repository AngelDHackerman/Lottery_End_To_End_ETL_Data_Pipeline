"""Zipapp entry point for the Glue pythonshell job.

Glue executes the job artifact as `python lottery_transformer.zip`, so Python requires a
`__main__.py` at the ZIP ROOT. The job's `--script-file` argument does NOT select the
entry point — it is inert (Glue never reads it), which is why the pre-PR-016 zip only
worked by virtue of having a `__main__.py` at its root.

build_glue_package.sh copies this file into the zip root as `__main__.py`. It is kept
here rather than in src/loteria/ because it is packaging glue, not library code:
`loteria.transformer.__main__` already provides the equivalent `python -m` entry point.
"""

import os
import sys


def _bridge_secret_name_arg_to_env() -> None:
    """Copy the ``--LOTERIA_SECRET_NAME`` job argument into ``os.environ`` (PR-017).

    Glue delivers job arguments on the command line (``sys.argv``), not as environment
    variables, but ``loteria.common.aws_secrets.get_secrets()`` reads the secret name
    from ``LOTERIA_SECRET_NAME`` in the environment — and does so at *import* time. So
    this bridge must run BEFORE the transformer is imported below. ``setdefault`` lets a
    real environment variable win if one is ever set.
    """
    argv = sys.argv
    for i, token in enumerate(argv):
        if token == "--LOTERIA_SECRET_NAME" and i + 1 < len(argv):
            os.environ.setdefault("LOTERIA_SECRET_NAME", argv[i + 1])
            return
        if token.startswith("--LOTERIA_SECRET_NAME="):
            os.environ.setdefault("LOTERIA_SECRET_NAME", token.split("=", 1)[1])
            return


_bridge_secret_name_arg_to_env()

from loteria.transformer.transformer import main  # noqa: E402

if __name__ == "__main__":
    main()
