#!/bin/sh

set -eu

DATA_DIR="${RABBITMQ_DATA_DIR:-/var/lib/rabbitmq}"

printf 'rabbitmq_entrypoint fixing permissions data_dir=%s\n' "$DATA_DIR"

if [ ! -d "$DATA_DIR" ]; then
  printf 'rabbitmq_entrypoint creating_data_dir path=%s\n' "$DATA_DIR"
  mkdir -p "$DATA_DIR"
fi

if chown -R rabbitmq:rabbitmq "$DATA_DIR" 2>/dev/null; then
  printf 'rabbitmq_entrypoint permissions_applied path=%s\n' "$DATA_DIR"
else
  printf 'rabbitmq_entrypoint permissions_skipped path=%s\n' "$DATA_DIR" >&2
fi

DEFAULT_ENTRYPOINT=""
if command -v docker-entrypoint.sh >/dev/null 2>&1; then
  DEFAULT_ENTRYPOINT="$(command -v docker-entrypoint.sh)"
elif [ -x /usr/local/bin/docker-entrypoint.sh ]; then
  DEFAULT_ENTRYPOINT="/usr/local/bin/docker-entrypoint.sh"
fi

UPSTREAM_ENTRYPOINT="${RABBITMQ_UPSTREAM_ENTRYPOINT:-$DEFAULT_ENTRYPOINT}"

if [ -z "$UPSTREAM_ENTRYPOINT" ] || [ ! -x "$UPSTREAM_ENTRYPOINT" ]; then
  printf 'rabbitmq_entrypoint upstream_entrypoint_missing path=%s\n' "$UPSTREAM_ENTRYPOINT" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  set -- "${RABBITMQ_DEFAULT_CMD:-rabbitmq-server}"
fi

exec "$UPSTREAM_ENTRYPOINT" "$@"
