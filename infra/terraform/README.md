# Relay (hospital-lms) — Terraform

> ⚠️ These `.tf` files are **starter scaffolding authored without a local
> Terraform binary to validate them**. Run `terraform fmt`, `terraform
> validate`, and review a `terraform plan` before any `apply`, and treat the
> first apply as a staging exercise.

See `/docs/deployment.md` for the full architecture writeup this stack
implements.

## Prereqs

- Terraform >= 1.5
- AWS credentials with admin-ish rights for the initial apply
- An ACM certificate ARN for your domain (in `us-east-1`)
- (Optional, for remote state) an S3 bucket + DynamoDB table — backend is
  commented out in `versions.tf`; uncomment and fill in to enable, then
  `terraform init -migrate-state`.

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in: allowed_hosts, acm_certificate_arn, db_password
terraform init
terraform plan
terraform apply
```

## Bootstrap secrets (after the first apply)

Real values never live in Terraform — they're set directly in SSM:

```bash
aws ssm put-parameter --name /relay/prod/secret_key       --type SecureString --value '<django-secret>' --overwrite
aws ssm put-parameter --name /relay/prod/database_url      --type SecureString --value 'postgres://…'    --overwrite
aws ssm put-parameter --name /relay/prod/redis_url         --type SecureString --value 'redis://…'       --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_api_key    --type SecureString --value 'KEY…'            --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_public_key --type SecureString --value '…'               --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_phone_number --type String     --value '+1…'             --overwrite
```

`database_url` / `redis_url` are built from the `rds_endpoint` / `redis_endpoint`
outputs of this stack.

## First deploy

Push to `main` (or run the CI workflow): image builds, lands in ECR, the
`hospital-lms-migrate` task runs via `aws ecs run-task` (see
`docs/deployment.md`), then the web and celery services roll out.
