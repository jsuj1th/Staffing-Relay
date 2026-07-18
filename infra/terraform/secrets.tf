# Real values are set out-of-band via `aws ssm put-parameter --overwrite`
# (see README.md). Terraform only creates the parameter and then ignores
# further value changes so it doesn't clobber what ops sets manually.

resource "aws_ssm_parameter" "secret_key" {
  name  = "/relay/prod/secret_key"
  type  = "SecureString"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}

resource "aws_ssm_parameter" "database_url" {
  name  = "/relay/prod/database_url"
  type  = "SecureString"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}

resource "aws_ssm_parameter" "redis_url" {
  name  = "/relay/prod/redis_url"
  type  = "SecureString"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}

resource "aws_ssm_parameter" "telnyx_api_key" {
  name  = "/relay/prod/telnyx_api_key"
  type  = "SecureString"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}

resource "aws_ssm_parameter" "telnyx_public_key" {
  name  = "/relay/prod/telnyx_public_key"
  type  = "SecureString"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}

resource "aws_ssm_parameter" "telnyx_phone_number" {
  name  = "/relay/prod/telnyx_phone_number"
  type  = "String"
  value = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = local.common_tags
}
