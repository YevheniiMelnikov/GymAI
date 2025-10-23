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

exec /opt/rabbitmq/sbin/docker-entrypoint.sh "$@"
