#!/usr/bin/env bash
set -euo pipefail
# The official Docker builder supplies the Docker CLI. Share that executable
# with the Python/gcloud steps instead of assuming those images include Docker.
if [[ ${RELEASE_PROJECT:-} != okinawago-dictionary || ! $1 =~ ^[0-9a-f]{40}$ || ! $2 =~ ^[0-9a-f-]{36}$ ]]; then
    echo 'Expected production project, full commit SHA and Cloud Build UUID' >&2
    exit 1
fi
mkdir -p /release-tools
cp "$(command -v docker)" /release-tools/docker
exec docker build -t "asia.gcr.io/okinawago-dictionary/okinawago-dictionary-app/okinawago-dictionary-app:$1-$2" .
