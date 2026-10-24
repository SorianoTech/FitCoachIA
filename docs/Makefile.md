# Comandos `make`

`make help` lista todo con una descripción corta. Este documento explica lo que no cabe ahí.

---

## Levantar el entorno

Son los comandos del día a día. Hay un único entorno (`docker-compose.yml`).

| Comando | Qué hace |
|---|---|
| `make up` | Crea las redes si faltan, construye las imágenes y levanta app, embedder, Postgres y pgAdmin; con `--remove-orphans`, elimina servicios que ya no están en el Compose |
| `make app` | Reconstruye y reinicia solo la API (`--no-deps`; el resto debe estar ya levantado) |
| `make down` | Detiene el stack y retira huérfanos |
| `make app-logs` | Sigue los logs del stack |

La imagen **siempre se construye** donde se ejecuta `make up` (en el servidor, el workflow copia el
código de la versión); no se descarga de ningún registro.

En el servidor se usa `sudo make up`: el fichero de entorno vive en una ruta con permisos
restringidos.

### Detener sin perder datos

`down` **no borra volúmenes** (`fitcoach-postgres`, `fitcoach-pgadmin`): la base de datos sobrevive. Para
borrarla también hay que llamar a Compose a mano con `-v`, que es deliberadamente incómodo.

---

## Cómo se resuelve el fichero de entorno

Cada target de entorno (`up`, `app`, `down`, `app-logs`) ejecuta antes esta rutina y te dice por consola
cuál eligió:

```
¿es legible $(ENV_FILE)?   (por defecto /etc/fitcoachia/dev/.env.dev)
   sí → se usa
   no → .env de la raíz del repositorio (con aviso)
        └─ tampoco existe → ERROR
```

La comprobación usa `-r` (legible), no `-f` (existe): sin `sudo`, un fichero de root existe pero no se
puede leer, y por eso se cae al `.env` o se muestra el error indicándolo.

### Sobrescribir la ruta

`ENV_FILE` es una variable de `make`, así que se puede pasar en la llamada:

```bash
make up ENV_FILE=/otra/ruta/.env
```

Una vez resuelto, el fichero se pasa a Compose **por dos vías a la vez**: `--env-file` para
interpolar `${VAR}` en el YAML, y `FITCOACH_ENV_FILE` para el `env_file:` que lo inyecta en el
contenedor. Detalle en [entornos-y-despliegue.md](entornos-y-despliegue.md#2-el-fichero-de-entorno).

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
el del Compose**. En tu máquina da igual; con el stack levantado chocaría.

---

## Nota sobre `version`

`version` (minúsculas) solo afecta a los targets de imagen local (`build`, `run`, `clean-image`); por
defecto `latest`. El Compose no interpola ninguna versión: `make up` siempre construye desde el código.
