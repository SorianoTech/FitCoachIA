#!/usr/bin/env bash

set -e

# ==========================
# CONFIGURACIÓN
# ==========================
IMAGE_BASE_NAME="fitcoachia/fitcoach-app"   # Nombre del repo de la imagen
CONTAINER_NAME="fitcoach-ia"                # Nombre del contenedor
PORTS="-p 8000:8000"                        # Puerto de la aplicación
EXTRA_ARGS="--network proxy-network"        # Volúmenes, redes, etc (opcional)
MAX_RETRIES=10                              # Maximo de reintentos para verificar si el contenedor es up
RETRY_INTERVAL=2                            # Tiempo de espera entre reintentos (en segundos)

# ==========================
# VALIDACIÓN DE ARGUMENTOS
# ==========================
if [ -z "$1" ]; then
  echo "Error: debes pasar la versión de la imagen"
  echo "Uso: ./deploy.sh <image_version>"
  exit 1
fi

IMAGE_TAG="$1"
FULL_IMAGE="${IMAGE_BASE_NAME}:${IMAGE_TAG}"

log_step() {
  echo "[deploy] $1"
}

# ==========================
# VALIDAR IMAGEN REMOTA Y HACER PULL
# ==========================
log_step "Paso 1/4: verificando si la imagen ${FULL_IMAGE} existe en el registry..."
if docker manifest inspect "$FULL_IMAGE" >/dev/null 2>&1; then
  log_step "Imagen encontrada en el registry."
else
  log_step "Error: la imagen ${FULL_IMAGE} no existe o no es accesible desde este host."
  exit 1
fi

log_step "Paso 2/4: descargando la imagen ${FULL_IMAGE}..."
docker pull "$FULL_IMAGE"

# ==========================
# PARAR CONTENEDOR SI EXISTE
# ==========================
log_step "Paso 3/4: verificando si existe un contenedor previo..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  log_step "Contenedor existente detectado. Deteniendo y eliminando ${CONTAINER_NAME}..."
  docker stop "$CONTAINER_NAME"
  docker rm "$CONTAINER_NAME"
else
  log_step "No existe un contenedor previo con el nombre ${CONTAINER_NAME}."
fi

# ==========================
# LANZAR CONTENEDOR NUEVO
# ==========================
log_step "Paso 4/5: lanzando un nuevo contenedor con la imagen ${FULL_IMAGE}..."
docker run -d \
  --name "$CONTAINER_NAME" \
  $PORTS \
  $EXTRA_ARGS \
  "$FULL_IMAGE"

# ==========================
# VERIFICAR CONTENEDOR ACTIVO
# ==========================

log_step "Paso 5/5: verificando si el contenedor ${CONTAINER_NAME} esta arrancado..."
for i in $(seq 1 $MAX_RETRIES); do
  if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null)" = "true" ]; then
    log_step "Contenedor ${CONTAINER_NAME} arrancado correctamente (intento ${i}/${MAX_RETRIES})."
    break
  fi

  log_step "Intento ${i}/${MAX_RETRIES}: contenedor aun no esta en ejecucion. Reintentando en ${RETRY_INTERVAL}s..."
  sleep $RETRY_INTERVAL

  if [ "$i" -eq "$MAX_RETRIES" ]; then
    log_step "Error: el contenedor ${CONTAINER_NAME} no arranco tras ${MAX_RETRIES} intentos."
    docker ps -a --filter "name=^${CONTAINER_NAME}$"
    exit 1
  fi
done

log_step "Deploy completado con exito."