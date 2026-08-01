-- Run once, as the postgres superuser: sudo -u postgres psql -f postgres_setup.sql
-- Replace CHANGE_ME_STRONG_PASSWORD first — this must match POSTGRES_PASSWORD in
-- /opt/jobagentweb/.env (see JobAgentWeb's config.py POSTGRES dict). JobAgent
-- itself never touches Postgres directly — it's a stateless HTTP client of
-- JobAgentWeb's API, so no local .env / WireGuard DB access is needed for it.
CREATE ROLE jobagent WITH LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE jobagent OWNER jobagent;
