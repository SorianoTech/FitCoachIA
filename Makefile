# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_BASE=fitcoachia/fitcoach-app
IMAGE_LATEST=$(IMAGE_BASE):latest
CONTAINER_NAME=fitcoach-ia
PORT=8000
version ?= latest

.PHONY: container build run stop clean all help tag images clean-images

help:
	@echo "Comandos disponibles Docker"
	@echo "  make container                      - Consulta los contenedores"
	@echo "  make build [version=x.y.z]          - Construye la imagen de Docker (Por defecto, latest). Si indicas version, genera las imagenes latest y x.y.z (Defecto: latest)"
	@echo "  make run [version=x.y.z]            - Ejecuta el contenedor con la imagen (previamente generada) latest o version x.y.z indicada en el puerto $(PORT)"
	@echo "  make stop                           - Detiene y elimina el contenedor si está corriendo"
	@echo "  make clean                          - Detiene el contenedor y elimina todas las imagenes $(IMAGE_BASE)"
	@echo "  make all                            - Construye y ejecuta todo (limpiando primero)"
	@echo "  make images                         - Consulta las imagenes en local"
	@echo "  make clean-images                   - Elimina todas las imagenes en local"
	@echo "  make tag version=x.y.z              - Versiona la imagen local latest a la version deseada"

container:
	@$(DOCKER) ps -a
	
build:
	@$(DOCKER) build -t $(IMAGE_BASE):$(version) -f src/Dockerfile ./src
	@if [ "$(version)" != "latest" ]; then \
		$(DOCKER) tag $(IMAGE_BASE):$(version) $(IMAGE_LATEST); \
		echo "Imagen construida: $(IMAGE_BASE):$(version) (también etiquetada como latest)"; \
	else \
		echo "Imagen construida: $(IMAGE_LATEST)"; \
	fi

run: 
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@$(DOCKER) run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) $(TARGET_IMAGE)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@$(DOCKER) stop $(CONTAINER_NAME) || true
	@$(DOCKER) rm $(CONTAINER_NAME) || true

clean: stop clean-images

all: clean build run

images:
	@$(DOCKER) images

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
