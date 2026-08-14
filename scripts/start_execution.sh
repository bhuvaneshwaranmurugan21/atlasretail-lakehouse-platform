#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 7 ]]; then
  echo "usage: start_execution.sh NAME STATE_MACHINE SOURCE_URI MANIFEST_URI BATCH_ID DIGEST INJECT_FAILURE" >&2
  exit 64
fi

execution_name="$1"
state_machine_arn="$2"
source_uri="$3"
manifest_uri="$4"
batch_id="$5"
manifest_digest="$6"
inject_failure="$7"
generation_id="g-${batch_id}"

input="$(python - "${source_uri}" "${manifest_uri}" "${batch_id}" "${generation_id}" "${manifest_digest}" "${inject_failure}" <<'PY'
import json
import sys

print(json.dumps({
    "source_uri": sys.argv[1],
    "manifest_uri": sys.argv[2],
    "batch_id": sys.argv[3],
    "generation_id": sys.argv[4],
    "manifest_digest": sys.argv[5],
    "inject_failure": sys.argv[6],
}, separators=(",", ":")))
PY
)"

execution_arn="$(aws stepfunctions start-execution \
  --state-machine-arn "${state_machine_arn}" \
  --name "${execution_name}" \
  --input "${input}" \
  --query executionArn \
  --output text)"

deadline="$((SECONDS + 900))"
while true; do
  status="$(aws stepfunctions describe-execution \
    --execution-arn "${execution_arn}" \
    --query status \
    --output text)"
  case "${status}" in
    SUCCEEDED|FAILED|TIMED_OUT|ABORTED)
      break
      ;;
  esac
  if (( SECONDS >= deadline )); then
    aws stepfunctions stop-execution \
      --execution-arn "${execution_arn}" \
      --cause "GitHub lab timeout" >/dev/null
    status="TIMED_OUT"
    break
  fi
  sleep 15
done

printf '%s\t%s\n' "${execution_arn}" "${status}"
