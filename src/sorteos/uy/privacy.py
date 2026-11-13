"""What Uruguay's ingestion must never touch (UY-001; DESIGN.md, P5).

The DNLQ publishes ``*_DET_INVALIDAS_*`` PDFs next to its results, and they carry a
"Cédula Id." column — national ID numbers tied to voided phone bets (Ley 18.331). Nothing
matching ``DET_INVALIDAS`` is requested, followed through a redirect, stored or logged.

The pattern lives here, in code, and never in a YAML: a mistake in a configuration file
must not be able to switch the guard off. Every Uruguayan client is built through
:func:`polite_client`, so no caller can forget to pass it.
"""

from __future__ import annotations

import os

from sorteos.core import http_client
from sorteos.core.http_client import PoliteClient
from sorteos.uy.sources import AGENT

BLOCKED_PATTERNS = ("DET_INVALIDAS",)


def polite_client(**kwargs) -> PoliteClient:
    """A PoliteClient that refuses :data:`BLOCKED_PATTERNS` and introduces itself as
    :data:`~sorteos.uy.sources.AGENT`. Neither can be overridden: passing ``blocklist`` or
    ``agent`` here is a TypeError. The contact comes from ``LOTERIA_UY_CONTACT`` if set."""
    kwargs.setdefault("contact", os.environ.get("LOTERIA_UY_CONTACT"))
    return PoliteClient(blocklist=BLOCKED_PATTERNS, agent=AGENT, **kwargs)


def blocked_pattern(url: str) -> str | None:
    """The Uruguayan pattern ``url`` matches, or None (used to skip links in a page)."""
    return http_client.blocked_pattern(url, BLOCKED_PATTERNS)
