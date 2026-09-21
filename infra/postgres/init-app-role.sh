#!/usr/bin/env bash
# Runs once on first database init. Creates the non-superuser role the application
# uses and makes it owner of the application database (and thus its public schema).
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD" -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE :"db" OWNER TO :"app_user";
SQL
