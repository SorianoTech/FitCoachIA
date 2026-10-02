# Entornos y despliegue

Cómo encajan el workflow de CI/CD, el `Makefile`, los dos Compose y los ficheros de entorno. Para el
detalle de las fases del pipeline, ver [ci-cd.md](ci-cd.md); para los comandos, [Makefile.md](Makefile.md).

---

## 1. Las tres piezas

| Pieza | Responsabilidad |
|---|---|
| **`deploy.yml`** | Copia ficheros al servidor por SSH y orquesta el cutover con rollback |
| **`Makefile`** | Resuelve **qué fichero de entorno** usar y lanza `docker compose` |
| **Compose** | Define los servicios; recibe el fichero ya resuelto |

La clave está en el reparto: el workflow **no sabe** dónde vive la configuración, solo pasa una ruta.
El `Makefile` **no sabe** desplegar, solo resolver el entorno. Por eso el mismo `make prod-up`
funciona igual lanzado a mano en el servidor que invocado por el despliegue.

---

## 2. Los ficheros de entorno

Dos ubicaciones, con reglas distintas por entorno:

| Entorno | Ubicación preferida | Si no existe |
|---|---|---|
| **dev** | `/etc/fitcoachia/dev/.env.dev` | usa `.env.dev` del repositorio |
| **prod** | `/etc/fitcoachia/prod/.env.prod` | **falla**; no hay alternativa |

La asimetría es deliberada. En desarrollo trabajas en tu máquina y no quieres crear rutas de sistema
para arrancar; en producción, un fichero olvidado que caiga silenciosamente a otro sería peor que un
error.

