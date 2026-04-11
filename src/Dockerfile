FROM python:3.11-slim

# No genera archivos .pyc (innecesarios en contenedor)
ENV PYTHONDONTWRITEBYTECODE=1
# No bufferiza stdout/stderr (logs en tiempo real)
ENV PYTHONUNBUFFERED=1
# No comprueba si hay versión más nueva de pip (más rápido)
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

EXPOSE 8000

WORKDIR /app

COPY ./fitcoach .

# Instalar herramientas para compilar extensiones nativas de Python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "fitcoach.main:app", "--host", "0.0.0.0", "--port", "8000"]