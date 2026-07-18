# Relay — AWS Deployment Architecture

Target: **ECS Fargate** in **us-east-1**, fronted by an ALB, backed by RDS
PostgreSQL and ElastiCache Redis, with static files on S3 and logs in
CloudWatch. This matches the intent already encoded in
`.github/workflows/deploy.yml`, `Dockerfile`, and `lms/settings/production.py`.

> Starter-grade defaults are chosen for a single environment that runs
> cheaply and correctly. Production-hardening items (multi-AZ, autoscaling,
> WAF, blue/green) are listed at the end and left as deliberate follow-ups.

## Topology

```
                         Internet
                            │  HTTPS (443)
                            ▼
                   ┌──────────────────┐
                   │  ALB (public)    │  health check: GET /health/
                   └──────────────────┘
                            │  HTTP 8000
             ┌──────────────┴───────────────┐
             ▼                               ▼
   ECS service: hospital-lms-web    ECS service: hospital-lms-celery
   (Fargate, private subnets)       (Fargate, private subnets)
   gunicorn, 2 tasks                celery worker, 1 task
             │        │        │                    │
             │        │        └──────────┬─────────┘
             ▼        ▼                    ▼
        RDS Postgres  S3 (static)     ElastiCache Redis
        (private)     django-storages (private, Celery broker + result)
             ▲
             │  one-off ECS task "hospital-lms-migrate"
             └── runs `manage.py migrate` on each release (before web rollout)

  Images: GitHub Actions → ECR (hospital-lms) → ECS
  Logs:   all tasks → stdout → CloudWatch Logs
  Config: SSM Parameter Store (SecureString) → injected as task-def secrets
```

## Components

| Concern | AWS resource | Starter sizing | Notes |
|---|---|---|---|
| Container images | ECR repo `hospital-lms` | — | scan-on-push on |
| Orchestration | ECS **Fargate** cluster `hospital-lms-cluster` | — | no EC2 to manage |
| Web | ECS service `hospital-lms-web` | 512 CPU / 1024 MB, **2 tasks** | gunicorn, port 8000 |
| Worker | ECS service `hospital-lms-celery` | 256 CPU / 512 MB, **1 task** | `celery -A lms worker` |
| Migrations | ECS task `hospital-lms-migrate` | 256 / 512, run-once | `manage.py migrate`, invoked by the pipeline |
| Load balancer | ALB (public subnets) | — | HTTPS listener; needs an ACM cert ARN |
| Database | RDS PostgreSQL 15 | `db.t4g.micro`, 20 GB gp3, single-AZ | private subnets; automated backups 7 days |
| Cache/broker | ElastiCache Redis 7 | `cache.t4g.micro`, 1 node | private subnets; Celery broker + result backend |
| Static files | S3 bucket | — | `django-storages` (already wired in `production.py`) |
| Secrets/config | SSM Parameter Store (SecureString) | — | injected into task defs via `secrets` |
| Logs | CloudWatch Log Groups | 30-day retention | app already logs to stdout |
| Networking | VPC, 2 AZs, public+private subnets, 1 NAT GW, IGW | — | single NAT to keep cost down |

## Request & data flow

1. Client → **ALB** on 443 (TLS terminated at the ALB via ACM cert).
2. ALB → **web tasks** on 8000 (gunicorn), health-checked at `GET /health/`.
3. Web tasks read/write **RDS**, read **S3** for static asset URLs, and
   enqueue async work to **Redis**.
4. **Celery** tasks pull from Redis and hit RDS as needed.
5. **Telnyx** posts inbound SMS webhooks to `https://<domain>/webhooks/telnyx/`
   (public via ALB); the app verifies the Ed25519 signature using
   `TELNYX_PUBLIC_KEY` (see `apps/messaging/views.py`).

## Configuration & secrets

`production.py` reads everything from the environment. In ECS these come from
the task definition — non-secret values inline, secrets referenced from SSM.

| Env var | Source | Secret? |
|---|---|---|
| `DJANGO_SETTINGS_MODULE=lms.settings.production` | task def (inline) | no |
| `ALLOWED_HOSTS` | task def (inline) | no |
| `AWS_S3_REGION_NAME`, `AWS_STORAGE_BUCKET_NAME` | task def (inline) | no |
| `SECRET_KEY` | SSM `/relay/prod/secret_key` | **yes** |
| `DATABASE_URL` | SSM `/relay/prod/database_url` | **yes** |
| `REDIS_URL` | SSM `/relay/prod/redis_url` | **yes** |
| `TELNYX_API_KEY` | SSM `/relay/prod/telnyx_api_key` | **yes** |
| `TELNYX_PUBLIC_KEY` | SSM `/relay/prod/telnyx_public_key` | **yes** |
| `TELNYX_PHONE_NUMBER` | SSM `/relay/prod/telnyx_phone_number` | no-ish |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | **prefer the task IAM role** over static keys | — |

