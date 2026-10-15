#!/usr/bin/env bash
# Prepare local configuration and persistent directories for Docker Compose.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

command -v openssl >/dev/null
docker compose version >/dev/null

if [[ ! -e .env ]]; then
    (
        umask 077
        cp docker/.env.example .env
        for name in MONGODB_PASSWORD REDIS_PASSWORD JWT_SECRET CSRF_SECRET ADMIN_PASSWORD; do
            value="$(openssl rand -hex 32)"
            sed -i "s/CHANGE_ME_${name}/${value}/g" .env
        done
    )
    echo "Created .env; the initial admin password is in ADMIN_DEFAULT_PASSWORD."
fi

if [[ ! -e deployment/config/searxng-settings.yml ]]; then
    (
        umask 077
        cp deployment/config/searxng-settings.yml.example deployment/config/searxng-settings.yml
        value="$(openssl rand -hex 32)"
        sed -i "s/replace-with-a-random-secret/${value}/g" deployment/config/searxng-settings.yml
        chmod 644 deployment/config/searxng-settings.yml
    )
    echo "Created SearXNG configuration."
fi

mkdir -p mapped/data/db mapped/var/lib/redis mapped/app/{data,logs,runtime}
if [[ ! -s mapped/data/db/.mongodb-keyfile ]]; then
    docker run --rm --user 0 --entrypoint bash \
        --mount "type=bind,src=$PWD/mapped/data/db,dst=/data/db" \
        mongo:7.0.37 -euc '
            umask 077
            openssl rand -base64 756 > /data/db/.mongodb-keyfile
            chown mongodb:mongodb /data/db/.mongodb-keyfile
            chmod 600 /data/db/.mongodb-keyfile
        '
    echo "Created MongoDB keyfile."
fi

echo "Local configuration is ready. Run ./docker/rebuild.sh to build and start."
