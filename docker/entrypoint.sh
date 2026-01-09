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


fi

if [ "${WEBAPP_AUTO_BUILD}" = "true" ]; then
  echo "▶ Building webapp bundle..."
  if [ ! -d "/app/apps/webapp/node_modules" ]; then
    (cd /app/apps/webapp && npm ci)
  fi
  (cd /app/apps/webapp && npm run build)
fi

if [ "${SKIP_COLLECTSTATIC}" = "true" ]; then
  echo "▶ Skipping collectstatic (disabled)"
elif [ "$ROLE" = "web" ] || [ "$ROLE" = "api" ]; then
  echo "▶ Collecting static files..."
  CLEAR_FLAG=""
  if [ "${COLLECTSTATIC_CLEAR}" = "true" ]; then
    CLEAR_FLAG="--clear"
  fi
  python apps/manage.py collectstatic --noinput $CLEAR_FLAG || echo "Skipping collectstatic"
  if [ -d "/app/apps/webapp/static" ]; then
    mkdir -p /app/staticfiles/css /app/staticfiles/i18n /app/staticfiles/images
    copy_static_file() {
      SRC="$1"
      DST="$2"
      if [ ! -f "$SRC" ]; then
        return 0
      fi
      if [ -f "$DST" ]; then
        SRC_INODE=$(stat -c "%d:%i" "$SRC")
        DST_INODE=$(stat -c "%d:%i" "$DST")
        if [ "$SRC_INODE" = "$DST_INODE" ]; then
          return 0
        fi
      fi
      cp -f "$SRC" "$DST"
    }
    copy_static_file "/app/apps/webapp/static/css/common.css" "/app/staticfiles/css/common.css"
    if [ -d "/app/apps/webapp/static/i18n" ]; then
      for JSON_FILE in /app/apps/webapp/static/i18n/*.json; do
        if [ -f "$JSON_FILE" ]; then
          BASENAME=$(basename "$JSON_FILE")
          copy_static_file "$JSON_FILE" "/app/staticfiles/i18n/$BASENAME"
        fi
      done
    fi
    copy_static_file "/app/apps/webapp/static/images/404.png" "/app/staticfiles/images/404.png"
  fi
else
  echo "▶ Skipping collectstatic for role $ROLE"
fi

echo "▶ Starting: $@"
exec "$@"
