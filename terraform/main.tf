# AWS side of the project: an encrypted, versioned bucket for BI backups, an
# SNS topic for health alerts, and a least-privilege policy for the CI role.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "region" {
  type    = string
  default = "ca-central-1"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique name for the backup bucket"
}

variable "alert_email" {
  type        = string
  description = "Address that receives failed health check alerts"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "bi-platform-ops", managed_by = "terraform" }
  }
}

resource "aws_s3_bucket" "backups" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "tier-then-expire"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "bi-platform-ops-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Attach this to the role your Jenkins agent or GitHub OIDC role assumes.
resource "aws_iam_policy" "ci" {
  name = "bi-platform-ops-ci"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.backups.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "alert_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "ci_policy_arn" {
  value = aws_iam_policy.ci.arn
}
