# Database in Glue
# resource "aws_glue_catalog_database" "lottery_db" {
#  name = "lottery_santalucia_db"
# }

# Crawler pointing to partitioned S3 bucket "Premios" section
resource "aws_glue_crawler" "premios_silver_crawler" {
  name              = "lottery-premios-silver-crawler"
  role              = aws_iam_role.glue_crawler_role.arn
  database_name     = aws_glue_catalog_database.lottery_db.name
  table_prefix      = "silver_premios_"

  s3_target {
    path = "s3://lottery-partitioned-storage-prod/silver/premios/"
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
resource "aws_glue_crawler" "sorteos_silver_crawler" {
  name          = "lottery-sorteos-silver-crawler"
  role          = aws_iam_role.glue_crawler_role.arn
  database_name = aws_glue_catalog_database.lottery_db.name
  table_prefix  = "silver_sorteos_"

  s3_target {
    path = "s3://lottery-partitioned-storage-prod/silver/sorteos/"
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

# Execute the crawlers once they are deployed
resource "null_resource" "run_silver_glue_crawlers" {
  provisioner "local-exec" {
    command = <<EOT
      aws glue start-crawler --name lottery-premios-silver-crawler
      aws glue start-crawler --name lottery-sorteos-silver-crawler
    EOT
  }

  depends_on = [ 
    aws_glue_crawler.premios_silver_crawler,
    aws_glue_crawler.sorteos_silver_crawler
   ]
}