#!/bin/sh

set -eu

DATA_DIR="${RABBITMQ_DATA_DIR:-/var/lib/rabbitmq}"
COOKIE_FILE="${DATA_DIR}/.erlang.cookie"

printf 'rabbitmq_entrypoint fixing permissions data_dir=%s\n' "$DATA_DIR"

if [ ! -d "$DATA_DIR" ]; then
    printf 'rabbitmq_entrypoint creating_data_dir path=%s\n' "$DATA_DIR"
    mkdir -p "$DATA_DIR"
fi

if chown -R rabbitmq:rabbitmq "$DATA_DIR"; then
    printf 'rabbitmq_entrypoint permissions_applied path=%s\n' "$DATA_DIR"
else
    printf 'rabbitmq_entrypoint failed_to_chown path=%s\n' "$DATA_DIR" >&2
fi

if [ -f "$COOKIE_FILE" ]; then
    if chmod 600 "$COOKIE_FILE"; then
        printf 'rabbitmq_entrypoint cookie_permissions_fixed path=%s\n' "$COOKIE_FILE"
    else
        printf 'rabbitmq_entrypoint failed_to_fix_cookie path=%s\n' "$COOKIE_FILE" >&2
    fi
fi

DEFAULT_ENTRYPOINT="/usr/local/bin/docker-entrypoint.sh"
if command -v docker-entrypoint.sh >/dev/null 2>&1; then
    DEFAULT_ENTRYPOINT="$(command -v docker-entrypoint.sh)"
fi
UPSTREAM_ENTRYPOINT="${RABBITMQ_UPSTREAM_ENTRYPOINT:-$DEFAULT_ENTRYPOINT}"

if [ ! -x "$UPSTREAM_ENTRYPOINT" ]; then
    printf 'rabbitmq_entrypoint upstream_entrypoint_missing path=%s\n' "$UPSTREAM_ENTRYPOINT" >&2
    exit 1
fi

exec "$UPSTREAM_ENTRYPOINT" "$@"
