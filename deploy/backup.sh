#!/usr/bin/env bash
# Nightly PostgreSQL backup + media copy, keeps 14 days.
# Install:  chmod +x deploy/backup.sh ; crontab -e  ->  30 2 * * * /srv/ngtraders/app/deploy/backup.sh
# Also copy /var/backups/ngtraders OFF the server regularly (another machine or cloud storage).
set -euo pipefail
set -a; . /etc/ngtraders.env; set +a

DEST=/var/backups/ngtraders
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"

PGPASSWORD="$DB_PASSWORD" pg_dump -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" -U "$DB_USER" -Fc "$DB_NAME" \
  > "$DEST/db-$STAMP.dump"
tar -czf "$DEST/media-$STAMP.tar.gz" -C /srv/ngtraders/app media 2>/dev/null || true

find "$DEST" -type f -mtime +14 -delete
echo "Backup finished: $DEST/db-$STAMP.dump"
