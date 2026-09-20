"""One reading of one flag, whatever delivers it (PR-041.1).

The `simple` bucket's write path is disabled by a flag that reaches the two writers by
different routes — a Glue **job argument** for the transformer, a Lambda **environment
variable** for the extractor — and both arrive as strings typed by a human into Terraform.
This module is what makes ``"false"`` mean the same thing on both sides.

**The default is ON, and unrecognised values stay ON.** That is not laziness about
validation; it is the direction a mistake should fail in. PR-041.1's entire promise is
"stop the writes, keep every byte", and its acceptance test is that the object count stops
moving — so a typo that leaves writes enabled is *visible* on the next run, while one that
silently disabled them would be a quiet data-loss change nobody asked for. The typo is not
silent either way: an unrecognised value logs a warning naming it.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: The flag's name. Identical as a Glue job argument (``--ENABLE_SIMPLE_BUCKET_WRITES``)
#: and as a Lambda environment variable, so grepping either side finds both.
FLAG_SIMPLE_BUCKET_WRITES = "ENABLE_SIMPLE_BUCKET_WRITES"

#: Terraform renders a bool as ``"true"``/``"false"``; the rest are here because a human
#: editing a console field writes what they think, not what HCL emits.
_TRUE = frozenset({"true", "1", "yes", "on", "enabled"})
_FALSE = frozenset({"false", "0", "no", "off", "disabled"})


def parse_flag(value: str | None, *, default: bool = True, name: str = "flag") -> bool:
    """Read a boolean out of a config string.

    ``None`` and the empty string mean "not set" and take ``default`` without comment — an
    absent argument is the normal case for a job whose code ships separately from its
    Terraform. Anything else that is not recognised keeps ``default`` and says so.
    """
    if value is None or not value.strip():
        return default

    normalised = value.strip().lower()
    if normalised in _TRUE:
        return True
    if normalised in _FALSE:
        return False

    logger.warning(
        "Unrecognised boolean config value; keeping the default",
        extra={"config_name": name, "value": value, "default": default},
    )
    return default


def env_flag(name: str, *, default: bool = True) -> bool:
    """``parse_flag`` against ``os.environ``, read at CALL time, not at import.

    The extractor's module body already runs at import (``get_secrets()``), and reading
    configuration there is what PR-017 had to unpick: a value bridged into the environment
    after the import has no effect on anything decided during it. Reading here also means a
    console edit of the Lambda's environment takes effect on the next invocation without a
    redeploy, which is the point of putting the flag in Terraform rather than in the zip.
    """
    return parse_flag(os.environ.get(name), default=default, name=name)
