#!/bin/bash
# Despliega una release en /opt/fitcoachia; si no arranca, vuelve al compose y la version previos.
# Lo lanza deploy.yml por SSM (como root) con los ficheros de la release ya descargados de S3.
# Ver docs/despliegue-aws-ec2.md y docs/ci-cd.md.
# Uso: deploy-release.sh <version X.Y.Z> <directorio con docker-compose.yml, Makefile y backup-postgres.sh>
set -euo pipefail

VERSION="${1:?version obligatoria}"
SRC="${2:?directorio de ficheros obligatorio}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/fitcoachia}"
APP_CONTAINER="fitcoach-ia"
APP_REPO="fitcoachia/fitcoach-app"
OWN_NAMESPACE="fitcoachia/"

step() { echo ""; echo "=== $* ==="; }
log()  { echo "    $*"; }

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  log "ERROR: la version debe tener formato X.Y.Z"
  exit 1
fi
for f in docker-compose.yml Makefile backup-postgres.sh; do
  [ -f "$SRC/$f" ] || { log "ERROR: falta $f en $SRC"; exit 1; }
done

cd "$DEPLOY_DIR"
ENV_FILE="$DEPLOY_DIR/.env"
export FITCOACH_ENV_FILE="$ENV_FILE"

# Solo nombres de imagen: nunca imprime valores del .env.
images_of() {
  VERSION="$2" docker compose -f "$1" --env-file "$ENV_FILE" config --images
}

prod_up() {
  VERSION="$1" make prod-up PROD_ENV_FILE="$ENV_FILE"
}

step "1/5 Contexto"
log "Servidor:           $(hostname)"
log "Version a desplegar: $VERSION"
log "Espacio libre en /: $(df -h / | awk 'NR==2 {print $4}')"
if [ ! -r "$ENV_FILE" ]; then
  log "ERROR: $ENV_FILE no existe; crealo antes del primer despliegue"
  exit 1
fi

step "2/5 Version en servicio (para el rollback)"
PREV_VERSION=""
PREV_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$APP_CONTAINER" 2>/dev/null || true)
if [ -n "$PREV_IMAGE" ] && [[ "$PREV_IMAGE" =~ ^$APP_REPO:([0-9]+\.[0-9]+\.[0-9]+)$ ]] \
   && [ -f docker-compose.yml ]; then
  PREV_VERSION="${BASH_REMATCH[1]}"
  cp docker-compose.yml docker-compose.prev.yml
  log "En servicio: $PREV_IMAGE; compose guardado en docker-compose.prev.yml"
else
  log "Sin version previa desplegada (${PREV_IMAGE:-ningun contenedor}): no habra rollback"
fi

step "3/5 Instalar los ficheros de la release"
install -m 644 "$SRC/docker-compose.yml" "$DEPLOY_DIR/docker-compose.yml"
install -m 644 "$SRC/Makefile" "$DEPLOY_DIR/Makefile"
install -m 750 "$SRC/backup-postgres.sh" "$DEPLOY_DIR/backup-postgres.sh"
log "docker-compose.yml, Makefile y backup-postgres.sh en $DEPLOY_DIR"

step "4/5 make prod-up VERSION=$VERSION (pull + up --wait)"
if prod_up "$VERSION"; then
  log "Todos los servicios arrancados y sanos"
else
  step "FALLO: la version $VERSION no ha arrancado"
  docker compose --env-file "$ENV_FILE" ps -a || true
  docker logs "$APP_CONTAINER" --tail 50 2>/dev/null || log "(sin logs de $APP_CONTAINER)"
  if [ -z "$PREV_VERSION" ]; then
    log "ERROR: no hay version anterior que restaurar; el servicio queda como este"
    exit 1
  fi
  step "Rollback a $PREV_VERSION con el compose previo"
  cp docker-compose.prev.yml docker-compose.yml
  if prod_up "$PREV_VERSION"; then
    log "ROLLBACK OK: $PREV_VERSION de nuevo en servicio"
  else
    log "ERROR CRITICO: el rollback tambien ha fallado"
  fi
  exit 1
fi

step "5/5 Limpiar imagenes propias que no usa ni esta release ni la anterior"
if ! KEEP=$(images_of docker-compose.yml "$VERSION"); then
  KEEP=""
elif [ -n "$PREV_VERSION" ] && ! KEEP+=$'\n'$(images_of docker-compose.prev.yml "$PREV_VERSION"); then
  KEEP=""
fi
if [ -z "$KEEP" ]; then
  log "AVISO: no se pudo leer la lista de imagenes de los compose; no se borra nada"
else
  docker images --format '{{.Repository}}:{{.Tag}}' | { grep "^$OWN_NAMESPACE" || true; } \
    | { grep -v ':<none>$' || true; } | while read -r img; do
    if grep -qxF "$img" <<< "$KEEP"; then
      log "conservada: $img"
    elif docker rmi "$img" > /dev/null 2>&1; then
      log "eliminada:  $img"
    else
      log "NO eliminada (en uso u otro error): $img"
    fi
  done
  docker image prune -f > /dev/null || true
fi

step "Resultado"
docker compose --env-file "$ENV_FILE" ps
log "Espacio libre en /: $(df -h / | awk 'NR==2 {print $4}')"
