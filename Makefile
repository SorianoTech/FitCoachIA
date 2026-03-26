# Variables para personalizar fácilmente
IMAGE_NAME=fitcoach-app-image
CONTAINER_NAME=fitcoach-container
PORT=8000

.PHONY: build run stop clean all help

help:
	@echo "Comandos disponibles:"
	@echo "  make build  - Construye la imagen de Docker usando el contexto de 'src'"
	@echo "  make run    - Ejecuta el contenedor en el puerto $(PORT)"
	@echo "  make stop   - Detiene y elimina el contenedor si está corriendo"
	@echo "  make clean  - Detiene el contenedor y elimina la imagen"
	@echo "  make all    - Construye y ejecuta todo (limpiando primero)"

build:
	docker build -t $(IMAGE_NAME) -f src/Dockerfile ./src

run:
	docker run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) $(IMAGE_NAME)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@docker stop $(CONTAINER_NAME) || true
	@docker rm $(CONTAINER_NAME) || true

clean: stop
	@docker rmi $(IMAGE_NAME) || true

all: clean build run
