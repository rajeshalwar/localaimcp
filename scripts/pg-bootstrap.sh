#!/bin/sh
# Idempotently create the application role and database.
set -eu
USER_NAME="${POSTGRES_USER:-solar}"
DB_NAME="${POSTGRES_DB:-solar}"
PASSWORD="${POSTGRES_PASSWORD:-localdev}"
HBA=/var/lib/pgsql/data/pg_hba.conf

for _ in $(seq 1 30); do pg_isready -q && break; sleep 1; done

if ! psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${USER_NAME}'" | grep -q 1; then
  psql -c "CREATE ROLE \"${USER_NAME}\" LOGIN PASSWORD '${PASSWORD}'"
  echo "created role ${USER_NAME}"
fi
if ! psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  psql -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${USER_NAME}\""
  echo "created database ${DB_NAME}"
fi

# Volumes initialised before pg-init passed --auth-* have `trust` everywhere,
# so the password was never checked. Tighten them in place; a no-op otherwise.
if grep -Eq '^[[:space:]]*(local|host)[[:space:]].*[[:space:]]trust[[:space:]]*$' "$HBA"; then
  sed -i -E \
    -e 's/^([[:space:]]*host[[:space:]].*[[:space:]])trust[[:space:]]*$/\1scram-sha-256/' \
    -e 's/^([[:space:]]*local[[:space:]].*[[:space:]])trust[[:space:]]*$/\1peer/' "$HBA"
  psql -tAc "SELECT pg_reload_conf()" >/dev/null
  echo "pg_hba.conf: replaced trust with peer/scram-sha-256"
fi
