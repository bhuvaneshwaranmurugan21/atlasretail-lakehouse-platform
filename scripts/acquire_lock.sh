#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"

lock_id="portfolio-lab"
owner="${GITHUB_REPOSITORY}/${GITHUB_RUN_ID}"
now_epoch="$(date +%s)"
expires_at="$((now_epoch + 10800))"

aws dynamodb put-item \
  --region "${AWS_REGION}" \
  --table-name portfolio-lab-account-lease \
  --item "{\"lock_id\":{\"S\":\"${lock_id}\"},\"owner\":{\"S\":\"${owner}\"},\"expires_at\":{\"N\":\"${expires_at}\"}}" \
  --condition-expression "attribute_not_exists(lock_id) OR expires_at < :now" \
  --expression-attribute-values "{\":now\":{\"N\":\"${now_epoch}\"}}"

echo "PORTFOLIO_LOCK_OWNER=${owner}" >> "${GITHUB_ENV}"