`/etc/fitcoachia/prod` tiene permisos restringidos: **el usuario de despliegue no puede leerlo**. Por
eso el workflow ejecuta el comando con `sudo -n` y ese usuario necesita una regla `sudoers` sin
contraseña. Ver [how-to.md](how-to.md#desplegar-producción).

### Cómo llega el fichero al contenedor

```
Makefile: resuelve la ruta
    │
    ├── export FITCOACH_ENV_FILE=<ruta>      ← para el `env_file:` del compose
    └── docker compose --env-file <ruta>     ← para interpolar ${VAR} en el YAML
```

**Son dos mecanismos distintos y ambos hacen falta**, que es la confusión más común:

- `--env-file` alimenta la **interpolación** del YAML: `${POSTGRES_PASSWORD}`, `${VERSION}`. Se
  resuelve al leer el fichero, antes de crear nada.
- `env_file:` inyecta variables **dentro del contenedor**, para que la app las lea.

Una variable que solo esté en `env_file:` no sirve para interpolar, y al revés.

---

## 3. Levantar cada entorno

### Desarrollo

```bash
make dev-up
```

Construye la imagen desde el código local (`--build`), levanta `dev-fitcoach-ia`, su Postgres y
Adminer. Usa `/etc/fitcoachia/dev/.env.dev` si existe; si no, `.env.dev` del repositorio y te avisa
por consola de cuál ha elegido.

### Producción

```bash
sudo make prod-up VERSION=0.3.0
```

**No construye nada**: descarga la imagen ya publicada con ese tag. El `sudo` hace falta porque el
fichero de entorno es de root.

| | dev | prod |
|---|---|---|
| Imagen | se construye en local | se descarga del registro |
| Compose | `docker-compose.dev.yml` | `docker-compose.yml` |
| Proyecto | `fitcoach-dev` | `fitcoach-prod` |
| Servicio app | `fitcoach-ia-dev` | `fitcoach-ia-prod` |
| Contenedor | `dev-fitcoach-ia` | `fitcoach-ia` |
| Base de datos | `postgres-dev` | `postgres-prod` |
| Extras | Adminer | — |

Ambos conviven en el mismo servidor. Los **nombres de servicio** son distintos por entorno a
propósito: Compose los registra como alias en `proxy-network`, y si coincidieran, el DNS resolvería a
dos contenedores. Ya ocurrió: el bot de producción respondía desde el contenedor de desarrollo.

---

## 4. El despliegue, paso a paso

Lo dispara `release.yml` al publicar una versión, o a mano por `workflow_dispatch`.

```
┌─ GitHub Actions ─────────────────────────────────────────┐
│  1. Valida el formato de la versión (X.Y.Z)              │
│  2. rsync por SSH: docker-compose.yml + Makefile         │
│                    → /home/<usuario>/                    │
└──────────────────────────┬───────────────────────────────┘
                           │  SCRIPT_BEFORE (sesión SSH 1)
┌──────────────────────────▼───────────────────────────────┐
│  1/4  sudo -n disponible y .env.prod legible             │
│  2/4  estado del contenedor actual (informativo)         │
│  3/4  imágenes locales                                   │
│  4/4  docker pull de la nueva imagen                     │
└──────────────────────────┬───────────────────────────────┘
                           │  SCRIPT_AFTER (sesión SSH 2)
┌──────────────────────────▼───────────────────────────────┐
│  1/6  captura la versión en servicio → rollback          │
│  2/6  retira el contenedor (conserva su imagen)          │
│  3/6  sudo -n env VERSION=… PROD_ENV_FILE=… make prod-up │
│  4/6  espera a `healthy` (10 intentos × 5 s)             │
│  5/6  limpia contenedores huérfanos                      │
│  6/6  elimina imágenes semver antiguas                   │
└──────────────────────────────────────────────────────────┘
```

Tres detalles que explican por qué está montado así:

**`SCRIPT_BEFORE` y `SCRIPT_AFTER` son sesiones SSH distintas.** Las variables no cruzan entre ellas,
por eso la versión anterior se captura en el paso 1/6 y no antes.

**Si el `docker pull` falla, `SCRIPT_AFTER` no llega a ejecutarse.** El contenedor en servicio queda
intacto: una versión inexistente en el registro no tumba producción.

**El `Makefile` viaja con el despliegue.** Por eso el `SOURCE` del rsync incluye los dos ficheros: el
servidor necesita el compose *y* la lógica de resolución del entorno.

### Si algo falla

Se descartan contenedor e imagen nuevos y se restaura la versión anterior desde la imagen retenida.
Por eso el paso 6/6 —borrar imágenes antiguas— va **al final**: hasta que la nueva versión no está
sana, la anterior es el artefacto de vuelta atrás.

Esto implica una ventana breve sin servicio en cada despliegue. Durante ella el proxy devuelve 502 y
Telegram reintenta los updates, así que no se pierden mensajes.

---

## 5. Variables por entorno

Ninguna se comparte entre dev y prod:

| Variable | Por qué difiere |
|---|---|
| `bot_telegram_token` | un bot distinto por entorno |
| `bot_telegram_secret_token` | un secreto por bot; compartirlo permitiría falsificar updates de prod desde dev |
| `bot_telegram_webhook_base_url` | cada entorno tiene su dominio público |
| `POSTGRES_PASSWORD` | bases de datos independientes |
| `ia_skill` | dev usa `interviewer-dev`, con tres preguntas |

`APP_ENV` no se configura: lo fija cada Compose (`dev` / `prod`) y de él salen la etiqueta
`deployment.environment.name` de las trazas y el sufijo del fichero `.env.<APP_ENV>` que carga la app.

---

## 6. Problemas frecuentes

| Síntoma | Causa |
|---|---|
| `no existe o no tiene permisos de acceso` al hacer `prod-up` | falta `sudo`, o la regla `sudoers` |
| `POSTGRES_PASSWORD is required` en `dev-down` | el target no pasaba `--env-file`; ya corregido |
| `password authentication failed` con Postgres sano | `POSTGRES_PASSWORD` solo se aplica al **inicializar** el volumen; cambiarlo después no altera la contraseña guardada |
| El bot no recibe nada, la app en verde | webhook registrado en otro sitio: `getWebhookInfo` |
| Conflicto de nombre de contenedor al desplegar | quedó un huérfano; `make prod-down` ya usa `--remove-orphans` |
