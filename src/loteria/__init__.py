"""Loteria Santa Lucia — single source of truth for the ETL pipeline code.

Subpackages:
- extractor:   scrapes loteria.org.gt and lands raw .txt in S3 (runs as the Lambda)
- parser:      pure text -> records parsing of the HEADER/BODY .txt format
- transformer: raw .txt -> Silver Parquet (runs as the Glue pythonshell job)
- common:      shared AWS helpers (Secrets Manager, S3)
"""
