#!/bin/sh
# Backup nocturno de las dos Postgres de produccion a S3.
# pg_dump se ejecuta dentro de cada contenedor con sus propias credenciales, asi que
# este script no necesita conocer contrasenas. Ver docs/despliegue-aws-ec2.md.
# Uso: BACKUP_BUCKET=<bucket> backup-postgres.sh
set -eu

: "${BACKUP_BUCKET:?BACKUP_BUCKET es obligatorio}"
CONTAINERS="${BACKUP_CONTAINERS:-fitcoach-postgres pgvector-prod}"
STAMP="$(date -u +%Y-%m-%dT%H%MZ)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

for container in $CONTAINERS; do
  echo "$(date -u +%FT%TZ) dump de $container"
  docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$WORKDIR/$container.dump"
  aws s3 cp --only-show-errors "$WORKDIR/$container.dump" \
    "s3://$BACKUP_BUCKET/postgres/$STAMP/$container.dump"
done
echo "$(date -u +%FT%TZ) backup completado en s3://$BACKUP_BUCKET/postgres/$STAMP/"
