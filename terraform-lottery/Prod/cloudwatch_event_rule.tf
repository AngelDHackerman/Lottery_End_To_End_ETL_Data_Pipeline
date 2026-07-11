# DELETED in PR-012 (the duplicate weekly trigger).
#
# aws_cloudwatch_event_rule.weekly_trigger ("weekly-etl-lottery-trigger-prod",
# cron(0 14 ? * 6 *), Sat 08:00 Guatemala) duplicated the kept Monday rule
# ("lottery-etl-weekly-trigger-prod", now in terraform/modules/orchestration/) — two
# rules ran the pipeline twice a week. This one stays in the LEGACY state on purpose so
# `terraform apply` here DESTROYS it (the one deliberate destroy of the migration).
# See docs/runbooks/PR-012-catalog-orchestration-migration.md, Step 3.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
