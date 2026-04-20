# Explica comandos make para docker
*   `make help`: Muestra todos los comandos disponibles con su descripción.
*   `make build`: Construye la imagen de Docker a partir del archivo `Dockerfile`.
*   `make run [version=x.y.z]`: Inicia el contenedor en segundo plano (puerto 8000). Si no se indica versión, usa `latest`.
*   `make stop`: Detiene y elimina el contenedor que está en ejecución.
*   `make clean`: Detiene el contenedor y elimina todas las imágenes locales de la aplicación para liberar espacio.
*   `make all`: Secuencia completa: detiene, construye y arranca el contenedor de nuevo.
*   `make container`: Muestra todos los contenedores (en ejecución y detenidos).
*   `make images`: Muestra todas las imágenes Docker disponibles en local.
*   `make tag version=x.y.z`: Aplica un tag de versión a la imagen `latest` local (ej: `make tag version=1.0.0`).


