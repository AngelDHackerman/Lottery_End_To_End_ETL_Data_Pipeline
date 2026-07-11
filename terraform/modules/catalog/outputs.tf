# Outputs exposed by the "catalog" module.
# Consumed by the orchestration module (crawler names in the Step Function), the iam
# module (narrowed glue:StartCrawler grant), and lake-formation (PR-013, db name).

output "db_name" {
  description = "Name of the Glue catalog database."
  value       = aws_glue_catalog_database.lottery_db.name
}

output "premios_silver_crawler_name" {
  description = "Name of the silver premios crawler."
  value       = aws_glue_crawler.premios_silver_crawler.name
}

output "sorteos_silver_crawler_name" {
  description = "Name of the silver sorteos crawler."
  value       = aws_glue_crawler.sorteos_silver_crawler.name
}

output "athena_workgroup_name" {
  description = "Name of the Athena workgroup."
  value       = aws_athena_workgroup.lottery_wg.name
}
