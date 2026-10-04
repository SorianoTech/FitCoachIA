# Dockerfile — Guía de lectura

Este Dockerfile construye la aplicación en **tres etapas**: frontend Node,
dependencias Python y runtime Python. El contexto es la raíz del repositorio:
`docker build -f src/Dockerfile .`.
Node compila `frontend/` con `npm ci` y `npm run build`; solo `dist/` llega al
runtime, en `fitcoach/static/miniapp`. No se instala Node en la imagen final.

---

## Stage 1 — Builder (preparación)

| Instrucción | Qué hace |
|-------------|----------|
| `FROM python:3.12-slim AS builder` | Usa Python 3.12 como base y llama a esta etapa `builder` |
| `RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*` | Instala herramientas de compilación necesarias para algunas librerías y limpia la caché de apt para no engordar la imagen |
| `COPY ./src/requirements.txt .` | Copia la lista de dependencias al contenedor |
| `RUN pip install --prefix=/install -q --no-cache-dir -r requirements.txt` | Instala todas las librerías en `/install` sin caché de pip ni output verboso |
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
| `FROM python:3.12-slim` | Empieza desde cero con una imagen limpia, sin herramientas de compilación |
| `ARG APP_LIB_DIR=/opt/fitcoach` | Define la ruta de las librerías como variable reutilizable |
| `ENV PYTHONDONTWRITEBYTECODE=1` | Evita generar archivos `.pyc` innecesarios |
| `ENV PYTHONUNBUFFERED=1` | Los logs aparecen en tiempo real en consola |
| `ENV PIP_DISABLE_PIP_VERSION_CHECK=1` | Evita comprobar actualizaciones de pip al arrancar |
| `ENV PYTHONPATH=...` | Le dice a Python dónde están las librerías instaladas |
| `ENV PATH=...` | Hace accesibles los comandos del entorno virtual (como `fastapi`) |
| `EXPOSE 8000` | Documenta que la app escucha en el puerto 8000 |
| `WORKDIR /app` | Establece `/app` como directorio de trabajo dentro del contenedor |
| `COPY --from=builder /install $APP_LIB_DIR` | Trae las librerías instaladas en el Stage 1 a esta imagen limpia |
| `COPY ./src/fitcoach ./fitcoach` | Copia el código fuente de la aplicación |
| `COPY --from=frontend /frontend/dist ./fitcoach/static/miniapp` | Copia los estáticos de la Mini App |
| `COPY ./alembic ./alembic` y `COPY ./alembic.ini .` | Incluye las migraciones de la base de aplicación |
| `ENTRYPOINT ["sh", "-c", "alembic upgrade head && exec fastapi run fitcoach/main.py --port 8000"]` | Aplica migraciones y arranca la API y estáticos |

---

## ¿Por qué separar las etapas?

La primera etapa necesita herramientas de compilación pesadas para instalar dependencias.
La segunda solo necesita ejecutar la app. Al separarlo, la imagen final **no arrastra
herramientas innecesarias** — es más pequeña y más segura.
