#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "usage: wait_athena.sh WORKGROUP DATABASE SQL OUTPUT_JSON" >&2
  exit 64
fi

workgroup="$1"
database="$2"
sql="$3"
output_json="$4"

query_id="$(aws athena start-query-execution \
  --work-group "${workgroup}" \
  --query-execution-context Database="${database}" \
  --query-string "${sql}" \
  --query QueryExecutionId \
  --output text)"

deadline="$((SECONDS + 300))"
while true; do
  state="$(aws athena get-query-execution \
    --query-execution-id "${query_id}" \
    --query QueryExecution.Status.State \
    --output text)"
  case "${state}" in
    SUCCEEDED)
      break
      ;;
    FAILED|CANCELLED)
      aws athena get-query-execution --query-execution-id "${query_id}" > "${output_json}"
      exit 1
      ;;
  esac
  if (( SECONDS >= deadline )); then
    aws athena stop-query-execution --query-execution-id "${query_id}"
    exit 1
  fi
  sleep 5
done

aws athena get-query-execution --query-execution-id "${query_id}" > "${output_json}"
aws athena get-query-results --query-execution-id "${query_id}" > "${output_json%.json}-results.json"
