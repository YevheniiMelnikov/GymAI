#!/usr/bin/env sh
set -e

export PYTHONPATH=/app/api:/app
export DJANGO_SETTINGS_MODULE=api.settings

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "▶ Applying database migrations..."
  python api/manage.py migrate --noinput

  echo "▶ Collecting static files..."
  python api/manage.py collectstatic --noinput || echo "Skipping collectstatic"
fi

echo "▶ Starting: $@"
exec "$@"
