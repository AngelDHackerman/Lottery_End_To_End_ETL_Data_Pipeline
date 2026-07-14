"""Zipapp entry point for the Glue pythonshell job.

Glue executes the job artifact as `python lottery_transformer.zip`, so Python requires a
`__main__.py` at the ZIP ROOT. The job's `--script-file` argument does NOT select the
entry point — it is inert (Glue never reads it), which is why the pre-PR-016 zip only
worked by virtue of having a `__main__.py` at its root.

build_glue_package.sh copies this file into the zip root as `__main__.py`. It is kept
here rather than in src/loteria/ because it is packaging glue, not library code:
`loteria.transformer.__main__` already provides the equivalent `python -m` entry point.
"""

from loteria.transformer.transformer import main

if __name__ == "__main__":
    main()
