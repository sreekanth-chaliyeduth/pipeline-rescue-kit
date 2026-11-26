#!/bin/sh
# Bring up the controller, wait for JCasC to create the node, read the agent
# secret from the Jenkins API, then start the agent. Safe to re-run.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "${ROOT}/.." && pwd)
cd "${ROOT}"

export JENKINS_URL="http://127.0.0.1:${JENKINS_PORT:-8080}"

./scripts/bootstrap-secrets.sh

docker compose build
docker compose up -d controller

python3 scripts/jenkins_api.py wait-controller --timeout 300
python3 scripts/jenkins_api.py reload
python3 scripts/jenkins_api.py wait-node --name linux-agent --timeout 180
python3 scripts/jenkins_api.py fetch-agent-secret --name linux-agent

docker compose up -d --force-recreate --no-deps agent
python3 scripts/jenkins_api.py wait-agent-online --name linux-agent --timeout 180

echo "Jenkins controller: ${JENKINS_URL}/"
echo "Admin user: admin"
echo "Admin password file: ${PROJECT_ROOT}/.secrets/admin-password"
