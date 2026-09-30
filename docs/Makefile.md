<<<<<<< Updated upstream
# Comandos `make`

`make help` lista todo con una descripción corta. Este documento explica lo que no cabe ahí.

---

## Levantar entornos

Son los comandos del día a día.

| Comando | Qué hace |
|---|---|
| `make dev-up` | Construye la imagen desde el código local y levanta dev (app + Postgres + Adminer) |
| `make dev-down` | Detiene dev y retira huérfanos |
| `make dev-logs` | Sigue los logs de dev |
| `sudo make prod-up VERSION=x.y.z` | Descarga esa versión del registro y levanta producción |
| `sudo make prod-down` | Detiene producción |
| `sudo make prod-logs` | Sigue los logs de producción |

Diferencia esencial: **`dev-up` construye, `prod-up` descarga**. En producción nunca se compila; se
despliega una imagen ya publicada y escaneada.

El `sudo` de los targets de producción no es opcional: el fichero de entorno vive en una ruta con
permisos restringidos.

### Detener sin perder datos

`dev-down` y `prod-down` **no borran volúmenes**: la base de datos sobrevive. Para borrarla también
hay que llamar a Compose a mano con `-v`, que es deliberadamente incómodo.

---

## Cómo se resuelve el fichero de entorno

Cada target de entorno ejecuta antes una de estas dos rutinas, y te dice por consola cuál eligió:

```
>> entorno dev: /etc/fitcoachia/dev/.env.dev
```

**Desarrollo** — con alternativa:

```
¿existe /etc/fitcoachia/dev/.env.dev?
   sí → se usa
   no → .env.dev del repositorio
        └─ tampoco existe → ERROR
```

**Producción** — sin alternativa:

```
¿es legible /etc/fitcoachia/prod/.env.prod?
   sí → se usa
   no → ERROR: "no existe o no tiene permisos de acceso"
```

La comprobación de producción usa `-r` (legible), no `-f` (existe). La diferencia importa: sin
`sudo`, el fichero existe pero no se puede leer, y el mensaje te dice exactamente eso en vez de un
«no existe» engañoso.

### Sobrescribir la ruta

Las tres son variables de `make`, así que se pueden pasar en la llamada:

```bash
make prod-up PROD_ENV_FILE=/otra/ruta/.env.prod
make dev-up  ENV_ROOT=/tmp/config
```

Es lo que usa el workflow de despliegue para inyectar la ruta que le llega por secreto.

| Variable | Valor por defecto |
|---|---|
| `ENV_ROOT` | `/etc/fitcoachia` |
| `DEV_ENV_FILE` | `$(ENV_ROOT)/dev/.env.dev` |
| `PROD_ENV_FILE` | `$(ENV_ROOT)/prod/.env.prod` |

