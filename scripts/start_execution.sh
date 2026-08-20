#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 7 ]]; then
  echo "usage: start_execution.sh NAME STATE_MACHINE MANIFEST_URI MANIFEST_VERSION BATCH_ID DIGEST INJECT_FAILURE" >&2
  exit 64
fi

execution_name="$1"
state_machine_arn="$2"
manifest_uri="$3"
manifest_version_id="$4"
batch_id="$5"
manifest_digest="$6"
inject_failure="$7"
source_commit="${GITHUB_SHA:-unknown}"
workflow_run_id="${GITHUB_RUN_ID:-unknown}"
input="$(python - "${manifest_uri}" "${manifest_version_id}" "${batch_id}" "${manifest_digest}" "${inject_failure}" "${source_commit}" "${workflow_run_id}" <<'PY'
import json
import sys

print(json.dumps({
    "manifest_uri": sys.argv[1],
    "manifest_version_id": sys.argv[2],
    "batch_id": sys.argv[3],
    "manifest_digest": sys.argv[4],
    "inject_failure": sys.argv[5],
    "source_commit": sys.argv[6],
    "workflow_run_id": sys.argv[7],
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
