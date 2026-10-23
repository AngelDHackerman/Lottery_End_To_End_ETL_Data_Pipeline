"""Zip the current working directory into the archive named by argv[1].

Used by all four build_*.sh scripts instead of the `zip` binary,
which is not installed everywhere (notably bare WSL images).

Entries are stored with deterministic timestamps and sorted order so an unchanged
tree always produces a byte-identical zip — otherwise Terraform's `source_code_hash`
would churn on every rebuild and redeploy the Lambda for no reason.

File modes are normalised too (PR-046.2): 0644, or 0755 if the owner can execute. The
zip stores each file's unix mode, and the mode on disk depends on the umask of whatever
shell ran `make build`. On 2026-10-22 a `umask 077` left over from a secret edit turned
every entry into 0600: same files, same bytes, new hashes — `make deploy` planned a new
Lambda layer and a redeployed extractor. Worse than churn, Lambda reads the code as a
user that does not own it, so 0600 files can fail at import with Permission denied.
"""

import os
import stat
import sys
import zipfile

FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def normalised_mode(st_mode: int) -> int:
    """Regular-file mode with the umask taken out: 0644, or 0755 if owner-executable."""
    perms = 0o755 if st_mode & stat.S_IXUSR else 0o644
    return stat.S_IFREG | perms


def main() -> None:
    out = sys.argv[1]
    paths = []
    for root, dirs, files in os.walk("."):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            paths.append(os.path.relpath(full, "."))
    paths.sort()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in paths:
            info = zipfile.ZipInfo(rel, date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = normalised_mode(os.stat(rel).st_mode) << 16
            with open(rel, "rb") as handle:
                archive.writestr(info, handle.read())

    print(f"    {len(paths)} entries -> {out}")


if __name__ == "__main__":
    main()
