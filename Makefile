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

VENV=venv
PYTEST=$(VENV)/Scripts/pytest.exe

COMPOSE_IT=tests/docker-compose-test.yml
IT_PORT ?= 8001
IT_BASE_URL ?= http://localhost:$(IT_PORT)
export IT_PORT
export IT_BASE_URL

COMPOSE_UP=$(DOCKER) compose -f $(COMPOSE_IT) up -d --build --wait
COMPOSE_DOWN=$(DOCKER) compose -f $(COMPOSE_IT) down -v --remove-orphans

.PHONY: container build run stop clean all help clean-image clean-images logs tests dev-up dev-down dev-logs prod-up prod-down prod-logs

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
	@echo "  make dev-up                         - Levanta el entorno de desarrollo aislado"
	@echo "  make dev-down                       - Detiene el entorno de desarrollo"
	@echo "  make dev-logs                       - Muestra los logs del entorno de desarrollo"
	@echo "  make prod-up [version=x.y.z]        - Levanta el entorno de produccion"
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
	$(DOCKER) compose --env-file .env.dev -f docker-compose.dev.yml up -d --build

dev-down:
	$(DOCKER) compose --env-file .env.dev -f docker-compose.dev.yml down

dev-logs:
	$(DOCKER) compose --env-file .env.dev -f docker-compose.dev.yml logs -f

prod-up:
	$(DOCKER) compose --env-file .env.prod up -d

prod-down:
	$(DOCKER) compose --env-file .env.prod down

prod-logs:
	$(DOCKER) compose --env-file .env.prod logs -f

tests:
	@$(COMPOSE_UP)
	@$(PYTEST) --cov=$(BASE_PACKAGE)/fitcoach --cov-fail-under=80 -o testpaths="$(UNIT_TEST_PACKAGE) $(IT_TEST_PACKAGE)"; \
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
