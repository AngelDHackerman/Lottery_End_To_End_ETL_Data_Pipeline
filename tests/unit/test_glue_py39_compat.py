"""PR-050 — the Glue transform job runs on Python 3.9; keep its code 3.9-compatible.

ruff targets py312 (the Lambdas), so its UP rules happily suggest 3.10+/3.11+ idioms —
`dt.UTC`, `X | Y` outside an annotation, `StrEnum`. CI passes, the Lambda imports it fine,
and the weekly Glue run dies. pyproject.toml's per-file-ignores switch those rules off for
the modules the transform job runs. These tests keep that list honest:

* the job's import closure is computed from the source, so a module the transformer starts
  importing tomorrow is checked without anyone remembering to add it;
* every module in the closure must sit under one of the 3.9 globs, with all the rules;
* every module must parse under 3.9's grammar — the one thing an ignore list cannot catch.
"""

from __future__ import annotations

import ast
import fnmatch
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

# What Glue actually executes: the zipapp entry point, which imports the transformer.
ENTRY_POINT = REPO / "scripts" / "glue_zip_main.py"

# The rules that would rewrite code into something 3.9 cannot run (see pyproject.toml).
PY39_RULES = {"UP007", "UP017", "UP038", "UP040", "UP041", "UP042"}


def _module_path(module: str) -> Path | None:
    base = SRC.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _loteria_imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] == "loteria":
                found.add(node.module)
                # `from loteria.common import lineage` imports a submodule, not a name.
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.split(".")[0] == "loteria")
    return found


def glue_import_closure() -> list[Path]:
    """Every file the transform job can import, starting from its entry point."""
    paths = {ENTRY_POINT}
    pending = list(_loteria_imports(ENTRY_POINT))
    seen: set[str] = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(module)
        if path is None:  # a name imported from a package, not a submodule
            continue
        paths.add(path)
        parts = module.split(".")
        # Importing a.b.c runs a/__init__.py and a/b/__init__.py first.
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        pending.extend(_loteria_imports(path))
    return sorted(paths)


def _per_file_ignores() -> dict[str, list[str]]:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["ruff"]["lint"]["per-file-ignores"]


def _ignored_rules(rel_path: str, ignores: dict[str, list[str]]) -> set[str]:
    rules: set[str] = set()
    for pattern, codes in ignores.items():
        if fnmatch.fnmatch(rel_path, pattern):
            rules.update(codes)
    return rules


CLOSURE = glue_import_closure()


def test_closure_is_the_transform_job():
    """Guard the guard: if the walk silently found nothing, every test below would pass."""
    rel = {p.relative_to(REPO).as_posix() for p in CLOSURE}
    assert "src/loteria/transformer/transformer.py" in rel
    assert "src/loteria/parser/parser.py" in rel
    assert "src/loteria/common/lineage.py" in rel
    assert "scripts/glue_zip_main.py" in rel


@pytest.mark.parametrize("path", CLOSURE, ids=lambda p: p.relative_to(REPO).as_posix())
def test_glue_module_is_shielded_from_py310_plus_rewrites(path: Path):
    rel = path.relative_to(REPO).as_posix()
    missing = PY39_RULES - _ignored_rules(rel, _per_file_ignores())
    assert not missing, (
        f"{rel} runs in the Python 3.9 Glue job but ruff may still rewrite it with "
        f"{sorted(missing)}. Add its directory to the 3.9 block of "
        "[tool.ruff.lint.per-file-ignores] in pyproject.toml."
    )


@pytest.mark.parametrize("path", CLOSURE, ids=lambda p: p.relative_to(REPO).as_posix())
def test_glue_module_parses_as_python_39(path: Path):
    # feature_version rejects grammar newer than 3.9 — `match`, `except*`, PEP 695 — which
    # no ignore list can stop someone from typing by hand.
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))
