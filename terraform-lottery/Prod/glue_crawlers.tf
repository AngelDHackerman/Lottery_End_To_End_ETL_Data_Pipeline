# Database in Glue
resource "aws_glue_catalog_database" "lottery_db" {
  name = "lottery_santalucia_db"
}

# Crawler pointing to partitioned S3 bucket "Premios" section
resource "aws_glue_crawler" "premios_crawler" {
  name              = "lottery-premios-crawler"
  role              = aws_iam_role.glue_crawler_role.arn
  database_name     = aws_glue_catalog_database.lottery_db.name
  table_prefix      = "premios_"

  s3_target {
    path = "s3://lottery-partitioned-storage-prod/processed/premios/"
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

# Crawler pointing to partitioned S3 bucket "Sorteos" section
resource "aws_glue_crawler" "sorteos_crawler" {
  name          = "lottery-sorteos-crawler"
  role          = aws_iam_role.glue_crawler_role.arn
  database_name = aws_glue_catalog_database.lottery_db.name
  table_prefix  = "sorteos_"

  s3_target {
    path = "s3://lottery-partitioned-storage-prod/processed/sorteos/"
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

# Execute the crawlers
resource "null_resource" "run_glue_crawlers" {
  provisioner "local-exec" {
    command = <<EOT
      aws glue start-crawler --name lottery-premios-crawler
      aws glue start-crawler --name lottery-sorteos-crawler
    EOT
  }

  depends_on = [ 
    aws_glue_crawler.premios_crawler,
    aws_glue_crawler.sorteos_crawler
   ]
}