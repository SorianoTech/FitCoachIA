# Explica comandos make para docker
*   `make build`: Construye la imagen de Docker a partir del archivo `Dockerfile`.
*   `make run`: Inicia el contenedor en segundo plano (puerto 8000).
*   `make stop`: Detiene y elimina el contenedor que está en ejecución.
*   `make clean`: Detiene el contenedor y elimina la imagen para liberar espacio.
*   `make all`: Secuencia completa: detiene, construye y arranca el contenedor de nuevo.
*   `make docker_image_pull`: Hace login en Docker Hub, elimina la imagen local si existe y descarga la imagen `latest` del repositorio.
*   `make docker_image_push`: Hace login en Docker Hub y sube la imagen local `latest` al repositorio.


