#!/usr/bin/env bash
# Disaster recovery: restore the latest (or a specific) snapshot from a restic
# repo produced by backup.sh. Run this against a *pulled* copy of the repo
# (see deploy/pull-backup.ps1) when the VPS itself is gone — or directly
# against /var/backups/jobagentweb-restic on the VPS for a same-box restore
# (e.g. recovering from a bad UPDATE without a full disaster).
#
# Usage: RESTIC_REPOSITORY=/path/to/pulled/jobagentweb-restic \
#        RESTIC_PASSWORD_FILE=/path/to/restic-password \
#        [SNAPSHOT=latest] [TARGET_DB=jobagentweb_restored] \
#        ./restore.sh
#
# What this does NOT do: recreate the Postgres role/database (see
# deploy/postgres_setup.sql), reinstall JobAgentWeb itself (see bootstrap.sh),
# or restart the service — this only restores data + .env into files/a
# database you point it at. Deliberately manual after that point, same
# reasoning as bootstrap.sh's own "remaining manual steps".
set -euo pipefail

: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY to the restic repo dir (pulled copy, or the VPS own /var/backups/jobagentweb-restic)}"
: "${RESTIC_PASSWORD_FILE:?Set RESTIC_PASSWORD_FILE to the restic repo password (the one saved in your password manager)}"

SNAPSHOT="${SNAPSHOT:-latest}"
TARGET_DB="${TARGET_DB:-jobagentweb_restored}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== restoring snapshot $SNAPSHOT from $RESTIC_REPOSITORY =="
restic restore "$SNAPSHOT" --target "$TMP"

DUMP="$(find "$TMP" -name jobagentweb.sql.gz)"
ENV_BACKUP="$(find "$TMP" -name env-backup)"
if [ -z "$DUMP" ] || [ -z "$ENV_BACKUP" ]; then
    echo "ERROR: expected files not found in restored snapshot (found: $(find "$TMP" -type f))" >&2
    exit 1
fi

echo "== restored files =="
echo "  DB dump:    $DUMP"
echo "  .env backup: $ENV_BACKUP"
echo
echo "Next steps (manual — this script stops here on purpose, see its own header):"
echo "  1. Create the target role/database (deploy/postgres_setup.sql), or point"
echo "     TARGET_DB at an existing empty one."
echo "  2. Load the dump:"
echo "       gunzip -c '$DUMP' | psql -h \$POSTGRES_HOST -U \$POSTGRES_USER -d $TARGET_DB"
echo "  3. Copy '$ENV_BACKUP' to /opt/jobagentweb/.env (update POSTGRES_DB if the"
echo "     restored name differs from the original), then restart jobagentweb.service."
