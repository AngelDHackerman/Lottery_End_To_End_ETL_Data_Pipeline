# TODO PR-013: aws_lakeformation_resource has no `terraform import` support and this
# was set up manually in AWS. Left commented out so `terraform plan` stays a no-op
# during the PR-004 state reconstruction. PR-013 codifies Lake Formation properly
# (resource registration + aws_lakeformation_permissions grants).
# resource "aws_lakeformation_resource" "athena_results_location" {
#   arn      = aws_s3_bucket.athena_results.arn
#   role_arn = aws_iam_role.glue_crawler_role.arn
# }


# data "aws_iam_user" "santa_lucia_dev" {
#   user_name = "santa-lucia-dev"
# }

# data "aws_iam_user" "angel_adming" {
#   user_name = "angel-adming"
# }

# Allow SELECT + DESCRIBE on Database
# resource "aws_lakeformation_permissions" "lf_select_db" {
#   for_each   = {
#     santa = data.aws_iam_user.santa_lucia_dev.arn
#     angel = data.aws_iam_user.angel_adming.arn
#   }

#   principal   = each.value
#   permissions = ["DESCRIBE", "SELECT"]

#   database {
#     name = aws_glue_catalog_database.lottery_db.name
#   }
# }