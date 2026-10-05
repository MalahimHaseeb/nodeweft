#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

REGION="${AWS_REGION:-eu-west-1}"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"
TERRAFORM_DIR=deploy/terraform
SERVICES="auth workflow execution"

value_of() {
  grep -E "^$2=" "$1" | head -1 | cut -d= -f2-
}

for service in $SERVICES; do
  if [ ! -f "$service.prod.env" ]; then
    echo "Missing $service.prod.env. Run deploy/scripts/make-prod-env.sh first."
    exit 1
  fi
  if ! grep -q '^APP_ENV=production$' "$service.prod.env"; then
    echo "$service.prod.env must contain APP_ENV=production"
    exit 1
  fi
done

for key in JWT_SECRET INTERNAL_SERVICE_TOKEN; do
  first=$(value_of auth.prod.env "$key")
  second=$(value_of workflow.prod.env "$key")
  third=$(value_of execution.prod.env "$key")
  if [ -z "$first" ] || [ "$first" != "$second" ] || [ "$first" != "$third" ]; then
    echo "$key must be set and identical in all three prod env files"
    exit 1
  fi
done

if grep -q '^AWS_ACCESS_KEY_ID=' execution.prod.env; then
  echo "Remove the AWS keys from execution.prod.env. The server uses its IAM role."
  exit 1
fi

INSTANCE_ID=$(terraform -chdir="$TERRAFORM_DIR" output -raw instance_id)
DEPLOY_BUCKET=$(terraform -chdir="$TERRAFORM_DIR" output -raw deploy_bucket)
REGISTRY=$(terraform -chdir="$TERRAFORM_DIR" output -raw ecr_registry)

echo "Logging in to ECR"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

for service in $SERVICES; do
  echo "Building $service"
  docker build --platform linux/amd64 -f "services/$service/Dockerfile" -t "$REGISTRY/nodeweft-$service:$TAG" .
  docker push "$REGISTRY/nodeweft-$service:$TAG"
done

echo "Storing environment files in SSM Parameter Store"
for service in $SERVICES; do
  aws ssm put-parameter \
    --name "/nodeweft/prod/$service.env" \
    --type SecureString \
    --tier Intelligent-Tiering \
    --overwrite \
    --value "file://$service.prod.env" \
    --region "$REGION" >/dev/null
done

echo "Uploading manifests"
aws s3 sync deploy/k8s "s3://$DEPLOY_BUCKET/k8s/" --delete --region "$REGION" --only-show-errors
aws s3 cp deploy/scripts/nodeweft-apply.sh "s3://$DEPLOY_BUCKET/bin/nodeweft-apply.sh" --region "$REGION" --only-show-errors

echo "Deploying tag $TAG on $INSTANCE_ID"
REMOTE_COMMAND="for attempt in \$(seq 1 60); do [ -x /usr/local/bin/nodeweft-apply ] && break; sleep 10; done; nodeweft-apply $TAG"
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --timeout-seconds 1200 \
  --parameters "commands=[\"$REMOTE_COMMAND\"]" \
  --query Command.CommandId \
  --output text \
  --region "$REGION")

while true; do
  status=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query Status --output text --region "$REGION" 2>/dev/null || echo Pending)
  case "$status" in
    Pending | InProgress | Delayed) sleep 5 ;;
    *) break ;;
  esac
done

aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query StandardOutputContent --output text --region "$REGION"
aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query StandardErrorContent --output text --region "$REGION"

if [ "$status" != "Success" ]; then
  echo "Deploy finished with status $status"
  exit 1
fi
echo "Deploy finished. Test it with: curl https://$(terraform -chdir="$TERRAFORM_DIR" output -raw cloudfront_domain_name)/health"
