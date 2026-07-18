# Relay — Single-Box Deploy (~$28/mo)

The cheap, simple deployment for ~50 occasional users: **one EC2 instance runs
the Django app in Docker, Postgres lives on managed RDS.** No ALB, no NAT, no
Celery, no Redis.

```
Internet ──HTTP:80──► EC2 (t3.small)              RDS PostgreSQL (db.t4g.micro)
                       └─ web container  ───5432──► managed DB, daily backups
                          static via WhiteNoise
                       └─ cron: flush batched SMS every 10 min
```

**Why no Celery/Redis:** the SMS queue is a database table (`NotificationQueue`).
A cron job runs `manage.py send_pending_sms` every 10 min to flush due batches —
that's all Celery would have done here.

**Cost:** EC2 t3.small ~$15 + RDS db.t4g.micro ~$13 + EIP/EBS ~$1 = **~$28/mo**.
Data survives the instance dying (RDS is separate, with 7-day backups).

---

## One-time setup

### 1. Provision the infra

```bash
cd infra/singlebox
terraform init
export TF_VAR_db_password='<a-strong-password>'
terraform plan      # review
terraform apply     # ~10 min (RDS is the slow part)
```

Outputs you'll use:

```bash
terraform output          # public_ip, app_url, rds_endpoint, ecr_repository_url, instance_id
```

Terraform auto-generates `SECRET_KEY` and `DATABASE_URL` into SSM Parameter
Store. You only need to set the Telnyx secrets:

### 2. Set the Telnyx secrets (once)

```bash
aws ssm put-parameter --name /relay/prod/telnyx_api_key      --type SecureString --overwrite --value '<KEY>'
aws ssm put-parameter --name /relay/prod/telnyx_public_key   --type SecureString --overwrite --value '<KEY>'
aws ssm put-parameter --name /relay/prod/telnyx_phone_number --type String       --overwrite --value '+1XXXXXXXXXX'
```

### 3. First deploy (build + push + start)

```bash
scripts/deploy-singlebox.sh
```

This builds the image (for x86), pushes to ECR, and runs the app on the box
(pulls image, writes `.env` from SSM, runs migrations).

### 4. Create an admin user

Shell into the box (no SSH key needed — uses SSM Session Manager):

```bash
aws ssm start-session --target "$(cd infra/singlebox && terraform output -raw instance_id)"
# then on the box:
cd /opt/relay && docker compose run --rm web python manage.py createsuperuser
exit
```

### 5. Open it

```bash
cd infra/singlebox && terraform output -raw app_url
```

Point your Telnyx webhook at `http://<public_ip>/webhooks/telnyx/`.

---

## Everyday operations

**Deploy new code:** commit, then

```bash
scripts/deploy-singlebox.sh
```

**View logs:**

```bash
aws ssm start-session --target <instance_id>
cd /opt/relay && docker compose logs -f web        # app logs
cat /var/log/relay-sms.log                          # the 10-min SMS cron
```

**Run a management command:**

```bash
cd /opt/relay && docker compose run --rm web python manage.py <command>
```

**The SMS batch cron** is at `/etc/cron.d/relay-sms` (runs every 10 min). Change
the schedule there if needed.

---

## Backups & recovery

- **Automated:** RDS keeps 7 days of daily backups + point-in-time restore.
- **Instance dies:** `terraform apply` recreates the EC2 box; it reconnects to
  the same RDS. Then `scripts/deploy-singlebox.sh` to restart the app. Data is
  untouched (it was never on the box).
- **Manual snapshot before risky changes:**
  ```bash
  aws rds create-db-snapshot --db-instance-identifier relay-db --db-snapshot-identifier relay-manual-$(date +%Y%m%d)
  ```

---

## Adding a domain + HTTPS later

The box currently serves plain **HTTP** — fine for testing, but login passwords
travel in cleartext, so add TLS before real staff use.

Easiest path: put **Caddy** in front (auto Let's Encrypt certs). Ask and I'll
add a Caddy container to the compose file and a `Caddyfile` once you have a
domain pointing at the EIP.

---

## Tear it all down (stops billing)

```bash
cd infra/singlebox && terraform destroy
```

> This deletes the database too. Take a final RDS snapshot first if you want to
> keep the data.

---

## What this replaced

The full ECS stack in `infra/terraform/` (~$100/mo: ALB + NAT + ECS + RDS +
ElastiCache) is still there if you ever outgrow one box. For 50 occasional users
this single-box setup does the same job at ~1/4 the cost.
