"""Run the UY fetch Lambda's code FROM ITS ZIP, with only what Lambda would have (UY-043.2.1).

    python scripts/uy_fetch_smoke.py dist/uy/uy_fetch.zip      # or: make uy-fetch-check

#156 deployed a fetch zip whose handler could not even be imported: lambda_fetch → incremental
→ build_silver → pyarrow, which only the silver image has. Every test passed, because the test
venv has pyarrow, and CI only checked that the zip was reproducible, never that it ran.

This unpacks the zip to a temp dir and, in a child Python, refuses every import that is not the
standard library, the zip's own contents or boto3 and its dependencies (the Lambda runtime
brings those). Then it imports the handler and runs a small incremental through the same
``run_incremental`` the handler calls, twice (the second run re-reads a settling page through
``_same_page``), against a fake site, a SQLite manifest and local bronze in the temp dir. So an
import done lazily on the fetch path fails here too, not only one at the top of a module.

Needs no AWS and no network. Exit 0 when the zip runs, 1 when it does not.
"""

from __future__ import annotations

# subprocess runs this same Python on the script this file defines (CHILD).
import subprocess  # nosec B404
import sys
import tempfile
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "uy"

CHILD = r"""
import importlib.abc
import importlib.machinery
import sys
import sysconfig
from pathlib import Path

zip_dir, fixtures, work = (Path(a) for a in sys.argv[1:4])
RUNTIME = {"boto3", "botocore", "jmespath", "s3transfer", "dateutil", "six"}
IN_ZIP = {p.name.split(".")[0] for p in zip_dir.iterdir()}
# Private stdlib modules (_sysconfigdata_*, ...) are not in sys.stdlib_module_names: anything
# whose file lives in the interpreter's own library is the standard library too. Two traps,
# both of which let pyarrow through in the first version of this check: inside a venv
# "platstdlib" is the VENV's lib/python3.X (hence sys.base_prefix), and on some installs
# (actions/setup-python) site-packages sits inside the stdlib directory itself.
_BASE = {k: sys.base_prefix for k in ("base", "platbase", "installed_base", "installed_platbase")}
STDLIB = tuple(
    str(Path(sysconfig.get_path(k, vars=_BASE)).resolve()) + "/" for k in ("stdlib", "platstdlib")
)


def in_stdlib(origin: str) -> bool:
    resolved = Path(origin).resolve()
    return str(resolved).startswith(STDLIB) and not {"site-packages", "dist-packages"} & set(
        resolved.parts
    )


class OnlyWhatLambdaHas(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top in sys.stdlib_module_names or top in IN_ZIP or top in RUNTIME:
            return None  # let the normal finders look for it, the zip first
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec and spec.origin and in_stdlib(spec.origin):
            return None
        raise ModuleNotFoundError(
            f"{name!r} is not in the fetch zip, the standard library or the Lambda runtime"
        )


sys.meta_path.insert(0, OnlyWhatLambdaHas())
sys.path.insert(0, str(zip_dir))

from datetime import UTC, date, datetime, timedelta

from sorteos.core.bronze import BronzeStore
from sorteos.core.http_client import FetchResult
from sorteos.core.manifest import SqliteManifest
from sorteos.uy import lambda_fetch, sources

assert lambda_fetch.__file__.startswith(str(zip_dir)), lambda_fetch.__file__

TODAY = date(2016, 7, 7)
DAY = date(2016, 7, 6)  # a draw of all three games (tests/fixtures/uy)
pages = {
    sources.RESULTADOS.url(TODAY - timedelta(days=back)): (fixtures / "resultados_2025-12-25.html")
    for back in range(7)
}
pages[sources.RESULTADOS.url(DAY)] = fixtures / "resultados_2016-07-06.html"


class FakeSite:
    def get(self, url):
        page = pages.get(url)
        status, body = (200, page.read_bytes()) if page else (404, b"not found")
        headers = {"Content-Type": "text/html; charset=UTF-8"}
        return FetchResult(url, url, status, headers, body, datetime.now(UTC), 0.01)


manifest = SqliteManifest(work / "manifest.sqlite")
store = BronzeStore(work, "uy")
for night in (1, 2):
    report = lambda_fetch.run_incremental(
        manifest, store, FakeSite(), TODAY, pending=None, max_requests=60
    )
    print(f"night {night}: {report['requests']} requests, changed {len(report['changed'])}")
    if night == 1:
        assert ["resultados", DAY.isoformat()] in report["changed"], report
        assert report["years"] == [2016], report
manifest.close()
"""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    zip_path = Path(args[0])
    with tempfile.TemporaryDirectory(prefix="uy-fetch-smoke-") as tmp:
        zip_dir, work = Path(tmp) / "zip", Path(tmp) / "work"
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(zip_dir)  # our own build output, not a download
        work.mkdir()
        # -I: no PYTHONPATH, no user site and no current directory on sys.path.
        # A fixed argv and this same interpreter.
        done = subprocess.run(  # nosec B603
            [sys.executable, "-I", "-c", CHILD, str(zip_dir), str(FIXTURES), str(work)],
            check=False,
        )
    if done.returncode:
        print(f"FAIL: {zip_path} does not run with only what the Lambda has", file=sys.stderr)
        return 1
    print(f"OK: {zip_path} imports and runs the incremental with only what the Lambda has")
    return 0


if __name__ == "__main__":
    sys.exit(main())
