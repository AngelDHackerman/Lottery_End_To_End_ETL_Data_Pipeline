# CODIFIED in PR-013 → terraform/modules/lake-formation/
#
# This file only ever held commented-out sketches — the real Lake Formation setup was
# done by hand in the console (challanges_faced.md §5) and was never in this stack's
# state. PR-013 codifies it properly in the main stack: silver/ path registration +
# grants to the glue-crawler-role + the gated IAMAllowedPrincipals compat grant.
# See docs/runbooks/PR-013-lake-formation.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
