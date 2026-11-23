# The manifest in DynamoDB (UY-041.2). DESIGN.md D28 and P16.
#
# One table holds both of SQLite's tables (core/manifest.py):
#
#   pk                    sk                          what
#   <source>#<YYYY-MM-DD> STATE                       the manifest row of that key
#   <source>#<YYYY-MM-DD> LOG#<fetched_at>#<n>        one row of fetch_log
#
# - history() is a Query on pk with sk begins_with "LOG#", newest first.
# - record() writes the STATE item and its LOG# item in one TransactWriteItems.
# - open_keys() is a Query on the sparse index: only a STATE item whose state is not final
#   (not_yet_published, error) carries the `open` attribute, so the index holds a few dozen
#   items, never the ~22,000 of the table. record() sets `open` = "1" or removes it with the
#   state. Overrides (manual_overrides.csv) are still applied in the code, as in SQLite.
# - summary() and date_range() Scan the STATE items once per run (fractions of a cent).
#
# The attribute names above are the contract the DynamoDB backend of UY-042 follows.

resource "aws_dynamodb_table" "manifest" {
  name         = "lottery-uy-manifest-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  attribute {
    name = "open"
    type = "S"
  }

  attribute {
    name = "draw_date"
    type = "S"
  }

  # Sparse: an item without `open` is not in the index. Sorted by draw_date so open_keys()
  # comes back oldest first, as the Protocol promises; `state` rides along because the
  # override check needs it.
  global_secondary_index {
    name               = "open-keys"
    hash_key           = "open"
    range_key          = "draw_date"
    projection_type    = "INCLUDE"
    non_key_attributes = ["state"]
  }

  # D28: the reason for DynamoDB over SQLite-in-S3 is a history that can be recovered. PITR
  # keeps 35 days of it; deletion protection and prevent_destroy keep a plan from dropping
  # the table (the SQLite file is the only other copy, and only until UY-042 migrates it).
  point_in_time_recovery {
    enabled = true
  }

  deletion_protection_enabled = true

  # Encrypted at rest with the AWS managed key (aws/dynamodb), which costs nothing. A customer
  # managed key adds $1/month for a table whose content is public lottery results.
  #checkov:skip=CKV_AWS_119:public data; the AWS managed KMS key is enough and a CMK costs $1/month
  server_side_encryption {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
