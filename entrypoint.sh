#!/usr/bin/env sh
set -e

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "▶ Applying database migrations..."
  python manage.py migrate --noinput

  echo "▶ Collecting static files..."
  python manage.py collectstatic --noinput || echo "Skipping collectstatic"

fi

echo "▶ Starting: $@"
exec "$@"
