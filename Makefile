# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_BASE=fitcoachia/fitcoach-app
IMAGE_LATEST=$(IMAGE_BASE):latest
CONTAINER_NAME=fitcoach-container
PORT=8000
version ?= latest

.PHONY: container build run stop clean all help tag images

help:
	@echo "Comandos disponibles Docker"
	@echo "  make container                      - Consulta los contenedores"
	@echo "  make build                          - Construye la imagen de Docker usando el contexto de 'src'"
	@echo "  make run [version=x.y.z]            - Ejecuta el contenedor con la imagen 'version' (defecto, latest) en el puerto $(PORT)"
	@echo "  make stop                           - Detiene y elimina el contenedor si está corriendo"
	@echo "  make clean                          - Detiene el contenedor y elimina todas las imagenes $(IMAGE_BASE)"
	@echo "  make all                            - Construye y ejecuta todo (limpiando primero)"
	@echo "  make images                         - Consulta las imagenes en local"
	@echo "  make tag version=x.y.z              - Versiona la imagen local latest a la version deseada"

container:
	@$(DOCKER) ps -a
	
build:
	@$(DOCKER) build -t $(IMAGE_LATEST) -f src/Dockerfile ./src

run:
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@$(DOCKER) run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) $(TARGET_IMAGE)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@$(DOCKER) stop $(CONTAINER_NAME) || true
	@$(DOCKER) rm $(CONTAINER_NAME) || true

clean: stop
	@$(DOCKER) rmi -f $$($(DOCKER) images $(IMAGE_BASE) -q) 2>/dev/null || true

all: clean build run

images:
	@$(DOCKER) images

tag:
	@if [ -z "$(version)" ]; then \
		echo "Error: debes indicar la versión. Uso: make tag version=1.0.0"; \
		exit 1; \
	fi; \
	echo "Buscando imagen local $(IMAGE_LATEST)..."; \
	if ! $(DOCKER) image inspect $(IMAGE_LATEST) > /dev/null 2>&1; then \
		echo "Error: no se encontró la imagen $(IMAGE_LATEST) en local. Ejecuta 'make build' primero."; \
		exit 1; \
	fi; \
	echo "Imagen encontrada. Aplicando tag $(IMAGE_BASE):$(version)..."; \
	$(DOCKER) tag $(IMAGE_LATEST) $(IMAGE_BASE):$(version); \
	echo "Tag aplicado. Imágenes disponibles para $(IMAGE_BASE):"; \
	$(DOCKER) images $(IMAGE_BASE)
