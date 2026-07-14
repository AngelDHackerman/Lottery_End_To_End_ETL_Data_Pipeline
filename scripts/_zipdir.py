"""Zip the current working directory into the archive named by argv[1].

Used by build_lambda_package.sh / build_glue_package.sh instead of the `zip` binary,
which is not installed everywhere (notably bare WSL images).

Entries are stored with deterministic timestamps and sorted order so an unchanged
tree always produces a byte-identical zip — otherwise Terraform's `source_code_hash`
would churn on every rebuild and redeploy the Lambda for no reason.
"""

import os
import sys
import zipfile

FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


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
            info.external_attr = (os.stat(rel).st_mode & 0xFFFF) << 16
            with open(rel, "rb") as handle:
                archive.writestr(info, handle.read())

    print(f"    {len(paths)} entries -> {out}")


if __name__ == "__main__":
    main()
