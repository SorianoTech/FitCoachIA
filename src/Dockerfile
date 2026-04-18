# Stage 1: Ejecuta todos los requerimientos para ejecutar la aplicación
FROM python:3.11-slim AS builder

# Instalar herramientas para compilar extensiones nativas de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .
RUN pip install --prefix=/install -q --no-cache-dir -r requirements.txt
RUN python -m venv /opt/fitcoach

# Stage 2: runtime (imagen final limpia, sin build-essential)
FROM python:3.11-slim

ARG APP_LIB_DIR=/opt/fitcoach

# No genera archivos .pyc (innecesarios en contenedor)
ENV PYTHONDONTWRITEBYTECODE=1
# No bufferiza stdout/stderr (logs en tiempo real)
ENV PYTHONUNBUFFERED=1
# No comprueba si hay versión más nueva de pip (más rápido)
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# Configuramos las rutas a las librerias para que Python encuentre todo
ENV PYTHONPATH=$APP_LIB_DIR/lib/python3.11/site-packages
# Configurar el path para ejecutar la aplicación
ENV PATH="$APP_LIB_DIR/bin:$PATH"

EXPOSE 8000

WORKDIR /app

COPY --from=builder /install $APP_LIB_DIR

COPY ./fitcoach .

ENTRYPOINT ["fastapi", "run","/app/main.py"]

CMD ["--port", "8000"]