#!/usr/bin/env bash
# Build, push, and roll api/worker/mock-netsuite on Azure Container Apps (staging).
# ponytail: no tag arg handling beyond a timestamp default — add if you need
# rollback-by-tag later.
set -euo pipefail

ACR=o2cstagingacr0kyxkz
RG=rg-o2c-staging
TAG="${1:-$(date +%Y%m%d%H%M%S)}"

az acr login --name "$ACR"

CA_SECRET=(--secret id=corporate_ca,src=.build-ca/corporate-ca-bundle.crt)

docker build "${CA_SECRET[@]}" -f Dockerfile.api    -t "$ACR.azurecr.io/o2c/api:$TAG"    .
docker build "${CA_SECRET[@]}" -f Dockerfile.worker -t "$ACR.azurecr.io/o2c/worker:$TAG" .
docker build                   -f Dockerfile.mocks  -t "$ACR.azurecr.io/mocks:$TAG"      .

docker push "$ACR.azurecr.io/o2c/api:$TAG"
docker push "$ACR.azurecr.io/o2c/worker:$TAG"
docker push "$ACR.azurecr.io/mocks:$TAG"

az containerapp update -g "$RG" -n o2c-staging-api           --image "$ACR.azurecr.io/o2c/api:$TAG"
az containerapp update -g "$RG" -n o2c-staging-worker        --image "$ACR.azurecr.io/o2c/worker:$TAG"
az containerapp update -g "$RG" -n o2c-staging-mock-netsuite --image "$ACR.azurecr.io/mocks:$TAG"

echo "Deployed tag $TAG"
