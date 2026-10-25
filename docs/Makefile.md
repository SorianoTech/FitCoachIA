# Comandos `make`

`make help` lista todo con una descripción corta. Este documento explica lo que no cabe ahí.

---

## Levantar entornos

Son los comandos del día a día. Todos usan el único `docker-compose.yml` de la raíz: cada host tiene
un solo entorno, y lo que cambia entre dev y prod es el fichero de entorno y si se construye o se
descarga.

| Comando | Qué hace |
|---|---|
| `make dev-up` | Construye las imágenes desde el código local y levanta todo el sistema; con `--remove-orphans`, elimina servicios que ya no están en el Compose |
| `make dev-app` | Reconstruye y reinicia solo la app (`--no-deps`: no toca el embedder ni las bases de datos) |
| `make dev-down` | Detiene el sistema y retira huérfanos |
| `make dev-logs` | Sigue los logs de todos los servicios |
| `make prod-up VERSION=x.y.z` | Descarga las imágenes (`pull`) y levanta producción **sin construir** (`--no-build`), retirando huérfanos; espera hasta `PROD_WAIT_TIMEOUT` segundos (900 por defecto) a que todos los servicios con *healthcheck* estén `healthy` y falla si no lo consigue |
| `make prod-down` | Detiene producción |
| `make prod-logs` | Sigue los logs de producción |
| `make vector-up` | Construye y levanta solo `pgvector` (el catálogo de ejercicios) |
| `make vector-down` | Detiene `pgvector` sin borrar su volumen |
| `make vector-logs` | Sigue los logs de `pgvector` |

Diferencia esencial: **`dev-up` construye, `prod-up` descarga**. En producción nunca se compila; se
despliegan imágenes ya publicadas en Docker Hub. Si falta alguna, `prod-up` falla antes de arrancar
nada.

`VERSION` solo fija la imagen de la app. El resto de imágenes propias (embedder, `pgvector` y las de
observabilidad) llevan su tag fijo en el `docker-compose.yml`.

Las redes las crea el propio Compose: el `Makefile` ya no crea redes externas.

### Detener sin perder datos

`dev-down`, `prod-down` y `vector-down` **no borran volúmenes**: las bases de datos sobreviven. Para
borrarlas también hay que llamar a Compose a mano con `-v`, que es deliberadamente incómodo.

---

## Cómo se resuelve el fichero de entorno

Cada target de entorno comprueba antes su fichero y te dice por consola cuál usa:

```
>> entorno dev: .env
```

| Variable | Valor por defecto | Si no existe |
|---|---|---|
| `DEV_ENV_FILE` | `.env` (raíz del repositorio) | ERROR |
| `PROD_ENV_FILE` | `/opt/fitcoachia/.env` | ERROR: «no existe o no tiene permisos de acceso» |

La comprobación de producción usa `-r` (legible), no `-f` (existe): si el fichero existe pero tu
usuario no puede leerlo, el mensaje te dice exactamente eso.

Las dos son variables de `make`, así que se pueden pasar en la llamada:

```bash
make prod-up VERSION=1.2.0 PROD_ENV_FILE=/otra/ruta/.env
make dev-up DEV_ENV_FILE=.env.dev
```

Una vez resuelto, el fichero se pasa a Compose **por dos vías a la vez**: `--env-file` para
interpolar `${VAR}` en el YAML, y `FITCOACH_ENV_FILE` para el `env_file:` que lo inyecta en los
contenedores.

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
- **`VERSION`** (mayúsculas) — la que interpola el Compose en el tag de la imagen de la app.

Por eso `make prod-up VERSION=0.3.0` lleva mayúsculas y `make build version=0.3.0` minúsculas.
