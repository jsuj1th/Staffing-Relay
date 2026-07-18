# Static asset bucket for django-storages (S3Boto3Storage), referenced by
# STATIC_URL in lms/settings/production.py.
#
# ponytail: public-read via bucket policy (not ACLs) is the simplest thing
# that serves static assets over a public STATIC_URL. It makes every object
# in this bucket world-readable — fine for compiled CSS/JS/images, NOT fine
# if anything private ever lands here. If that changes, front the bucket
# with CloudFront + OAC instead and drop the public bucket policy.
resource "aws_s3_bucket" "static" {
  bucket = "${var.project}-${var.environment}-static-${data.aws_caller_identity.current.account_id}"

  tags = local.common_tags
}

resource "aws_s3_bucket_ownership_controls" "static" {
  bucket = aws_s3_bucket.static.id

  rule {
    object_ownership = "BucketOwnerEnforced" # disables ACLs entirely; access is via bucket policy only
  }
}

resource "aws_s3_bucket_public_access_block" "static" {
  bucket = aws_s3_bucket.static.id

  # Block ACL-based public access; allow the policy below to grant public reads.
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "static" {
  bucket = aws_s3_bucket.static.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadStaticObjects"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.static.arn}/*"
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.static]
}
