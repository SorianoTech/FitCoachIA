# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_NAME=fitcoach-app-image
CONTAINER_NAME=fitcoach-container
PORT=8000

.PHONY: build run stop clean all help docker_image_pull docker_image_push

help:
	@echo "Comandos disponibles:"
	@echo "  make build  - Construye la imagen de Docker usando el contexto de 'src'"
	@echo "  make run    - Ejecuta el contenedor en el puerto $(PORT)"
	@echo "  make stop   - Detiene y elimina el contenedor si está corriendo"
	@echo "  make clean  - Detiene el contenedor y elimina la imagen"
	@echo "  make all    - Construye y ejecuta todo (limpiando primero)"
	@echo "  make docker_image_pull   - Obtiene la imagen del repositorio de docker.
	@echo "  make docker_image_push   - Sube la imagen con tag latest al dockerhub.

build:
	@$(DOCKER) build -t $(IMAGE_NAME) -f src/Dockerfile ./src

run:
	@$(DOCKER) run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) $(IMAGE_NAME)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@$(DOCKER) stop $(CONTAINER_NAME) || true
	@$(DOCKER) rm $(CONTAINER_NAME) || true

clean: stop
	@$(DOCKER) rmi $(IMAGE_NAME) || true

all: clean build run

docker_image_pull:
	@echo "Iniciando sesión en Docker Hub..."
	@$(DOCKER) login; \
	if [ $$? -ne 0 ]; then \
		echo "Error: docker login fallido. Abortando pull."; \
		exit 1; \
	fi; \
	echo "Login exitoso. Comprobando si existe la imagen local $(IMAGE_NAME):latest..."; \
	if @$(DOCKER) image inspect $(IMAGE_NAME):latest > /dev/null 2>&1; then \
		echo "Imagen local encontrada. Eliminando..."; \
		@$(DOCKER) rmi $(IMAGE_NAME):latest; \
	fi; \
	echo "Obteniendo imagen $(IMAGE_NAME):latest del repositorio..."; \
	@$(DOCKER) pull $(IMAGE_NAME):latest

docker_image_push:
	@echo "Iniciando sesión en Docker Hub..."
	@$(DOCKER) login; \
	if [ $$? -ne 0 ]; then \
		echo "Error: docker login fallido. Abortando push."; \
		exit 1; \
	fi; \
	echo "Login exitoso. Buscando imagen $(IMAGE_NAME):latest..."; \
	if ! $(DOCKER) image inspect $(IMAGE_NAME):latest > /dev/null 2>&1; then \
		echo "Error: no se encontró la imagen $(IMAGE_NAME):latest. Ejecuta 'make build' primero."; \
		exit 1; \
	fi; \
	echo "Imagen encontrada. Realizando push al repositorio..."; \
	@$(DOCKER) push $(IMAGE_NAME):latest
