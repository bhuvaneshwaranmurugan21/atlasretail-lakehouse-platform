#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${ACCOUNT_LEASE_TABLE:?ACCOUNT_LEASE_TABLE is required}"
if [[ -z "${PORTFOLIO_LOCK_OWNER:-}" ]]; then
  exit 0
fi

set +e
detail="$(aws dynamodb delete-item \
  --region "${AWS_REGION}" \
  --table-name "${ACCOUNT_LEASE_TABLE}" \
  --key '{"lock_id":{"S":"portfolio-lab"}}' \
  --condition-expression "#owner = :owner" \
  --expression-attribute-names '{"#owner":"owner"}' \
  --expression-attribute-values "{\":owner\":{\"S\":\"${PORTFOLIO_LOCK_OWNER}\"}}" 2>&1)"
status="$?"
set -e

if [[ "${status}" -eq 0 || "${detail}" == *"ConditionalCheckFailedException"* ]]; then
  exit 0
fi
printf '%s\n' "${detail}" >&2
exit "${status}"
