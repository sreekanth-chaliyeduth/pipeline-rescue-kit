#!/bin/bash
# Read the inbound agent secret from a mounted file, then hand over to the
# stock inbound-agent launcher. The secret is never placed in the image,
# compose file or Git.
set -euo pipefail

secret_file="${JENKINS_SECRET_FILE:-/run/secrets/agent-secret}"

for _ in $(seq 1 90); do
  if [ -s "${secret_file}" ]; then
    break
  fi
  sleep 2
done

if [ ! -s "${secret_file}" ]; then
  echo "agent secret file ${secret_file} is missing or empty" >&2
  exit 1
fi

JENKINS_SECRET="$(cat "${secret_file}")"
export JENKINS_SECRET

exec /usr/local/bin/jenkins-agent "$@"
