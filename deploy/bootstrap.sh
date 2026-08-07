#!/usr/bin/env bash
# One-time VPS provisioning for JobAgentWeb (home.pl VPS Linux XS, Ubuntu LTS).
# Run once as root on a fresh box: bash bootstrap.sh
#
# What this does NOT do (deliberately manual — see the echoed steps at the end):
# creating the Postgres role/database, configuring Postgres to listen on the
# WireGuard interface, setting up WireGuard keys, or starting the systemd service —
# each needs a value (password, generated key, domain) that shouldn't be baked into
# a script that might get committed or re-run.
set -euo pipefail

APP_USER="jobagent"
APP_DIR="/opt/jobagentweb"
REPO_URL="https://github.com/BaranskiTomasz/JobAgentWeb.git"

echo "== apt update/upgrade =="
apt-get update -y
apt-get upgrade -y

echo "== base packages =="
# python3/python3-venv track whatever the distro's current default is (Ubuntu
# 26.04 ships 3.14) rather than pinning to 3.12 by exact package name, which
# doesn't exist in every release's repos. build-essential/libpq-dev/python3-dev
# are needed because psycopg2-binary doesn't yet ship a precompiled wheel for
# every new Python version (e.g. 3.14 at the time of writing) and falls back to
# compiling from source.
apt-get install -y git curl ca-certificates gnupg python3 python3-venv python3-dev \
    postgresql wireguard build-essential libpq-dev restic

echo "== Caddy (official apt repo) =="
# Verify these URLs still match https://caddyserver.com/docs/install#debian-ubuntu-raspbian
# before running — this is the documented method as of this script's writing.
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy

echo "== app user (no login shell — runs the service only) =="
id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

echo "== clone/update app =="
if [ ! -d "$APP_DIR" ]; then
    git clone "$REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" pull
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "== python venv + deps =="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== firewall: keep :8000 off the public internet =="
# jobagentweb.service binds 0.0.0.0:8000, not 127.0.0.1 — Caddy needs to reach
# it locally AND JobAgent needs to reach it over the WireGuard tunnel, and
# --host 127.0.0.1 would cut off the tunnel too (JobAgent's default base URL
# is the wg0 address, not localhost). ufw is what actually keeps :8000 off the
# public internet instead: allowed on loopback and the tunnel interface only,
# denied everywhere else. Safe to run before WireGuard is configured (step 2
# below) — a rule naming an interface that doesn't exist yet just has no
# effect until it does, it doesn't error.
apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 51820/udp          # WireGuard's own listening port (deploy/wg-server.conf.example)
ufw allow in on lo to any port 8000 proto tcp
ufw allow in on wg0 to any port 8000 proto tcp
ufw --force enable

cat <<'EOF'

== bootstrap done — remaining manual steps ==
  1. sudo -u postgres psql -f deploy/postgres_setup.sql   (edit the password in it first)
  2. Set up WireGuard: generate server + client keys, fill in deploy/wg-server.conf.example
     and deploy/wg-client.conf.example, install the server one as /etc/wireguard/wg0.conf,
     then: systemctl enable --now wg-quick@wg0
  3. Point Postgres at the WireGuard interface only (see chat for the exact
     listen_addresses / pg_hba.conf lines — depends on your Postgres version's config path)
  4. cp deploy/env.example /opt/jobagentweb/.env   and fill in the real Postgres password,
     SECRET_KEY and INVITE_CODE (JOBAGENT_API_KEY / JOBAGENT_API_KEY_USER_ID are optional —
     see the comments in env.example; leave blank to skip the static-key login bypass)
  5. cp deploy/jobagentweb.service /etc/systemd/system/ && systemctl enable --now jobagentweb
  6. Fill in your real domain in deploy/Caddyfile, then:
     cp deploy/Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy
  7. Set up nightly backups (Postgres dump + .env, restic-encrypted):
     a. Generate a repo password and save it in your password manager NOW — it's
        the only way to ever read a backup back, and it must NOT live only on
        this VPS (see deploy/backup.sh's own header for why):
          openssl rand -base64 32 | tee /root/.restic-password
          chmod 600 /root/.restic-password
     b. cp deploy/backup.sh /usr/local/bin/jobagentweb-backup.sh && chmod +x /usr/local/bin/jobagentweb-backup.sh
        cp deploy/jobagentweb-backup.service deploy/jobagentweb-backup.timer /etc/systemd/system/
        systemctl enable --now jobagentweb-backup.timer
     c. Run it once by hand to confirm it actually works before trusting the timer:
          systemctl start jobagentweb-backup.service && journalctl -u jobagentweb-backup.service -n 50
     d. From a machine that is NOT this VPS, pull the backup down on its own
        schedule (see deploy/pull-backup.ps1 for a Windows example) — a restic
        repo that only ever lives on this box protects against a bad UPDATE,
        not against losing the VPS itself.
     e. See deploy/restore.sh for disaster recovery.
EOF
