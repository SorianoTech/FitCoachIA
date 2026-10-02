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
