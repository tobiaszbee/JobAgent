-- Run once, as the postgres superuser: sudo -u postgres psql -f postgres_setup.sql
-- Replace CHANGE_ME_STRONG_PASSWORD first — this must match POSTGRES_PASSWORD in
-- both /opt/jobagent/.env.web (JobAgentWeb) and the local JobAgent .env once the
-- WireGuard tunnel is up (see config.py's POSTGRES dict).
CREATE ROLE jobagent WITH LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
CREATE DATABASE jobagent OWNER jobagent;
