"""scripts/_zipdir.py — the zip must not depend on the umask of the shell that built it.

PR-046.2: on 2026-10-22 a leftover `umask 077` made every built file 0600, and because a
zip stores unix modes, byte-identical code produced new hashes and a planned Lambda
redeploy. These tests build the same tree under two umasks and compare.
"""

import importlib
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
zipdir = importlib.import_module("_zipdir")


def _make_tree(root: Path, file_mode: int, exec_mode: int) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("x = 1\n")
    (root / "pkg" / "mod.py").write_text("y = 2\n")
    (root / "bin").mkdir()
    (root / "bin" / "tool").write_text("#!/bin/sh\n")
    for f in ("pkg/__init__.py", "pkg/mod.py"):
        os.chmod(root / f, file_mode)
    os.chmod(root / "bin" / "tool", exec_mode)


def _build(tree: Path, out: Path, monkeypatch) -> bytes:
    monkeypatch.chdir(tree)
    monkeypatch.setattr(sys, "argv", ["_zipdir.py", str(out)])
    zipdir.main()
    return out.read_bytes()


def _modes(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return {i.filename: stat.filemode(i.external_attr >> 16) for i in archive.infolist()}


@pytest.mark.parametrize(
    ("st_mode", "expected"),
    [
        (0o100644, 0o100644),
        (0o100600, 0o100644),  # umask 077
        (0o100664, 0o100644),  # umask 002
        (0o100755, 0o100755),
        (0o100700, 0o100755),  # umask 077 on an executable
    ],
)
def test_normalised_mode(st_mode, expected):
    assert zipdir.normalised_mode(st_mode) == expected


def test_same_tree_under_two_umasks_gives_the_same_zip(tmp_path, monkeypatch):
    _make_tree(tmp_path / "a", 0o644, 0o755)  # umask 022
    _make_tree(tmp_path / "b", 0o600, 0o700)  # umask 077
    zip_a = _build(tmp_path / "a", tmp_path / "a.zip", monkeypatch)
    zip_b = _build(tmp_path / "b", tmp_path / "b.zip", monkeypatch)
    assert zip_a == zip_b
    assert _modes(tmp_path / "b.zip") == {
        "bin/tool": "-rwxr-xr-x",
        "pkg/__init__.py": "-rw-r--r--",
        "pkg/mod.py": "-rw-r--r--",
    }