Una vez resuelto, el fichero se pasa a Compose **por dos vías a la vez**: `--env-file` para
interpolar `${VAR}` en el YAML, y `FITCOACH_ENV_FILE` para el `env_file:` que lo inyecta en el
contenedor. Detalle en [entornos-y-despliegue.md](entornos-y-despliegue.md#2-los-ficheros-de-entorno).

---

## Tests

| Comando | Qué hace |
|---|---|
| `make tests` | Levanta el stack de test, ejecuta unitarios e integración, exige 80 % de cobertura |

Usa el `pytest` del `.venv` del proyecto, no el del `PATH`. En CI, donde no hay venv, se sobrescribe:

```bash
make tests PYTEST=pytest
```

Levanta y tumba su propio Compose (`tests/docker-compose-test.yml`), y **devuelve el código de salida
de pytest**, no el del `down`: si los tests fallan, el comando falla aunque la limpieza vaya bien.

---

## Imagen y contenedor sueltos

Utilidades de desarrollo local, sin Compose de por medio.

| Comando | Qué hace |
|---|---|
| `make build [version=x.y.z]` | Construye la imagen; con versión, etiqueta también `latest` |
| `make run [version=x.y.z]` | Arranca el contenedor en el 8000 con el `.env` de la raíz |
| `make stop` | Detiene y elimina ese contenedor |
| `make logs` | Sigue sus logs |
| `make container` | `docker ps -a` |
| `make clean-image [version=x.y.z]` | Borra una versión concreta |
| `make clean-images` | Borra todas las imágenes de la aplicación |
| `make clean` | `stop` + `clean-images` |
| `make all` | `clean` + `build` + `run` |

Ojo con `run`: usa el `.env` de la raíz y el nombre de contenedor `fitcoach-ia`, **el mismo que
producción**. En tu máquina da igual; en el servidor chocaría.

---

## Nota sobre `version` y `VERSION`

No son lo mismo y conviven:

- **`version`** (minúsculas) — targets de imagen local (`build`, `run`, `clean-image`). Por defecto `latest`.
- **`VERSION`** (mayúsculas) — la que interpola el Compose de producción en el tag de la imagen.

Por eso `make prod-up VERSION=0.3.0` lleva mayúsculas y `make build version=0.3.0` minúsculas.
=======
# Makefile

El `Makefile` es el punto de entrada común en local y en los workflows de GitHub (`.github/`). Ejecuta `make help` para ver el listado.

## Imagen y contenedor de la aplicación

*   `make build [version=x.y.z]`: construye la imagen (`src/Dockerfile`, contexto en la raíz del repo). Por defecto `latest`; si se indica versión, etiqueta también `latest`.
*   `make run [version=x.y.z] [log_level=...]`: arranca el contenedor en segundo plano (puerto 8000) con el fichero `.env`.
*   `make stop`: detiene y elimina el contenedor.
*   `make logs`: muestra los logs del contenedor en tiempo real.
*   `make container`: lista todos los contenedores (en ejecución y detenidos).
*   `make clean`: detiene el contenedor y elimina todas las imágenes locales de la aplicación.
*   `make clean-image [version=x.y.z]`: elimina solo la imagen de esa versión (por defecto `latest`).
*   `make clean-images`: elimina todas las imágenes locales de la aplicación.
*   `make all`: limpia, construye y arranca.

## Tests

*   `make tests`: levanta `tests/docker-compose-test.yml`, ejecuta unitarios e integración con cobertura (falla si es < 80 %) y lo detiene al terminar. En CI se invoca como `make tests PYTEST=pytest`.

## Entornos (Docker Compose)

*   `make dev-up | dev-down | dev-logs`: entorno de desarrollo (`docker-compose.dev.yml`). Usa `$(ENV_ROOT)/dev/.env.dev` si existe y, si no, `.env.dev` del repositorio.
*   `make prod-up [VERSION=x.y.z] | prod-down | prod-logs`: producción (`docker-compose.yml`). Requiere `$(ENV_ROOT)/prod/.env.prod` (se puede sustituir con `PROD_ENV_FILE=ruta`). Es el target que ejecuta `deploy.yml`.
*   `make vector-up | vector-down | vector-logs`: base de datos vectorial (`infra/vector-db`), con su propio ciclo de vida. `vector-down` conserva el volumen a propósito.

## Variables configurables

| Variable | Por defecto | Uso |
|---|---|---|
| `version` | `latest` | Versión de la imagen en `build`, `run` y `clean-image` |
| `VERSION` | `latest` | Versión de la imagen en `prod-up` |
| `PORT` | `8000` | Puerto del contenedor en `run` |
| `IT_PORT` | `8001` | Puerto de la aplicación en los tests de integración |
| `PYTEST` | `.venv/Scripts/pytest.exe` | Ejecutable de pytest en `tests` |
| `ENV_ROOT` | `/etc/fitcoachia` | Raíz de los ficheros de entorno fuera del repo |
| `DEV_ENV_FILE` / `PROD_ENV_FILE` | `$(ENV_ROOT)/dev/.env.dev` / `$(ENV_ROOT)/prod/.env.prod` | Fichero de entorno de cada entorno |
>>>>>>> Stashed changes
