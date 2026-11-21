# UY-044.1 — what Athena needs to read UY silver: the tables and a workgroup of UY's own.
#
# Until now lottery_uy_db was empty: the silver Lambda writes Parquet to uy/silver/ and the GX
# job reads the files directly (D20), so nothing needed the catalog. Gold does (UY-044.2/.3):
# it is SQL over these tables.
#
# The tables are DECLARED, not crawled (owner, UY-044 3a). Their columns come from
# silver_tables.json, generated from the pyarrow schemas the silver writer enforces
# (scripts/uy_catalog_schema.py; a test fails if the file is stale). Their partitions are
# PROJECTED: Athena derives country=/game=/year= from the table properties, so a year the
# Lambda writes tonight is readable tonight, with no crawler, MSCK or ADD PARTITION.

data "aws_s3_bucket" "athena_results" {
  bucket = "lottery-athena-results-${var.environment}"
}

locals {
  silver_catalog = jsondecode(file("${path.module}/silver_tables.json")).tables

  # silver_<name>: the database also holds gold (D25), as lottery_db does in the main stack.
  silver_table_prefix = "silver_"
}

resource "aws_glue_catalog_table" "silver" {
  for_each = local.silver_catalog

  database_name = aws_glue_catalog_database.uy.name
  name          = "${local.silver_table_prefix}${each.key}"
  description   = "UY silver `${each.key}` (docs/uruguay/DESIGN.md). Schema from sorteos.core.silver; partitions projected."
  table_type    = "EXTERNAL_TABLE"

  # projection.<col>.type plus .values (enum) or .range (integer), flattened from the JSON.
  parameters = merge(
    {
      "EXTERNAL"           = "TRUE"
      "classification"     = "parquet"
      "projection.enabled" = "true"
    },
    merge([
      for column, projection in each.value.projection : {
        for key, value in projection : "projection.${column}.${key}" => value
      }
    ]...)
  )

  dynamic "partition_keys" {
    for_each = each.value.partition_keys
    content {
      name = partition_keys.value.name
      type = partition_keys.value.type
    }
  }

  storage_descriptor {
    location      = "s3://${data.aws_s3_bucket.partitioned.bucket}/${local.silver_prefix}${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = {
        "serialization.format" = "1"
      }
    }

    dynamic "columns" {
      for_each = each.value.columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}

# A workgroup of UY's own (owner, 2026-11-11) rather than Santa Lucía's lottery-wg: that one
# belongs to the main stack, has no scan limit, and mixes both countries' queries and metrics.
resource "aws_athena_workgroup" "uy" {
  #checkov:skip=CKV_AWS_82:enforcing the workgroup configuration makes Athena reject a CTAS that sets external_location, which is how gold is built (PR-021's lesson, UY-044.3); the scan limit below holds either way

  name        = "lottery-uy-wg"
  description = "Uruguay: queries over lottery_uy_db and the gold build (UY-044)."

  configuration {
    enforce_workgroup_configuration    = false
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_scan_limit_bytes

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    # Santa Lucía's results bucket (30-day expiry), under UY's own prefix.
    result_configuration {
      output_location = "s3://${data.aws_s3_bucket.athena_results.bucket}/uy/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
