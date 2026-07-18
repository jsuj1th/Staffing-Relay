#!/bin/bash
# Build the image, push to ECR, and (re)deploy on the EC2 box via SSM.
# Run from anywhere: scripts/deploy-singlebox.sh
# Prereqs: infra/singlebox already applied, Docker running, AWS creds set.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/infra/singlebox"
ECR_URL=$(terraform output -raw ecr_repository_url)
INSTANCE_ID=$(terraform output -raw instance_id)
REGISTRY="${ECR_URL%%/*}"

echo "==> ECR login"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Build (linux/amd64 — the EC2 box is x86_64)"
cd "$ROOT"
docker build --platform linux/amd64 -t "$ECR_URL:latest" .

echo "==> Push"
docker push "$ECR_URL:latest"

echo "==> Deploy on the box via SSM"
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["bash /opt/relay/deploy.sh"]' \
  --region "$REGION" --query Command.CommandId --output text)

echo "    command $CMD_ID — waiting..."
aws ssm wait command-executed --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" || true
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' --output text

cd "$ROOT/infra/singlebox"
echo "==> Done → $(terraform output -raw app_url)"
