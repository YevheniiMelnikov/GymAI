#!/usr/bin/env sh
set -e

export PYTHONPATH=/app
export DJANGO_SETTINGS_MODULE=config.settings

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "▶ Checking for migration conflicts..."
  if ! python manage.py migrate --check >/dev/null 2>&1; then
    echo "▶ Conflicts detected, trying merge..."
    python manage.py makemigrations --merge --noinput || echo "▶ Merge failed, continuing anyway"
  fi

  echo "▶ Applying database migrations..."
  python manage.py migrate --noinput || echo "▶ Migrate failed, continuing anyway"

  echo "▶ Ensuring superuser..."
  python manage.py ensure_admin || echo "▶ ensure_admin failed"

  echo "▶ Ensuring AI coach..."
  python manage.py ensure_ai_coach || echo "▶ ensure_ai_coach failed"

  echo "▶ Collecting static files..."
  rm -rf /app/staticfiles/js /app/staticfiles/css || true
  python manage.py collectstatic --noinput || echo "Skipping collectstatic"
fi

echo "▶ Starting: $@"
exec "$@"
