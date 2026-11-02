#!/bin/sh
# Katru nakti 03:15 izveido DB kopiju /backups un dzēš vecākas par 14 dienām.
# Atjaunošana: gunzip -c backups/estudijas-XXXX.sql.gz | docker compose exec -T db psql -U estudijas estudijas
set -eu
while true; do
  now=$(date +%H%M)
  if [ "$now" = "0315" ]; then
    f="/backups/estudijas-$(date +%Y%m%d-%H%M).sql.gz"
    pg_dump -h db -U estudijas estudijas | gzip > "$f.tmp" && mv "$f.tmp" "$f" && echo "backup: $f"
    find /backups -name 'estudijas-*.sql.gz' -mtime +14 -delete
    sleep 61
  fi
  sleep 30
done
