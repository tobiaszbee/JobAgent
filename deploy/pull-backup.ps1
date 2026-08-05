# Pulls the VPS's local restic backup repo (see deploy/backup.sh) down to this
# machine, so the backup actually survives losing the VPS - a repo that only
# ever lives on the box it's backing up isn't a disaster-recovery backup, only
# protection against operator error (which restic's own snapshot history
# already covers on its own).
#
# Run manually, or on a schedule via Task Scheduler:
# schtasks /create /tn "JobAgentWeb backup pull" /sc daily /st 04:30 /tr "powershell.exe -NoProfile -File C:\path\to\deploy\pull-backup.ps1"
#
# Requires: Windows' built-in OpenSSH client (ssh.exe/scp.exe - already present
# on this machine), and an SSH key already authorized on the VPS for $VpsUser.
# Windows' scp does NOT reliably fall back to ~/.ssh/config the way a plain
# `ssh` invocation does when the key file isn't one of the default names
# (id_rsa/id_ed25519 etc.) - pass -IdentityFile explicitly rather than relying
# on that, even though this machine also has a jobagent-vps Host alias in
# ~/.ssh/config.
#
# Uses plain scp -r rather than rsync (not installed here) - it re-copies the
# whole repo directory every run rather than transferring only what changed.
# Fine at this project's scale (a restic repo pruned to 14 daily/8 weekly/6
# monthly snapshots of a database with a few thousand rows stays well under
# 1GB) - if it grows enough for that to matter, switch to rsync over WSL.

param(
    [string]$VpsHost = "CHANGE_ME.example.com",   # or the WireGuard address, e.g. 10.66.0.1
    [string]$VpsUser = "root",
    [string]$IdentityFile = "$env:USERPROFILE\.ssh\jobagent_vps",
    [string]$RemoteRepo = "/var/backups/jobagentweb-restic",
    [string]$LocalDest = "$env:USERPROFILE\Backups\jobagentweb-restic"
)

$ErrorActionPreference = "Stop"

if ($VpsHost -eq "CHANGE_ME.example.com") {
    Write-Error "Edit -VpsHost (or pass it as a parameter) before running this - see deploy/env.example for the convention this repo uses for placeholder values."
}

$parent = Split-Path -Parent $LocalDest
New-Item -ItemType Directory -Force -Path $parent | Out-Null

Write-Host "Pulling $VpsUser@${VpsHost}:$RemoteRepo -> $LocalDest ..."
& scp -i $IdentityFile -r "${VpsUser}@${VpsHost}:${RemoteRepo}" $parent
if ($LASTEXITCODE -ne 0) {
    Write-Error "scp failed (exit $LASTEXITCODE) - is the VPS reachable and is your SSH key authorized?"
}

Write-Host "Done. Restic repo password lives in your password manager, not in this repo or on disk here - deploy/restore.sh needs it to actually read a snapshot."
