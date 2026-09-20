# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_BASE=fitcoachia/fitcoach-app
IMAGE_LATEST=$(IMAGE_BASE):latest
CONTAINER_NAME=fitcoach-ia
PORT=8000
version ?= latest
BASE_PACKAGE=src
BASE_TEST_PACKAGE=tests
UNIT_TEST_PACKAGE=$(BASE_TEST_PACKAGE)/unit_test
IT_TEST_PACKAGE=$(BASE_TEST_PACKAGE)/it

# Prefiere .venv (layout por defecto de uv) y cae a venv si no existe.
VENV:=$(if $(wildcard .venv),.venv,venv)
PYTEST=$(VENV)/Scripts/pytest.exe

COMPOSE_IT=tests/docker-compose-test.yml
IT_PORT ?= 8001
IT_BASE_URL ?= http://localhost:$(IT_PORT)
export IT_PORT
export IT_BASE_URL

COMPOSE_UP=$(DOCKER) compose -f $(COMPOSE_IT) up -d --build --wait
COMPOSE_DOWN=$(DOCKER) compose -f $(COMPOSE_IT) down -v --remove-orphans

# Ficheros de entorno fuera del repositorio; dev cae al fichero local si no existen, prod no
ENV_ROOT ?= /etc/fitcoachia
DEV_ENV_FILE ?= $(ENV_ROOT)/dev/.env.dev
PROD_ENV_FILE ?= $(ENV_ROOT)/prod/.env.prod
DEV_ENV_FALLBACK=.env.dev

COMPOSE_DEV=$(DOCKER) compose -f docker-compose.dev.yml
COMPOSE_PROD=$(DOCKER) compose

define resolve_dev_env
if [ -f "$(DEV_ENV_FILE)" ]; then \
	ENV_FILE="$(DEV_ENV_FILE)"; \
else \
	ENV_FILE="$(DEV_ENV_FALLBACK)"; \
	echo ">> $(DEV_ENV_FILE) no encontrado -> usando $(DEV_ENV_FALLBACK)"; \
fi; \
[ -f "$$ENV_FILE" ] || { echo "ERROR: no existe ningun fichero de entorno de desarrollo"; exit 1; }; \
echo ">> entorno dev: $$ENV_FILE"; \
export FITCOACH_ENV_FILE="$$ENV_FILE"
endef

define resolve_prod_env
if [ ! -r "$(PROD_ENV_FILE)" ]; then \
	echo "ERROR: $(PROD_ENV_FILE) no existe o no tiene permisos de acceso"; \
	echo "       crea el fichero, o ejecuta el target con sudo"; \
	exit 1; \
fi; \
echo ">> entorno prod: $(PROD_ENV_FILE)"; \
export FITCOACH_ENV_FILE="$(PROD_ENV_FILE)"
endef

.PHONY: container build run stop clean all help clean-image clean-images logs tests dev-up dev-down dev-logs prod-up prod-down prod-logs
# Usa siempre el pytest del venv del proyecto, evitando depender de cuál
# pytest gane por orden del PATH del shell. En CI (sin venv, deps instaladas
# --system) se sobreescribe con `make tests PYTEST=pytest`.

help:
	@echo "Comandos disponibles Docker"
	@echo "  make container                      - Consulta los contenedores"
	@echo "  make build [version=x.y.z]          - Construye la imagen de Docker (Por defecto, latest). Si indicas version, genera las imagenes latest y x.y.z (Defecto: latest)"
	@echo "  make run [version=x.y.z]            - Ejecuta el contenedor con la imagen (previamente generada) latest o version x.y.z indicada en el puerto $(PORT)"
	@echo "  make stop                           - Detiene y elimina el contenedor si está corriendo"
	@echo "  make logs                           - Muestra los logs del contenedor"
	@echo "  make clean                          - Detiene el contenedor y elimina todas las imagenes $(IMAGE_BASE)"
	@echo "  make all                            - Construye y ejecuta todo (limpiando primero)"
	@echo "  make clean-images                   - Elimina todas las imagenes en local"
	@echo "  make clean-image [version=x.y.z]    - Elimina solo la imagen de la version indicada (Defecto: latest)"
	@echo "  make tests                          - execute all tests (unit test and it tests). Analiza cobertura y falla si cobertura < 80% "
	@echo "  make dev-up                         - Levanta el entorno de desarrollo aislado. Usa $(DEV_ENV_FILE) si existe, si no $(DEV_ENV_FALLBACK)"
	@echo "  make dev-down                       - Detiene el entorno de desarrollo"
	@echo "  make dev-logs                       - Muestra los logs del entorno de desarrollo"
	@echo "  make prod-up [VERSION=x.y.z]        - Levanta el entorno de produccion. Requiere $(PROD_ENV_FILE) (override: PROD_ENV_FILE=ruta)"
	@echo "  make prod-down                      - Detiene el entorno de produccion"
	@echo "  make prod-logs                      - Muestra los logs del entorno de produccion"

