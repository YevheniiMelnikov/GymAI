#!/usr/bin/env sh
set -e

export PYTHONPATH=/app
export DJANGO_SETTINGS_MODULE=config.settings
ROLE="${SERVICE_ROLE:-web}"

if [ "${RUN_MIGRATIONS}" = "true" ]; then
  echo "▶ Checking for migration conflicts..."
  if ! python apps/manage.py migrate --check >/dev/null 2>&1; then
    echo "▶ Conflicts detected, trying merge..."
    python apps/manage.py makemigrations --merge --noinput || echo "▶ Merge failed, continuing anyway"
  fi

  echo "▶ Applying database migrations..."
  python apps/manage.py migrate --noinput || echo "▶ Migrate failed, continuing anyway"

  echo "▶ Ensuring superuser..."
  python apps/manage.py ensure_admin || echo "▶ ensure_admin failed"

  echo "▶ Ensuring AI coach..."
  python apps/manage.py ensure_ai_coach || echo "▶ ensure_ai_coach failed"
fi

if [ "$ROLE" = "web" ]; then
  echo "▶ Collecting static files..."
  rm -rf /app/staticfiles/js /app/staticfiles/css || true
  python apps/manage.py collectstatic --noinput || echo "Skipping collectstatic"
else
  echo "▶ Skipping collectstatic for role $ROLE"
fi

echo "▶ Starting: $@"
exec "$@"