> `production.py` currently reads `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
> explicitly for S3. On ECS, prefer the **task role** (no static keys) — see
> the "hardening" note below to switch `django-storages` to role-based auth.

## Deploy pipeline

Current `deploy.yml`: on push to `main` → run tests → build image → push to
ECR → render new task def with the new image → deploy the **web** service.

**Two required additions** (see gaps below):

1. **Run migrations before the web rollout.** After pushing the image, run the
   one-off `hospital-lms-migrate` task and wait for it to exit 0, *then* deploy
   the web service. Example step:
   ```bash
   aws ecs run-task --cluster hospital-lms-cluster \
     --task-definition hospital-lms-migrate \
     --launch-type FARGATE \
     --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNETS],securityGroups=[$APP_SG],assignPublicIp=DISABLED}" \
     --overrides '{"containerOverrides":[{"name":"migrate","command":["python","manage.py","migrate","--noinput"]}]}'
   # then wait for the task to reach STOPPED with exitCode 0
   ```
2. **Deploy the Celery service too** (the workflow only handles `web`). Add a
   second render+deploy for `hospital-lms-celery`, or use one task def with two
   services.

## Gaps this closes / what remains

Closed by this doc + the Terraform in `infra/terraform/`:

- ✅ Infrastructure-as-code for VPC, ALB, ECS, RDS, Redis, S3, ECR, IAM, SSM.
- ✅ Migration strategy (dedicated one-off ECS task).
- ✅ Celery worker service definition.
- ✅ Secrets in SSM instead of undefined/inline.
- ✅ Fixed a behind-ALB redirect loop: `production.py` now sets
  `SECURE_PROXY_SSL_HEADER` (trust the ALB's `X-Forwarded-Proto`) and exempts
  `/health/` from `SECURE_SSL_REDIRECT`, so real traffic isn't looped and the
  target group's health check gets a 200.

Still your call / follow-ups:

- ⬜ ACM certificate + Route 53 record for the domain (Terraform takes a cert
  ARN variable; issuing the cert + DNS is left out to avoid guessing your
  domain).
- ⬜ Wire the two pipeline steps above into `deploy.yml`.
- ⬜ Decide whether to run inside your org's existing VPC (the Terraform
  creates its own; swap in existing subnet IDs via variables if preferred).

## Using the Terraform (`infra/terraform/`)

**Prereqs:** Terraform ≥ 1.5, AWS creds with admin-ish rights for the initial
apply, an S3 bucket + DynamoDB table if you want remote state (backend is
commented out in `versions.tf` — uncomment and fill in to enable).

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in: allowed_hosts, acm_certificate_arn, db_password
terraform init
terraform plan
terraform apply
```

**Bootstrap secrets after the first apply** (values never live in Terraform):
```bash
aws ssm put-parameter --name /relay/prod/secret_key       --type SecureString --value '<django-secret>' --overwrite
aws ssm put-parameter --name /relay/prod/database_url      --type SecureString --value 'postgres://…'    --overwrite
aws ssm put-parameter --name /relay/prod/redis_url         --type SecureString --value 'redis://…'       --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_api_key    --type SecureString --value 'KEY…'            --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_public_key --type SecureString --value '…'               --overwrite
aws ssm put-parameter --name /relay/prod/telnyx_phone_number --type String     --value '+1…'             --overwrite
```
`DATABASE_URL`/`REDIS_URL` are derived from the RDS and ElastiCache endpoints
that Terraform outputs after apply.

**First deploy:** push to `main` (or run the workflow) — image lands in ECR,
migrations run, web + celery services roll out.

> ⚠️ These `.tf` files are **starter scaffolding authored without a local
> Terraform binary to validate them**. Run `terraform fmt`, `terraform
> validate`, and a `terraform plan` review before any apply, and treat the
> first apply as a staging exercise.

## Rough monthly cost (us-east-1, starter sizing)

Very approximate, on-demand: ALB ~$18, 3 Fargate tasks (web×2 + celery×1) at
these sizes ~$35–45, RDS `db.t4g.micro` ~$13, ElastiCache `cache.t4g.micro`
~$12, 1 NAT gateway ~$32 + data, S3/ECR/CloudWatch a few dollars. **~$120–140/mo**
before traffic. The NAT gateway and ALB are the fixed floor; drop the NAT
(use VPC endpoints) or scale web to 1 task to trim.

## Production-hardening follow-ups (deliberately deferred)

- Multi-AZ RDS + a read replica; longer backup retention / PITR.
- ECS service autoscaling (target-tracking on CPU / ALB request count).
- Switch `django-storages` to the **task IAM role** (drop static AWS keys).
- WAF on the ALB; restrict the Telnyx webhook path by source if feasible.
- Route 53 + ACM automation; blue/green deploys via CodeDeploy.
- ElastiCache with a replica + automatic failover.
- Separate `staging` workspace/environment.
