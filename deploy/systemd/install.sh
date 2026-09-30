#!/usr/bin/env bash
# Install or upgrade the collector on a VPS. Run as root from a checkout:
#   sudo HERMES_USER=hermes deploy/systemd/install.sh
#
# Creates a new release under /opt/crypto-tracker/releases/<commit>, points
# /opt/crypto-tracker/current at it, and prepares users, directories and the
# encrypted credential. Previous releases are kept for rollback.
set -euo pipefail

HERMES_USER="${HERMES_USER:?set HERMES_USER to the account that runs Hermes}"
PYTHON="${PYTHON:-python3}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE=/opt/crypto-tracker
HOME_DIR=/var/lib/crypto-tracker
CREDSTORE=/etc/credstore.encrypted

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
id "$HERMES_USER" >/dev/null 2>&1 || { echo "no such user: $HERMES_USER" >&2; exit 1; }
[ "$HERMES_USER" != root ] || { echo "do not run Hermes as root" >&2; exit 1; }
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
  || { echo "Python 3.11+ required (set PYTHON=...)" >&2; exit 1; }

REV="$(git -C "$SRC" rev-parse --short=12 HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
if [ -n "$(git -C "$SRC" status --porcelain 2>/dev/null)" ]; then
  echo "warning: working tree has uncommitted changes; release $REV will include them" >&2
fi
RELEASE="$BASE/releases/$REV"

# Users and groups: the collector runs as crypto-tracker; the Hermes user joins
# tracker-readers to read the store and submit spool commands.
getent group tracker-readers >/dev/null || groupadd --system tracker-readers
id crypto-tracker >/dev/null 2>&1 || useradd --system --home-dir "$HOME_DIR" \
  --no-create-home --shell /usr/sbin/nologin --gid tracker-readers crypto-tracker
usermod -aG tracker-readers "$HERMES_USER"

# Release: code owned by root, read-only for everyone else.
install -d -m 0755 "$BASE" "$BASE/releases"
rm -rf "$RELEASE.tmp"
install -d -m 0755 "$RELEASE.tmp"
tar -C "$SRC" --exclude=.git --exclude=.venv --exclude=__pycache__ -cf - . | tar -C "$RELEASE.tmp" -xf -
if command -v uv >/dev/null 2>&1; then
  UV_PROJECT_ENVIRONMENT="$RELEASE.tmp/.venv" uv sync --frozen --no-dev --no-install-project \
    --project "$RELEASE.tmp" --python "$PYTHON"
else
  "$PYTHON" -m venv "$RELEASE.tmp/.venv"
  "$RELEASE.tmp/.venv/bin/pip" install --quiet --no-deps --require-hashes \
    -r "$RELEASE.tmp/deploy/requirements.lock.txt"
fi
chown -R root:root "$RELEASE.tmp"
chmod -R go-w "$RELEASE.tmp"
rm -rf "$RELEASE"
mv "$RELEASE.tmp" "$RELEASE"
ln -sfn "$RELEASE" "$BASE/current.new"
mv -T "$BASE/current.new" "$BASE/current"

# State: store is written only by the collector; spool is group-writable (setgid).
install -d -o crypto-tracker -g tracker-readers -m 0750 "$HOME_DIR"
install -d -o crypto-tracker -g tracker-readers -m 2750 "$HOME_DIR/store"
install -d -o crypto-tracker -g tracker-readers -m 2770 "$HOME_DIR/spool"

install -m 0644 "$RELEASE/deploy/systemd/crypto-tracker-collector.service" \
  /etc/systemd/system/crypto-tracker-collector.service
systemctl daemon-reload

install -d -m 0700 "$CREDSTORE"
if [ ! -f "$CREDSTORE/opennews_token" ]; then
  cat <<EOF

Next: store the OpenNews/OpenTwitter token (input is hidden, never in shell history):

  systemd-ask-password -n "OpenNews token:" \\
    | systemd-creds encrypt --name=opennews_token - $CREDSTORE/opennews_token

EOF
fi

cat <<EOF
Release $REV installed at $RELEASE (current -> $RELEASE).

  systemctl enable --now crypto-tracker-collector
  systemctl restart crypto-tracker-collector        # after an upgrade
  journalctl -u crypto-tracker-collector -f
  sudo -u crypto-tracker env PYTHONPATH=$BASE/current/src TRACKER_HOME=$HOME_DIR \\
    $BASE/current/.venv/bin/python -m crypto_tracker.cli status

Hermes (as $HERMES_USER; log in again so the new group applies):
  merge hermes/config.snippet.yaml into ~/.hermes/config.yaml, then /reload-mcp
  cp -r $RELEASE/hermes/skills/crypto-project-tracker ~/.hermes/skills/
  install -m 0700 $RELEASE/hermes/scripts/tracker-alerts.py ~/.hermes/scripts/

Rollback: ln -sfn $BASE/releases/<previous> $BASE/current && systemctl restart crypto-tracker-collector
EOF
