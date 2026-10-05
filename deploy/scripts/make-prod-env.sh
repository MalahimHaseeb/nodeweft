#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

cors_origins="${1:?usage: make-prod-env.sh https://nodeweft-new.vercel.app}"

set_value() {
  local file="$1" key="$2" value="$3" escaped
  if grep -q "^$key=" "$file"; then
    escaped=$(printf '%s' "$value" | sed 's/[&|\\]/\\&/g')
    sed -i "s|^$key=.*|$key=$escaped|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

for service in auth workflow execution; do
  if [ ! -f "$service.env" ]; then
    echo "Missing $service.env in the project root"
    exit 1
  fi
  cp -f "$service.env" "$service.prod.env"
  chmod 600 "$service.prod.env"
  set_value "$service.prod.env" APP_ENV production
  set_value "$service.prod.env" TRUSTED_PROXY_HOPS 2
  set_value "$service.prod.env" CORS_ORIGINS "$cors_origins"
done

sed -i '/^AWS_ACCESS_KEY_ID=/d; /^AWS_SECRET_ACCESS_KEY=/d' execution.prod.env
set_value execution.prod.env ALLOW_LOCAL_FILES false

echo "Created auth.prod.env, workflow.prod.env and execution.prod.env"
echo "AWS keys were removed from execution.prod.env because the server uses its IAM role"
