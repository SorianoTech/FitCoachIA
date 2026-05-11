# Dockerfile — Guía de lectura

Este Dockerfile construye la aplicación en **dos etapas**: una para instalar dependencias
y otra para ejecutar la app. El resultado es una imagen final ligera y lista para producción.

---

## Stage 1 — Builder (preparación)

| Instrucción | Qué hace |
|-------------|----------|
| `FROM python:3.11-slim AS builder` | Usa Python 3.11 como base y llama a esta etapa `builder` |
| `RUN apt-get install build-essential` | Instala herramientas de compilación necesarias para algunas librerías |
| `COPY ./requirements.txt .` | Copia la lista de dependencias al contenedor |
| `RUN pip install --prefix=/install -r requirements.txt` | Instala todas las librerías en la carpeta `/install` |
| `RUN python -m venv /opt/fitcoach` | Crea un entorno virtual aislado para la aplicación |

> **¿Para qué sirve `/install`?**
> Es una carpeta **temporal dentro del Stage 1**. Las librerías se instalan ahí
> en lugar de en el sistema, para poder moverlas en bloque al Stage 2 con
> `COPY --from=builder`. Una vez copiadas, el Stage 1 se descarta por completo
> y la imagen final solo contiene lo que llegó al Stage 2.

> **¿Y si añado nuevas dependencias al `requirements.txt`?**
> Docker construye por capas y guarda una caché de cada una. Si `requirements.txt`
> **no cambia**, el Stage 1 se salta y reutiliza la caché — la build es inmediata.
> Si **cambia**, Docker invalida la caché desde ese punto y vuelve a ejecutar
> `pip install` completo. Por eso `COPY ./requirements.txt` va siempre **antes**
> que `COPY ./fitcoach` — así cambiar solo el código no fuerza una reinstalación
> de dependencias.

---

## Stage 2 — Runtime (ejecución)

| Instrucción | Qué hace |
|-------------|----------|
| `FROM python:3.11-slim` | Empieza desde cero con una imagen limpia, sin herramientas de compilación |
| `ARG APP_LIB_DIR=/opt/fitcoach` | Define la ruta de las librerías como variable reutilizable |
| `ENV PYTHONDONTWRITEBYTECODE=1` | Evita generar archivos `.pyc` innecesarios |
| `ENV PYTHONUNBUFFERED=1` | Los logs aparecen en tiempo real en consola |
| `ENV PIP_DISABLE_PIP_VERSION_CHECK=1` | Evita comprobar actualizaciones de pip al arrancar |
| `ENV PYTHONPATH=...` | Le dice a Python dónde están las librerías instaladas |
| `ENV PATH=...` | Hace accesibles los comandos del entorno virtual (como `fastapi`) |
| `EXPOSE 8000` | Documenta que la app escucha en el puerto 8000 |
| `WORKDIR /app` | Establece `/app` como directorio de trabajo dentro del contenedor |
| `COPY --from=builder /install $APP_LIB_DIR` | Trae las librerías instaladas en el Stage 1 a esta imagen limpia |
| `COPY ./fitcoach .` | Copia el código fuente de la aplicación al contenedor |
| `ENTRYPOINT ["fastapi", "run", "/app/main.py"]` | Comando fijo que arranca la aplicación al iniciar el contenedor |
| `CMD ["--port", "8000"]` | Argumento por defecto del comando anterior — se puede sobreescribir al arrancar |

---

## ¿Por qué dos etapas?

La primera etapa necesita herramientas de compilación pesadas para instalar dependencias.
La segunda solo necesita ejecutar la app. Al separarlo, la imagen final **no arrastra
herramientas innecesarias** — es más pequeña y más segura.
