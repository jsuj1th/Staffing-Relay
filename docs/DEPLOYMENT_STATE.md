# Relay — Live Deployment State

Current production deployment. **Deployed 2026-07-18.** Setup details and
architecture rationale are in [`DEPLOY_SINGLEBOX.md`](DEPLOY_SINGLEBOX.md).

> 🔒 **Secrets are NOT in this file (or git).** The DB password lives in the
> gitignored `infra/singlebox/.env`. App secrets (SECRET_KEY, DATABASE_URL,
> Telnyx keys) live in AWS SSM Parameter Store under `/relay/prod/*`.

## Environment

| | |
|---|---|
| AWS account | `027252077890` |
| Region | `us-east-1` |
| IAM user | `deployer` |
| Deployment type | Single-box (EC2 + RDS). ~$28/mo. |

## Live resources

| Resource | Value |
|----------|-------|
| **App URL** | http://44.206.223.36 |
| Public IP (Elastic) | `44.206.223.36` |
| EC2 instance ID | `i-09b43baf391e05527` |
| Instance type | `t3.small` |
| RDS endpoint | `relay-db.c25w8oqkyed6.us-east-1.rds.amazonaws.com` |
| RDS database / user | `lms_db` / `lms_user` |
| ECR repo | `027252077890.dkr.ecr.us-east-1.amazonaws.com/relay` |
| Telnyx webhook URL | http://44.206.223.36/webhooks/telnyx/ |

## Architecture

- One EC2 box runs the Django app in Docker (gunicorn on :8000, mapped to :80).
- Static files served by **WhiteNoise** (no S3).
- Postgres on **managed RDS** (single-AZ, 7-day automated backups). Survives
  instance death.
- **No Celery / Redis.** Batched SMS (shift assignments) are flushed by a cron
  job on the box running `manage.py send_pending_sms` **every 10 minutes**
  (`/etc/cron.d/relay-sms`).
- Settings module: `lms.settings.singlebox`.
- Connect to the box via **SSM Session Manager** (no SSH keys / no port 22).

## Common operations

```bash
# --- from repo root ---
./scripts/deploy-singlebox.sh                      # build + push + deploy new code

# --- terraform (cd infra/singlebox && source .env first) ---
terraform output                                   # show all live values
terraform destroy                                  # tear down (STOPS billing, deletes DB)

# --- shell into the box ---
aws ssm start-session --target i-09b43baf391e05527
#   on box (needs sudo — files are root-owned):
sudo docker compose -f /opt/relay/docker-compose.yml logs -f web    # app logs
sudo cat /var/log/relay-sms.log                                     # SMS cron log
cd /opt/relay && sudo docker compose run --rm web python manage.py <cmd>
```

## Updating secrets

```bash
aws ssm put-parameter --name /relay/prod/telnyx_api_key --type SecureString --overwrite --value '<new>'
# then redeploy so the box rewrites its .env:
./scripts/deploy-singlebox.sh
```

## Known follow-ups

- [ ] **HTTPS** — currently plain HTTP (passwords in cleartext). Add a domain +
      Caddy (auto Let's Encrypt) before real staff use.
- [ ] **Commit the deploy files** — `infra/singlebox/`, `scripts/`,
      `lms/settings/singlebox.py`, `docker-compose.prod.yml`, `.dockerignore`,
      the `dateparser` requirements fix, and `send_pending_sms` command.
- [ ] The alternate full ECS stack (`infra/terraform/`, ~$100/mo) is unused but
      still present if the app ever outgrows one box.
