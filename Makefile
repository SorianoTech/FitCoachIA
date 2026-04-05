# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_BASE=fitcoachia/fitcoach-app
IMAGE_LATEST=$(IMAGE_BASE):latest
CONTAINER_NAME=fitcoach-container
PORT=8000
version ?= latest

.PHONY: container build run stop clean all help pull_image push_image tag, images

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
	@echo "  make pull_image [version=x.y.z]     - Obtiene la imagen del repositorio de docker (Por defecto, latest)"
	@echo "  make push_image [version=x.y.z]     - Si existe, sube la imagen:tag al repositorio (Por defecto, latest)"

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

pull_image:
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@$(DOCKER) login -u fitcoachia; \
	if [ $$? -ne 0 ]; then \
		echo "Error: docker login fallido. Abortando pull."; \
		exit 1; \
	fi; \
	echo "Comprobando si existe la imagen local $(TARGET_IMAGE)..."; \
	if $(DOCKER) image inspect $(TARGET_IMAGE) > /dev/null 2>&1; then \
		echo "Imagen local encontrada. Eliminando..."; \
		$(DOCKER) rmi $(TARGET_IMAGE); \
	fi; \
	echo "Obteniendo imagen $(TARGET_IMAGE) del repositorio..."; \
	$(DOCKER) pull $(TARGET_IMAGE)

push_image:
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@echo "Buscando imagen local $(TARGET_IMAGE)..."; \
	if ! $(DOCKER) image inspect $(TARGET_IMAGE) > /dev/null 2>&1; then \
		echo "Error: no se encontró la imagen $(TARGET_IMAGE). Ejecuta 'make build' o 'make tag version=$(TAG)' primero."; \
		exit 1; \
	fi; \
	echo "Imagen encontrada. Iniciando sesión en Docker Hub..."; \
	$(DOCKER) login -u fitcoachia; \
	if [ $$? -ne 0 ]; then \
		echo "Error: docker login fallido. Abortando push."; \
		exit 1; \
	fi; \
	echo "Realizando push de $(TARGET_IMAGE)..."; \
	$(DOCKER) push $(TARGET_IMAGE)
