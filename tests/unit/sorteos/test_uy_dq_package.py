"""UY-026.2: the lock for Glue 5.0, the sorteos wheel and the committed lock files."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REQUIREMENTS = REPO / "requirements"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lock = _load("uy_dq_lock")
wheel = _load("uy_build_wheel")


def _report(*packages):
    return {
        "install": [
            {
                "metadata": {"name": name, "version": version},
                "download_info": {"archive_info": {"hashes": {"sha256": sha}}},
            }
            for name, version, sha in packages
        ]
    }


# --- uy_dq_lock -------------------------------------------------------------------------------


def test_names_are_canonical():
    assert lock.canonical("PyYAML") == "pyyaml"
    assert lock.canonical("ruamel.yaml") == "ruamel-yaml"
    assert lock.canonical("typing_extensions") == "typing-extensions"


def test_pins_reads_requirements_and_locks():
    text = "# comment\n-c base.txt\nPyYAML==6.0.2 \\\n    --hash=sha256:ab\npandas\nnumpy==1.26.4\n"
    assert lock.pins(text) == {"pyyaml": "6.0.2", "numpy": "1.26.4"}


def test_a_report_gives_version_and_hash_per_package():
    report = _report(("PyYAML", "6.0.2", "aa"), ("numpy", "1.26.4", "bb"))
    assert lock.resolved(report) == {"pyyaml": ("6.0.2", "aa"), "numpy": ("1.26.4", "bb")}


def test_a_wheel_without_sha256_is_refused():
    report = {"install": [{"metadata": {"name": "x", "version": "1"}, "download_info": {}}]}
    with pytest.raises(SystemExit, match="no sha256 for x"):
        lock.resolved(report)


def test_what_glue_has_stays_out_of_the_zip():
    packages = {"scipy": ("1.17.1", "aa"), "numpy": ("1.26.4", "bb")}
    ship, provided = lock.split(packages, {"numpy": "1.26.4", "pandas": "2.2.2"})
    assert ship == {"scipy": ("1.17.1", "aa")}
    assert provided == {"numpy": ("1.26.4", "bb")}


def test_a_glue_module_at_another_version_is_an_error():
    with pytest.raises(SystemExit, match="numpy resolved to 2.0.0, but Glue 5.0 has 1.26.4"):
        lock.split({"numpy": ("2.0.0", "aa")}, {"numpy": "1.26.4"})


def test_render_is_sorted_and_hashed():
    text = lock.render({"b": ("2", "bb"), "a": ("1", "aa")}, "What.")
    assert text.splitlines()[3:] == [
        "a==1 \\",
        "    --hash=sha256:aa",
        "b==2 \\",
        "    --hash=sha256:bb",
    ]
    assert lock.pins(text) == {"a": "1", "b": "2"}


@pytest.fixture
def fake_pip(tmp_path, monkeypatch):
    """Point the script at tmp files and record the pip command instead of running it."""
    for name in ("INPUT", "BASE", "LOCK", "BASE_LOCK"):
        monkeypatch.setattr(lock, name, tmp_path / name.lower())
    lock.BASE.write_text("numpy==1.26.4\n")
    calls = []

    def run(command, check):
        calls.append(command)
        constraints = Path(command[command.index("-c") + 1]).read_text()
        calls.append(constraints)
        report = _report(("scipy", "1.17.1", "aa"), ("numpy", "1.26.4", "bb"))
        Path(command[command.index("--report") + 1]).write_text(json.dumps(report))

    monkeypatch.setattr(lock.subprocess, "run", run)
    return calls


def test_main_writes_both_locks_for_glue_s_target(fake_pip):
    assert lock.main([]) == 0
    command, constraints = fake_pip
    assert command[command.index("--python-version") + 1] == "3.11"
    assert [command[i + 1] for i, a in enumerate(command) if a == "--platform"] == list(
        lock.PLATFORMS
    )
    assert {"--dry-run", "--only-binary=:all:", "--ignore-installed"} <= set(command)
    assert lock.pins(lock.LOCK.read_text()) == {"scipy": "1.17.1"}
    assert lock.pins(lock.BASE_LOCK.read_text()) == {"numpy": "1.26.4"}
    assert constraints == f"-c {lock.BASE}\n"


def test_current_pins_are_kept_unless_upgrading(fake_pip):
    lock.LOCK.write_text("scipy==1.17.1 \\\n    --hash=sha256:aa\n")
    lock.main([])
    assert fake_pip[1].splitlines()[1:] == ["scipy==1.17.1"]
    lock.main(["--upgrade"])
    assert fake_pip[3] == f"-c {lock.BASE}\n"


# --- uy_build_wheel ---------------------------------------------------------------------------


def test_the_wheel_is_byte_identical_and_named_for_pip(tmp_path):
    first = wheel.build(tmp_path / "one")
    second = wheel.build(tmp_path / "two")
    assert first.name == "sorteos-0.1.0-py3-none-any.whl"
    assert first.read_bytes() == second.read_bytes()


def test_the_wheel_carries_the_data_files_and_no_bytecode(tmp_path):
    names = zipfile.ZipFile(wheel.build(tmp_path)).namelist()
    assert "sorteos/uy/dq/suites.py" in names
    assert "sorteos/uy/reference/game_rules.csv" in names
    assert "sorteos/uy/games/5_de_oro.yaml" in names
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]


def test_the_record_hashes_every_file(tmp_path):
    zf = zipfile.ZipFile(wheel.build(tmp_path))
    record = zf.read("sorteos-0.1.0.dist-info/RECORD").decode().splitlines()
    assert record[-1] == "sorteos-0.1.0.dist-info/RECORD,,"
    assert len(record) == len(zf.namelist())
    for line in record[:-1]:
        path, digest, size = line.split(",")
        data = zf.read(path)
        expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
        assert (digest, int(size)) == (f"sha256={expected.decode()}", len(data))


def test_the_wheel_declares_no_dependencies(tmp_path):
    metadata = zipfile.ZipFile(wheel.build(tmp_path)).read("sorteos-0.1.0.dist-info/METADATA")
    assert b"Requires-Dist" not in metadata
    assert b"Name: sorteos\nVersion: 0.1.0\n" in metadata


def test_bytecode_in_the_tree_is_left_out(tmp_path):
    source = tmp_path / "src"
    (source / "__pycache__").mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    (source / "stray.pyc").write_bytes(b"\0")
    assert [path for path, _ in wheel.files(source)] == ["sorteos/__init__.py"]


# --- The committed files ----------------------------------------------------------------------


def _committed(name):
    return lock.pins((REQUIREMENTS / name).read_text(encoding="utf-8"))


def test_the_base_lock_is_glue_s_own_versions():
    base = _committed("glue-5.0-base.txt")
    provided = _committed("uy-dq-glue-base.lock")
    assert provided and all(base[name] == version for name, version in provided.items())
    assert {"pandas", "numpy", "pyarrow"} <= set(provided)


def test_nothing_glue_has_goes_into_the_zip():
    base = _committed("glue-5.0-base.txt")
    assert not set(_committed("uy-dq.lock")) & set(base)


def test_every_locked_line_carries_a_hash():
    for name in ("uy-dq.lock", "uy-dq-glue-base.lock"):
        text = (REQUIREMENTS / name).read_text(encoding="utf-8")
        assert text.count("==") == text.count("--hash=sha256:")


def test_gx_is_the_version_the_repo_tests_with():
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    tested = re.search(r'dq = \["great-expectations==([^"]+)"\]', pyproject).group(1)
    assert _committed("uy-dq.txt")["great-expectations"] == tested
    assert _committed("uy-dq.lock")["great-expectations"] == tested
