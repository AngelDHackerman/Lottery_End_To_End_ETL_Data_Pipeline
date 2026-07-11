# Module: catalog
# Glue Data Catalog database + the silver crawlers + the Athena workgroup.
# Migrated from terraform-lottery/Prod/{glue_crawlers.tf, glue_crawlers_silver.tf,
# athena.tf} in PR-012 via cross-state `terraform state rm` (legacy) +
# `terraform import` (here) — nothing is recreated.
# See docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# PR-012 cleanup (see README):
#   - The legacy `processed/` crawlers (premios_crawler, sorteos_crawler) are GONE from
#     code — the transformer writes silver/, not processed/. They were `state rm`'d
#     (left unmanaged in AWS); the S3 prefix `processed/` itself is preserved.
#   - The `null_resource "run_glue_crawlers"` apply-time triggers are GONE — the Step
#     Function starts the crawlers.
#
# The gold crawler (s3://<partitioned>/gold/) is added in PR-022.

# Database in Glue
resource "aws_glue_catalog_database" "lottery_db" {
  name = var.database_name
}

# Crawler for the silver "premios" table
resource "aws_glue_crawler" "premios_silver_crawler" {
  name          = "lottery-premios-silver-crawler"
  role          = var.glue_crawler_role_arn
  database_name = aws_glue_catalog_database.lottery_db.name
  table_prefix  = "silver_premios_"

  s3_target {
    path = "s3://${var.partitioned_bucket_name}/silver/premios/"
  }

  configuration = jsonencode({
    Version = 1.0,
    CrawlerOutput = {
      Partitions = {
        AddOrUpdateBehavior = "InheritFromTable"
      }
    }
  })

  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "LOG"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_NEW_FOLDERS_ONLY"
  }
}

# Crawler for the silver "sorteos" table
resource "aws_glue_crawler" "sorteos_silver_crawler" {
  name          = "lottery-sorteos-silver-crawler"
  role          = var.glue_crawler_role_arn
  database_name = aws_glue_catalog_database.lottery_db.name
  table_prefix  = "silver_sorteos_"

  s3_target {
    path = "s3://${var.partitioned_bucket_name}/silver/sorteos/"
  }

  configuration = jsonencode({
    Version = 1.0,
    CrawlerOutput = {
      Partitions = {
        AddOrUpdateBehavior = "InheritFromTable"
      }
    }
  })

  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "LOG"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_NEW_FOLDERS_ONLY"
  }
}

# Athena workgroup used to query the catalog (results land in the storage module's
# athena_results bucket). Lives here because the catalog module owns the query layer;
# it had no assigned module in the roadmap and the legacy folder dies in PR-015.
resource "aws_athena_workgroup" "lottery_wg" {
  name = "lottery-wg"

  configuration {
    result_configuration {
      output_location = "s3://${var.athena_results_bucket_name}/"
    }
  }
}
