#!/usr/bin/env sh
set -e

export PYTHONPATH=/app
export DJANGO_SETTINGS_MODULE=config.settings

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "▶ Applying database migrations..."
  python manage.py migrate --noinput

  echo "▶ Ensuring superuser..."
  python manage.py ensure_admin
  echo "▶ Ensuring AI coach..."
  python manage.py ensure_ai_coach

  echo "▶ Collecting static files..."
  python manage.py collectstatic --noinput || echo "Skipping collectstatic"
fi

echo "▶ Starting: $@"
exec "$@"
