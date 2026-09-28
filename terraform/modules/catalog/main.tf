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

# --- PR-023: log retention -------------------------------------------------------------
#
# Like Python Shell jobs, crawlers have no per-crawler log group — every crawler in the
# account writes to /aws-glue/crawlers, created by the Glue service with no retention.
# Owning it here (gated by var.manage_shared_glue_log_groups) is the only way to expire
# those logs. The group already exists in prod and must be IMPORTED, not created:
# see docs/runbooks/PR-023-log-retention.md.
resource "aws_cloudwatch_log_group" "crawlers" {
  count = var.manage_shared_glue_log_groups ? 1 : 0

  name              = "/aws-glue/crawlers"
  retention_in_days = var.log_retention_days
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
    # Must be false so the Gold CTAS queries (PR-021) can set their own
    # `external_location` (s3://<partitioned>/gold/<name>/). With the AWS default
    # (true), the workgroup enforces the central output_location below and Athena
    # rejects any CTAS that carries an external_location. SELECT results still
    # default to output_location — only client overrides become allowed.
    enforce_workgroup_configuration = false

    result_configuration {
      output_location = "s3://${var.athena_results_bucket_name}/"
    }
  }
}

# ---------------------------------------------------------------------------------------
# PR-044.2 — the quarantine table, defined here rather than crawled.
# ---------------------------------------------------------------------------------------
# **Why not a crawler, when every other table in this database is crawled.** PR-045.1
# established, against the live account, that the two Silver crawlers cannot evolve a
# schema: `SchemaChangePolicy.UpdateBehavior = "LOG"` detects a change and only writes a log
# line, `CRAWL_NEW_FOLDERS_ONLY` never revisits existing partitions, and
# `Partitions.AddOrUpdateBehavior = "InheritFromTable"` gives a new partition the table's
# schema rather than its files'. A column added to the Parquet never reaches Athena.
#
# Quarantine is the one table in this project whose schema we *define* rather than discover —
# `loteria.common.quarantine.QUARANTINE_COLUMNS` is the source of truth. Inferring it would
# be strictly worse: extra moving parts, a crawler run per week, and a known inability to
# follow the very changes this table exists to record.
#
# ⚠️ The column list below and QUARANTINE_COLUMNS must stay in step. A test asserts it, by
# reading this file — the same technique PR-042.2 used for its alarm pattern, and for the
# same reason: nothing else would notice them drifting apart.
resource "aws_glue_catalog_table" "quarantine" {
  name          = "quarantine_rejects"
  database_name = aws_glue_catalog_database.lottery_db.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification        = "parquet"
    EXTERNAL              = "TRUE"
    "parquet.compression" = "SNAPPY"
  }

  # Hive partition keys. These are carried by the S3 path and are deliberately NOT columns in
  # the Parquet — Glue rejects a table whose columns and partition keys overlap.
  #
  # All three are `string`, including `year` and `sorteo`, which look numeric. A file that
  # fails before its header parses has no year and no sorteo to report, and the writer emits
  # the literal `unknown` rather than inventing one; a typed partition could not hold that.
  # The partition that says "we could not even tell which draw this was" is precisely the one
  # worth keeping.
  partition_keys {
    name = "dataset"
    type = "string"
  }
  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "sorteo"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.partitioned_bucket_name}/quarantine/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "parquet"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name    = "reason"
      type    = "string"
      comment = "Closed vocabulary: section_header (never stored), orphan_vendor_line, unrecognised, malformed_header, unexpected_key"
    }
    columns {
      name    = "line"
      type    = "string"
      comment = "The rejected input, truncated to 120 characters"
    }
    columns {
      name = "position"
      # bigint, not int: pandas writes a Python int as int64, and Athena widens INT to
      # BIGINT but has no supported path in the other direction — so an `int` declaration
      # over 64-bit Parquet data is a read error waiting for the first row written here.
      # Corrected in PR-045.2, before the table had a single row to be wrong about.
      type    = "bigint"
      comment = "1-based line number within the BODY; 0 for file-level rejects"
    }
    columns {
      name    = "source_key"
      type    = "string"
      comment = "The raw/ S3 key the reject came from"
    }
    columns {
      name    = "run_id"
      type    = "string"
      comment = "Step Functions execution name (PR-018 correlation id)"
    }
    columns {
      name    = "parser_version"
      type    = "bigint" # see `position` above (PR-045.2)
      comment = "Which parsing behaviour rejected it (PR-045.1)"
    }
    columns {
      name    = "quarantined_at"
      type    = "timestamp"
      comment = "UTC, timezone-naive, as PR-045.1's ingested_at"
    }
  }
}