container:
	@$(DOCKER) ps -a

build:
	@$(DOCKER) build -t $(IMAGE_BASE):$(version) -f src/Dockerfile .
	@if [ "$(version)" != "latest" ]; then \
		$(DOCKER) tag $(IMAGE_BASE):$(version) $(IMAGE_LATEST); \
		echo "Imagen construida: $(IMAGE_BASE):$(version) (también etiquetada como latest)"; \
	else \
		echo "Imagen construida: $(IMAGE_LATEST)"; \
	fi

dev-up:
	@$(resolve_dev_env); \
	$(COMPOSE_DEV) --env-file "$$FITCOACH_ENV_FILE" up -d --build

dev-down:
	@$(resolve_dev_env); \
	$(COMPOSE_DEV) --env-file "$$FITCOACH_ENV_FILE" down --remove-orphans

dev-logs:
	@$(resolve_dev_env); \
	$(COMPOSE_DEV) --env-file "$$FITCOACH_ENV_FILE" logs -f

prod-up:
	@$(resolve_prod_env); \
	$(COMPOSE_PROD) --env-file "$$FITCOACH_ENV_FILE" up -d

prod-down:
	@$(resolve_prod_env); \
	$(COMPOSE_PROD) --env-file "$$FITCOACH_ENV_FILE" down --remove-orphans

prod-logs:
	@$(resolve_prod_env); \
	$(COMPOSE_PROD) --env-file "$$FITCOACH_ENV_FILE" logs -f

tests:
	@$(COMPOSE_UP); \
	$(PYTEST) --cov=$(BASE_PACKAGE)/fitcoach --cov-fail-under=80 -o testpaths="$(UNIT_TEST_PACKAGE) $(IT_TEST_PACKAGE)"; \
	STATUS=$$?; \
	$(COMPOSE_DOWN); \
	exit $$STATUS

run:
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@$(DOCKER) run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) --env-file .env \
		$(if $(log_level),-e log_level=$(log_level),) $(TARGET_IMAGE)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@$(DOCKER) stop $(CONTAINER_NAME) || true
	@$(DOCKER) rm $(CONTAINER_NAME) || true

logs:
	@$(DOCKER) logs -f $(CONTAINER_NAME)

clean: stop clean-images

all: clean build run

# Borra unicamente la imagen de la version indicada, respetando el resto de tags
clean-image:
	@IMAGE=$$($(DOCKER) images --filter "reference=$(IMAGE_BASE):$(version)" -q); \
	if [ -z "$$IMAGE" ]; then \
		echo "No se encontro la imagen $(IMAGE_BASE):$(version). Nada que eliminar."; \
		exit 0; \
	fi; \
	echo "Eliminando $(IMAGE_BASE):$(version)..."; \
	$(DOCKER) rmi $(IMAGE_BASE):$(version)

# Borra todas las imagenes que contengan el nombre fitcoachia/fitcoach-app. Busca los IDs, elimina duplicados y borra las imagenes
clean-images:
	@IMAGES=$$($(DOCKER) images --filter "reference=$(IMAGE_BASE)" -q | sort -u); \
	if [ -z "$$IMAGES" ]; then \
		echo "No se encontraron imágenes de $(IMAGE_BASE). Nada que eliminar."; \
	else \
		echo "Eliminando imágenes de $(IMAGE_BASE)..."; \
		$(DOCKER) rmi -f $$IMAGES; \
		echo "Imágenes eliminadas correctamente."; \
	fi
