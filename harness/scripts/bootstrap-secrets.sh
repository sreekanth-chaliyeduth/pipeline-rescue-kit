#!/bin/sh
# Create local, gitignored secrets. The admin password is generated once and
# reused on restart. The agent secret is written later from the Jenkins API.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SECRETS="${ROOT}/.secrets"

umask 077
mkdir -p "${SECRETS}"
chmod 700 "${SECRETS}"

if [ ! -s "${SECRETS}/admin-password" ]; then
  openssl rand -hex 24 > "${SECRETS}/admin-password"
fi
chmod 600 "${SECRETS}/admin-password"

printf 'JENKINS_ADMIN_PASSWORD=%s\n' "$(cat "${SECRETS}/admin-password")" > "${SECRETS}/jenkins.env"
chmod 600 "${SECRETS}/jenkins.env"

# Empty placeholder until the controller has created the node. Mode 0644 is
# required because the bind-mounted file is read by uid 1000 in the agent; the
# parent directory is 0700 and the file is not tracked by Git.
if [ ! -e "${SECRETS}/agent-secret" ]; then
  : > "${SECRETS}/agent-secret"
fi
chmod 644 "${SECRETS}/agent-secret"
