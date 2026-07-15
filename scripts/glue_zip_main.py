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

# Job arguments that must be visible to the code as environment variables. Glue delivers
# arguments on the command line (``sys.argv``), NOT as env vars, but the code reads these
# from the environment (get_secrets() reads LOTERIA_SECRET_NAME at import time; PR-017,
# and configure_logging() reads CORRELATION_ID; PR-018). So this bridge must run BEFORE
# the transformer is imported below.
_ARGS_TO_BRIDGE = ("LOTERIA_SECRET_NAME", "CORRELATION_ID")


def _bridge_args_to_env() -> None:
    """Copy selected ``--NAME value`` job arguments into ``os.environ``.

    ``setdefault`` lets a real environment variable win if one is ever set.
    """
    argv = sys.argv
    for name in _ARGS_TO_BRIDGE:
        flag = f"--{name}"
        for i, token in enumerate(argv):
            if token == flag and i + 1 < len(argv):
                os.environ.setdefault(name, argv[i + 1])
                break
            if token.startswith(f"{flag}="):
                os.environ.setdefault(name, token.split("=", 1)[1])
                break


_bridge_args_to_env()

from loteria.transformer.transformer import main  # noqa: E402

if __name__ == "__main__":
    main()
