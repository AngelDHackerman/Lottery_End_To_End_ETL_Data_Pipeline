# MOVED in PR-007 → terraform/modules/storage/
#
# All S3 buckets that used to live here (lottery_partitioned, lottery_simple,
# lambda_code_zip, athena_results, and their versioning / SSE / public-access-block /
# lifecycle sub-resources) were migrated to the storage module via cross-state
# `terraform state rm` (here) + `terraform import` (into the main stack). No bucket was
# recreated. See docs/runbooks/PR-007-storage-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