# ---------------------------------------------------------------------------------------
# PR-045.2 — the two Silver tables, defined here instead of inferred by the crawlers.
# ---------------------------------------------------------------------------------------
# **Why this had to change hands.** PR-045.1 writes four lineage columns into every new
# Silver Parquet file and Athena could not see a single one of them. Three crawler settings
# compound, each sufficient on its own: `SchemaChangePolicy.UpdateBehavior = "LOG"` (detects
# a schema change, writes a log line, alters nothing), `CRAWL_NEW_FOLDERS_ONLY` (never
# re-examines an existing partition) and `Partitions.AddOrUpdateBehavior = "InheritFromTable"`
# (a new partition is given the *table's* schema, not its files'). The columns were on disk
# and `SELECT run_id FROM silver_sorteos_sorteos` was a column-not-found error.
#
# **The crawlers are NOT being loosened, and that is the design.** The obvious fix —
# `UPDATE_IN_DATABASE` + `CRAWL_EVERYTHING` — hands the schema of the two tables that seven
# gold CTAS queries read to a process that re-infers it from whatever landed in S3 that
# week. The same three settings that hid these columns are exactly what makes a
# Terraform-owned schema safe: a crawler that will not alter a table cannot fight the
# declaration below, and `InheritFromTable` means every partition it registers from now on
# is stamped with *this* schema. It keeps the one job it is still needed for — registering
# the new week's partition — and loses the one it was never good at.
#
# The account agrees: these tables were last updated **2025-12-14**, the day they were
# created, and the crawlers have run every Thursday since. They have not touched the tables
# in nine months.
#
# ⚠️ Both tables ALREADY EXIST and must be IMPORTED, not created. A create would mean Glue
# dropped and rebuilt the table Athena reads, losing all 118 registered partitions.
# See docs/runbooks/PR-045.2-lineage-queryable.md §2 for the two import commands.
#
# ⚠️ The four lineage columns at the end of each table are a contract with
# `loteria.common.lineage.LINEAGE_GLUE_TYPES`, held together by a test that reads this file
# — the same technique PR-044.2 used for the quarantine columns, for the same reason:
# nothing else would notice them drifting apart, and the symptom of drift is a query error
# nine months later.
locals {
  # Appended to BOTH Silver tables, in `LINEAGE_COLUMNS` order, which is also the order the
  # transformer appends them to the frame — so the declaration below matches the physical
  # column order in the Parquet rather than only the names.
  #
  # `parser_version` is **bigint, not int**, and that is not a detail. pandas writes a
  # Python int as int64, so the Parquet holds a 64-bit integer; Athena widens INT to BIGINT
  # but has no supported path in the other direction, so an `int` declaration over int64
  # data is a read error waiting for the first row that exercises it.
  lineage_columns = [
    { name = "run_id", type = "string", comment = "Step Functions execution name (PR-018 correlation id). NULL means the write did not come from a pipeline run" },
    { name = "ingested_at", type = "timestamp", comment = "When the transformer wrote the file. UTC, timezone-naive" },
    { name = "source_key", type = "string", comment = "The raw/ S3 key the row was derived from" },
    { name = "parser_version", type = "bigint", comment = "Which parsing behaviour produced the row (PR-045.1). Bumped by hand" },
  ]
}

resource "aws_glue_catalog_table" "silver_sorteos" {
  name          = "silver_sorteos_sorteos"
  database_name = aws_glue_catalog_database.lottery_db.name
  table_type    = "EXTERNAL_TABLE"

  # The literal the crawler wrote. Declared so the import does not show a field being
  # cleared: Glue's UpdateTable replaces the whole TableInput, so anything omitted here is
  # removed there.
  owner = "owner"

  parameters = {
    classification = "parquet"
    # Partition pruning on `year`/`sorteo`. The crawler set this and it must survive the
    # handover — without it Athena reads every partition for a single-sorteo lookup, which
    # is exactly the query this PR exists to make cheap.
    "partition_filtering.enabled" = "true"
  }

  # Deliberately NOT carried over: the crawler's statistics (`objectCount`, `recordCount`,
  # `sizeKey`, `averageRecordSize`, `CRAWL_RUN_ID`, `UPDATED_BY_CRAWLER`, `typeOfData`,
  # `compressionType`, the two CrawlerSchema*Version keys). They are frozen at the
  # 2025-12-14 crawl — `objectCount` says 79 against 118 partitions — so enshrining them in
  # code would be writing down a number that has been wrong for nine months.

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "sorteo"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.partitioned_bucket_name}/silver/sorteos/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "parquet"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    # --- business columns: exactly what the crawler inferred on 2025-12-14 ---------------
    columns {
      name = "numero_sorteo"
      type = "bigint"
    }
    columns {
      name = "tipo_sorteo"
      type = "string"
    }
    columns {
      name = "fecha_sorteo"
      type = "timestamp"
    }
    columns {
      name = "fecha_caducidad"
      type = "timestamp"
    }
    columns {
      name = "primer_premio"
      type = "bigint"
    }
    columns {
      name = "segundo_premio"
      type = "bigint"
    }
    columns {
      name = "tercer_premio"
      type = "bigint"
    }
    columns {
      name = "reintegro_primer_premio"
      type = "bigint"
    }
    columns {
      name = "reintegro_segundo_premio"
      type = "bigint"
    }
    columns {
      name = "reintegro_tercer_premio"
      type = "bigint"
    }

    # --- PR-045.1 lineage, appended at the end ------------------------------------------
    dynamic "columns" {
      for_each = local.lineage_columns
      content {
        name    = columns.value.name
        type    = columns.value.type
        comment = columns.value.comment
      }
    }
  }
}

resource "aws_glue_catalog_table" "silver_premios" {
  name          = "silver_premios_premios"
  database_name = aws_glue_catalog_database.lottery_db.name
  table_type    = "EXTERNAL_TABLE"

  owner = "owner"

  parameters = {
    classification                = "parquet"
    "partition_filtering.enabled" = "true"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "sorteo"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.partitioned_bucket_name}/silver/premios/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "parquet"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters            = { "serialization.format" = "1" }
    }

    columns {
      name = "numero_sorteo"
      type = "bigint"
    }
    columns {
      name = "numero_premiado"
      type = "bigint"
    }
    columns {
      name = "letras"
      type = "string"
    }
    columns {
      name = "monto"
      type = "double"
    }
    columns {
      name = "vendedor"
      type = "string"
    }
    columns {
      name = "ciudad"
      type = "string"
    }
    columns {
      name = "departamento"
      type = "string"
    }

    dynamic "columns" {
      for_each = local.lineage_columns
      content {
        name    = columns.value.name
        type    = columns.value.type
        comment = columns.value.comment
      }
    }
  }
}
