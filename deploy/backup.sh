#!/usr/bin/env bash
# Nightly backup: Postgres dump + a copy of .env, into a restic repo local to
# this VPS. Installed at /usr/local/bin/jobagentweb-backup.sh (see bootstrap.sh's
# manual steps), run as root by jobagentweb-backup.service — its
# EnvironmentFile=/opt/jobagentweb/.env supplies POSTGRES_HOST/PORT/DB/USER/PASSWORD.
#
# This alone does NOT get the backup off the VPS — see deploy/pull-backup.ps1,
# which a separate machine runs to copy $BACKUP_DIR down. A backup that never
# leaves the box it's backing up isn't a backup against disk failure, VPS loss,
# or ransomware — only against operator error (bad UPDATE, dropped table etc.),
# which restic's own snapshot history already covers on its own.
#
# .env is included deliberately: SECRET_KEY, INVITE_CODE, POSTGRES_PASSWORD, and
# JOBAGENT_API_KEY live ONLY in that file, never in the database — a DB-only
# backup would restore data nobody could log into or re-derive credentials for.
set -euo pipefail

BACKUP_DIR=/var/backups/jobagentweb-restic
RESTIC_PASSWORD_FILE=/root/.restic-password
ENV_FILE=/opt/jobagentweb/.env

export RESTIC_REPOSITORY="$BACKUP_DIR"
export RESTIC_PASSWORD_FILE

if [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
    echo "ERROR: $RESTIC_PASSWORD_FILE not found — generate one and save a copy" \
         "in your password manager before running this (see bootstrap.sh's backup step)." >&2
    exit 1
fi

: "${POSTGRES_HOST:?POSTGRES_HOST not set — this script expects EnvironmentFile=$ENV_FILE}"
: "${POSTGRES_PORT:?}"
: "${POSTGRES_DB:?}"
: "${POSTGRES_USER:?}"
: "${POSTGRES_PASSWORD:?}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB" \
    | gzip > "$TMP/jobagentweb.sql.gz"
cp "$ENV_FILE" "$TMP/env-backup"

mkdir -p "$BACKUP_DIR"
restic snapshots >/dev/null 2>&1 || restic init

restic backup "$TMP" --tag jobagentweb
# 14 daily + 8 weekly + 6 monthly: bounds how much disk this consumes locally
# (and how much deploy/pull-backup.ps1 has to copy) instead of growing forever.
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 6 --prune
