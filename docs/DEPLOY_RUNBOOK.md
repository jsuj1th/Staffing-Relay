# Relay — Deploy Runbook (small scale)

Practical step-by-step to deploy Relay to AWS. Sized for **~50 users, occasional
use** — no autoscaling, no HA, single of everything. For the architecture
rationale see [`deployment.md`](deployment.md).

> **Is this stack overkill?** For 50 occasional users, yes, a bit — ECS +
> RDS + Redis + ALB + NAT runs ~**$100/mo idle**. A single small EC2/Lightsail
> box running the existing `docker-compose.yml` would be ~$15/mo. We went with
> ECS because it's already built and hands-off to run. If cost matters more than
> convenience, ask and we'll do the single-box path instead.

---

## What gets created

| Component | Purpose | Size |
|-----------|---------|------|
| VPC (2 AZs, 1 NAT) | Network | ALB needs 2 AZs; 1 NAT to save cost |
| ECS Fargate | Runs Django (`web`) + Celery worker | 1 web task, 1 celery task |
| RDS PostgreSQL | Database | `db.t4g.micro`, single-AZ |
| ElastiCache Redis | Celery broker | `cache.t4g.micro` |
| ALB | Public entrypoint | HTTP-only until a domain is added |
| S3 | Static files | 1 bucket |
| ECR | Docker image registry | 1 repo |
| SSM Parameter Store | Secrets | 6 params |

**Cost estimate: ~$85–100/month** (NAT ~$32 and ALB ~$18 are the fixed floor;
they run whether anyone uses the app or not).

---

## Prerequisites (already done ✅)

- [x] `aws` CLI + `terraform` installed
- [x] AWS authenticated (`aws sts get-caller-identity` → account `027252077890`)
- [x] Region set to `us-east-1`
- [x] `terraform.tfvars` filled in (HTTP-only, `web_desired_count = 1`)
- [x] Code fixes applied (see [Appendix](#appendix-what-was-fixed))

---

## Deploy steps

All commands run from `infra/terraform/` unless noted.

### 1. Create the infrastructure

```bash
cd infra/terraform
terraform plan     # review: should say "56 to add, 0 to destroy"
terraform apply    # type 'yes' — takes ~15–20 min (RDS is slow)
```

Grab the outputs when it finishes:

```bash
terraform output
# note: alb_dns_name, ecr_repository_url, rds_endpoint, redis_endpoint
```

### 2. Load the real secrets into SSM

Build `database_url` / `redis_url` from the endpoints above.

```bash
aws ssm put-parameter --name /relay/prod/secret_key --type SecureString --overwrite \
  --value "$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')"

aws ssm put-parameter --name /relay/prod/database_url --type SecureString --overwrite \
  --value 'postgres://lms_user:<DB_PASSWORD>@<rds_endpoint>/lms_db'

aws ssm put-parameter --name /relay/prod/redis_url --type SecureString --overwrite \
  --value 'redis://<redis_endpoint>:6379/0'

aws ssm put-parameter --name /relay/prod/telnyx_api_key    --type SecureString --overwrite --value '<KEY>'
aws ssm put-parameter --name /relay/prod/telnyx_public_key --type SecureString --overwrite --value '<KEY>'
aws ssm put-parameter --name /relay/prod/telnyx_phone_number --type String     --overwrite --value '+1XXXXXXXXXX'
```

> `<DB_PASSWORD>` is the value in `terraform.tfvars`. The RDS username is
> `lms_user` and DB name `lms_db` (see `rds.tf`).

### 3. Push the first Docker image

```bash
cd /Users/sujithjulakanti/Desktop/LMS          # repo root
ACCOUNT=027252077890
REPO=$(cd infra/terraform && terraform output -raw ecr_repository_url)

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com"

docker build -t "$REPO:latest" .
docker push "$REPO:latest"
```

Force the services to pick up the image:

```bash
aws ecs update-service --cluster hospital-lms-cluster --service hospital-lms-web    --force-new-deployment
aws ecs update-service --cluster hospital-lms-cluster --service hospital-lms-celery --force-new-deployment
```

### 4. Run database migrations (one-off)

```bash
SUBNETS=$(cd infra/terraform && terraform output -json private_subnet_ids | tr -d '[]" ' )
SG=$(cd infra/terraform && terraform output -raw app_security_group_id)

aws ecs run-task --cluster hospital-lms-cluster \
  --task-definition hospital-lms-migrate --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
```

Check it succeeded in CloudWatch log group `/ecs/hospital-lms-migrate`.

> After this first manual run, the GitHub Actions pipeline runs migrations
> automatically on every push to `main` (see step 6).

### 5. Open the app

```bash
cd infra/terraform && terraform output -raw alb_dns_name
```

Open `http://<that-name>` in a browser. Create an admin user if needed:

```bash
# run as a one-off task, or temporarily via the migrate task def with a shell override
```

---

## Ongoing deploys (CI)

After the manual first deploy, everything is automatic:

1. In GitHub → repo Settings → Secrets → Actions, add `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` (the `deployer` user's keys, or a dedicated CI user).
2. `git push origin main` → tests run → image builds → migrations run → web
   service rolls out. See `.github/workflows/deploy.yml`.

---

## Adding a domain + HTTPS later

1. Buy a domain (Route 53 or anywhere).
2. Request a **free ACM certificate** in `us-east-1` for it; validate via DNS.
3. In `terraform.tfvars`:
   ```hcl
   allowed_hosts       = "relay.yourdomain.com"
   acm_certificate_arn = "arn:aws:acm:us-east-1:027252077890:certificate/xxxx"
   ```
4. `terraform apply` — the ALB switches to HTTPS automatically, and Django flips
   `HTTPS_ENABLED` on (secure cookies, HSTS, HTTP→HTTPS redirect). No code change.
5. Point a Route 53 ALIAS record at the ALB DNS name.

⚠️ **Until then, the app runs over plain HTTP — login passwords travel in
cleartext.** Fine for testing; add the domain before real staff use it.

---

## Tear it all down

Stops all billing (destroys everything, including the database):

```bash
cd infra/terraform && terraform destroy
```

---

## Appendix: what was fixed

- `production.py`: removed hardcoded AWS key env reads (now uses the ECS task
  IAM role); gated HTTPS/secure-cookie/HSTS behind `HTTPS_ENABLED`; added
  `CSRF_TRUSTED_ORIGINS` for HTTP-mode login.
- Deleted stray `lms/settings.py` (was shadowed by the `lms/settings/` package).
- `alb.tf` + `variables.tf`: ALB serves plain HTTP when no cert is set, HTTPS
  when one is.
- `ecs.tf`: injects `HTTPS_ENABLED` + `CSRF_TRUSTED_ORIGINS`.
- `deploy.yml`: added the DB-migrate step before each rollout.
- `.gitignore`: excludes `terraform.tfvars` + state (they hold secrets).
