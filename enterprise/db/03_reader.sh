#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=reader_password="$ANALYST_DB_PASSWORD" <<'SQL'
CREATE ROLE analyst_reader LOGIN PASSWORD :'reader_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE enterprise_analytics FROM PUBLIC;
GRANT CONNECT ON DATABASE enterprise_analytics TO analyst_reader;
GRANT USAGE ON SCHEMA sales TO analyst_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA sales TO analyst_reader;
ALTER ROLE analyst_reader SET default_transaction_read_only = on;
ALTER ROLE analyst_reader SET statement_timeout = '5s';
ALTER ROLE analyst_reader SET search_path = sales, pg_catalog;
SQL
