# The ECR repository for the silver Lambda's image (UY-041.2). DESIGN.md D29.
#
# The silver Lambda ships as a container image because its dependencies measure 222 MB for
# Linux and Python 3.12 (pyarrow alone is 156 MB), 28 MB short of the 250 MB zip limit. The
# image itself is built and pushed in UY-042.
#
# - Tags are IMMUTABLE: every push gets a new tag (the git SHA), so a tag always names the same
#   image and going back is pointing the function at an older tag. There is no `latest`.
# - The lifecycle policy keeps the 5 most recent images (owner, UY-041.2): enough to go back
#   if a new image goes wrong, and storage stays near zero.
# - Scan on push uses ECR's basic scanning, which is free.

resource "aws_ecr_repository" "silver" {
  name                 = "lottery-uy-silver-${var.environment}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # KMS with the AWS managed key (aws/ecr): no monthly cost and Lambda pulls it without extra
  # grants. Encryption cannot be changed after creation, so it is set here, once.
  encryption_configuration {
    encryption_type = "KMS"
  }
}

resource "aws_ecr_lifecycle_policy" "silver" {
  repository = aws_ecr_repository.silver.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 5 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_images_to_keep
      }
      action = { type = "expire" }
    }]
  })
}

# Lambda pulls the image as the Lambda service, not as the function's role, so the grant goes
# on the repository. Declared here because otherwise Lambda adds its own statement the first
# time a function is created from the repo, and that statement would be invisible to Terraform.
# Scoped to the silver function by name (it does not exist yet; UY-042 creates it).
data "aws_iam_policy_document" "ecr_silver" {
  statement {
    sid    = "LambdaPullSilverImage"
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "aws:sourceArn"
      values   = ["arn:aws:lambda:${var.aws_region}:${local.account_id}:function:${local.silver_function_name}*"]
    }
  }
}

resource "aws_ecr_repository_policy" "silver" {
  repository = aws_ecr_repository.silver.name
  policy     = data.aws_iam_policy_document.ecr_silver.json
}
