#!/bin/bash
set -euo pipefail
umask 077

source /etc/nodeweft/config
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
NAMESPACE=nodeweft
SERVICES="auth workflow execution"

refresh_ecr_secret() {
  local token
  token=$(aws ecr get-login-password --region "$REGION")
  kubectl -n "$NAMESPACE" create secret docker-registry ecr-pull \
    --docker-server="$ECR_REGISTRY" \
    --docker-username=AWS \
    --docker-password="$token" \
    --dry-run=client -o yaml | kubectl apply -f -
}

kubectl wait --for=condition=Ready node --all --timeout=300s
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE"

if [ "${1:-}" = "--refresh-ecr" ]; then
  refresh_ecr_secret
  exit 0
fi

IMAGE_TAG="${1:?image tag is required}"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

aws s3 sync "s3://$DEPLOY_BUCKET/k8s/" "$workdir/" --region "$REGION" --only-show-errors
refresh_ecr_secret

for name in $SERVICES; do
  aws ssm get-parameter \
    --name "$SSM_PREFIX/$name.env" \
    --with-decryption \
    --query Parameter.Value \
    --output text \
    --region "$REGION" >"$workdir/$name.env"
  kubectl -n "$NAMESPACE" create secret generic "$name-env" \
    --from-env-file="$workdir/$name.env" \
    --dry-run=client -o yaml | kubectl apply -f -
  upper=$(echo "$name" | tr '[:lower:]' '[:upper:]')
  export "ENV_HASH_$upper=$(sha256sum "$workdir/$name.env" | cut -c1-16)"
done

export ECR_REGISTRY IMAGE_TAG
for name in $SERVICES; do
  envsubst '${ECR_REGISTRY} ${IMAGE_TAG} ${ENV_HASH_AUTH} ${ENV_HASH_WORKFLOW} ${ENV_HASH_EXECUTION}' <"$workdir/$name.yaml" | kubectl apply -f -
done

for name in $SERVICES; do
  kubectl -n "$NAMESPACE" rollout status "deployment/$name" --timeout=300s
done
kubectl -n "$NAMESPACE" get pods -o wide
