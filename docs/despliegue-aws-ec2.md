# Despliegue en AWS sobre una única instancia EC2

Variante de despliegue en AWS que **reproduce el servidor actual** en una instancia EC2 con los
mínimos cambios en el repositorio. Los Compose, el `Makefile`, el `deploy.yml` por SSH, los ficheros
`/etc/fitcoachia/<entorno>/.env.<entorno>` y Nginx Proxy Manager se usan igual que hoy; lo único que
cambia es la máquina en la que corren.

Para el contexto general ver [entornos-y-despliegue.md](entornos-y-despliegue.md) y
[ci-cd.md](ci-cd.md). La alternativa con ECS Fargate + RDS está descrita fuera del repositorio, en la
documentación de arquitectura del proyecto.

---

## 1. Resumen

| Pieza | Hoy (servidor actual) | En AWS | ¿Cambia algo en el repo? |
|---|---|---|---|
| Máquina | Servidor propio | EC2 `t3.large` (2 vCPU, 8 GB, x86_64), Ubuntu 24.04 LTS | No |
| Contenedores | `docker-compose.yml` + Compose de pgVector | Los mismos | No |
| Proxy y TLS | Nginx Proxy Manager en `proxy-network` | El mismo, con [nginx-proxy-manager.compose.yml](../infra/aws/ec2/nginx-proxy-manager.compose.yml) | Fichero nuevo de referencia |
| Secretos | `/etc/fitcoachia/prod/.env.prod` (root) | Igual | No |
| Despliegue | `deploy.yml`: SSH + `sudo make prod-up` | Igual; solo cambian los secretos `SERVER_*` de GitHub | No |
| Imágenes | Docker Hub | Docker Hub | No |
| Dominio | DNS actual | Mismo dominio; registro `A` a la Elastic IP | No |
| Backups | — | Snapshots EBS diarios (DLM) + `pg_dump` nocturno a S3 | Script nuevo |
| Arranque del host | Manual | [user-data.sh](../infra/aws/ec2/user-data.sh) (cloud-init) | Script nuevo |
| Huérfanos al desplegar | `prod-up` no los quitaba | `dev-up` y `prod-up` llevan `--remove-orphans` | Arreglo en el `Makefile` |

Se elige **x86_64** (`t3`) y no Graviton (`t4g`, ~13 $/mes más barato) porque las imágenes actuales
solo se publican para `amd64` y porque permite copiar los volúmenes de Postgres tal cual. Pasar a
ARM exige builds multiarquitectura y queda como mejora posterior.

Coste orientativo en `eu-west-1`, bajo demanda: **≈ 75 USD/mes** solo producción (≈ 52 $ con un
Savings Plan de 1 año). Detalle en la [sección 7](#7-coste).

## 2. Diagrama

```
                        Internet
   Telegram ──webhook──┐        ┌── Usuario (Mini App)
                       ▼        ▼
              DNS: api.<dominio>  A  →  Elastic IP
                       │
┌──────────── EC2 t3.large · Ubuntu 24.04 · SG: 80, 443, 22 ─────────────────┐
│                                                                             │
│  proxy-network                                                              │
│   ├─ nginx-proxy-manager  :80 :443  (admin :81 solo en 127.0.0.1)           │
│   └─ fitcoach-ia (API + bot + scheduler) :8000                              │
│                                                                             │
│  fitcoach-prod-internal                                                     │
│   ├─ fitcoach-ia ──► fitcoach-embedder :8100                                │
│   ├─ fitcoach-ia ──► fitcoach-postgres (PG 16)       volumen EBS            │
│   ├─ fitcoach-ia ──► pgvector-prod (PG 18 + pgvector) volumen EBS           │
│   └─ pgadmin (sin publicar; acceso por túnel)                               │
│                                                                             │
│  cron 03:30 ─► backup-postgres.sh ─► S3 (fitcoach-backups-…)                │
└─────────────────────────────────────────────────────────────────────────────┘
        │ salida HTTPS: Telegram, OpenAI/OpenRouter, Sentry, Docker Hub
        ▼
GitHub Actions ──SSH (deploy.yml sin cambios)──► sudo make prod-up VERSION=x.y.z
```

## 3. Recursos de AWS

Todo se puede crear desde la consola; abajo van los valores. Región por defecto `eu-west-1`
(Irlanda); `eu-south-2` (Madrid) también vale si se prefiere latencia o residencia en España.

### 3.1 Red y seguridad
- **VPC por defecto** y una subred pública. No hace falta NAT ni balanceador.
- **Elastic IP** asociada a la instancia: el DNS y los secretos de GitHub no cambian si se
  reemplaza la máquina.
- **Security group `fitcoach-ec2`**:

  | Puerto | Origen | Para qué |
  |---|---|---|
  | 443/tcp | 0.0.0.0/0 | Webhook de Telegram y Mini App |
  | 80/tcp | 0.0.0.0/0 | Redirección a HTTPS y reto HTTP-01 de Let's Encrypt |
  | 22/tcp | 0.0.0.0/0 | `deploy.yml` desde los runners de GitHub (IPs variables). Solo clave, sin contraseña |

  No abrir 81 (admin de NPM), 8000 (la API publica ese puerto en el host, pero solo debe llegarle
  NPM), 5432/5433 ni 8100. Docker publica puertos saltándose `ufw`, así que **el security group es la
  barrera real**.
- Si se quiere cerrar el 22 más adelante: runner autoalojado o SSM Run Command desde el workflow.
  Implica tocar `deploy.yml` y queda fuera de esta variante.

### 3.2 Instancia
- AMI **Ubuntu Server 24.04 LTS (x86_64)**, tipo **`t3.large`**, crédito *unlimited* (el valor por
  defecto en `t3`; el embedder tiene picos cortos de CPU).
- Disco raíz **gp3 de 40 GB** (imágenes: ~3 GB el embedder; volúmenes: ~1 GB). Con dev en la misma
  máquina, 60 GB.
- **Rol de instancia** `fitcoach-ec2-role` con:
  - `AmazonSSMManagedInstanceCore` (consola y túneles por Session Manager, sin abrir puertos).
  - Una política propia que permita `s3:PutObject` sobre `arn:aws:s3:::<bucket-backups>/*`.
- **User data**: el contenido de [`infra/aws/ec2/user-data.sh`](../infra/aws/ec2/user-data.sh),
  editando antes `DEPLOY_USER` y `DEPLOY_SSH_PUBKEY` (la clave pública cuya privada está en el secreto
  `SERVER_PKEY` de GitHub).
- Protección contra terminación activada.

### 3.3 Backups
- **S3**: bucket privado `fitcoach-backups-<sufijo>`, cifrado SSE-S3, bloqueo de acceso público y
  regla de ciclo de vida que borre `postgres/` a los 30 días.
- **Data Lifecycle Manager**: política de snapshots diarios del volumen raíz, con retención de 7.
  Recupera la máquina entera; el `pg_dump` a S3 recupera una base concreta y es portable.

### 3.4 Vigilancia mínima
- Alarma de CloudWatch sobre `StatusCheckFailed_System` con la acción *Recover this instance*
  (conserva la Elastic IP y el disco).
- Alarma sobre `CPUCreditBalance` bajo y `CPUSurplusCreditsCharged` > 0, para detectar si `t3.large`
  se queda corta.
- Sentry y, si se mantiene, el stack de [observabilidad](observabilidad.md) siguen igual. Ese stack
  no cabe con holgura en 8 GB junto a producción: ver la [sección 7](#7-coste).

## 4. Preparar la instancia

`user-data.sh` deja la máquina como el servidor actual:

1. Docker Engine (≥ 25, necesario por `start_interval` de los healthchecks) y el plugin Compose
   desde el repositorio oficial de Docker, `make`, `git` y la AWS CLI.
2. Rotación de logs de Docker (`json-file`, 3 × 10 MB por contenedor) para no llenar el disco.
3. 2 GB de swap, como colchón ante picos de memoria.
4. Usuario de despliegue en el grupo `docker`, con la clave pública de GitHub Actions y la regla
   `sudoers` que exige `deploy.yml` ([how-to.md](how-to.md#desplegar-producción)).
5. `/etc/fitcoachia/prod` y `/etc/fitcoachia/dev` propiedad de root con permisos `700`.
6. Las redes `proxy-network` y `fitcoach-prod-internal`.

Su salida queda en `/var/log/cloud-init-output.log`. Después, a mano y una sola vez:

```bash
# Entrar sin abrir más puertos
aws ssm start-session --target <instance-id>

# Repositorio en el host: hace falta para el Compose de pgVector (build con el DDL)
sudo git clone https://github.com/SorianoTech/FitCoachIA.git /opt/fitcoachia
cd /opt/fitcoachia && sudo git checkout <tag-o-rama-desplegada>

# Secretos de producción: copiar los dos ficheros del servidor actual. Son distintos:
# el de la app y el del Compose de pgVector (credenciales de esa base y de sus roles).
sudo install -m 600 -o root -g root ./app.env.prod /etc/fitcoachia/prod/.env.prod
sudo install -m 600 -o root -g root ./vector-db.env.prod /opt/fitcoachia/infra/vector-db/.env.prod

# Si los repositorios de Docker Hub son privados, login como usuario de despliegue
sudo -iu <DEPLOY_USER> docker login
```

## 5. Migrar desde el servidor actual

El orden importa: **nunca puede haber dos producciones vivas con el mismo bot**, porque las dos
registrarían el webhook y sus schedulers enviarían avisos y encuestas desde bases distintas.

1. **Días antes**: bajar el TTL del registro DNS del dominio de la API a 60 s.
2. **Preparar el proxy** en la EC2:

   ```bash
   cd /opt/fitcoachia
   sudo docker compose -f infra/aws/ec2/nginx-proxy-manager.compose.yml up -d
   # Admin por túnel: aws ssm start-session --target <id> \
   #   --document-name AWS-StartPortForwardingSession --parameters portNumber=81,localPortNumber=8081
   ```

   Crear el Proxy Host igual que hoy ([telegram-miniapp.md](telegram-miniapp.md#nginx-proxy-manager)):
   destino `fitcoach-ia-prod`, puerto `8000`, `http`, Force SSL. Para tener el certificado **antes**
   del cambio de DNS, pedirlo con reto DNS-01 desde NPM (si el proveedor de DNS está soportado); si
   no, pedirlo justo después del paso 5, con unos minutos de errores TLS que Telegram reintenta.
3. **Parar producción en el servidor actual** (Telegram guarda los updates pendientes hasta 24 h):

   ```bash
   sudo make prod-down
   docker compose -f infra/vector-db/docker-compose.vector-db.prod.yml down   # desde infra/vector-db
   ```

4. **Copiar los dos volúmenes de Postgres.** Misma imagen, misma versión mayor y misma
   arquitectura (x86_64), así que se copian los ficheros tal cual, sin `pg_dump`/`pg_restore` y sin
   tocar el DDL de pgVector:

   ```bash
   # En el servidor actual: localizar los volúmenes (llevan el prefijo del proyecto Compose)
   docker volume ls | grep -E 'fitcoach-prod-postgres|pgvector-prod_volume'
   for v in fitcoach-prod_fitcoach-prod-postgres fitcoach-vector-db-prod_pgvector-prod_volume; do
     docker run --rm -v "$v":/data -v "$PWD":/backup alpine tar czf "/backup/$v.tgz" -C /data .
   done
   # Copiar los .tgz a la EC2 (scp o vía S3) y en la EC2:
   for v in fitcoach-prod_fitcoach-prod-postgres fitcoach-vector-db-prod_pgvector-prod_volume; do
     docker volume create "$v"
     docker run --rm -v "$v":/data -v "$PWD":/backup alpine tar xzf "/backup/$v.tgz" -C /data
   done
   ```

   Hay que crear los volúmenes con **el mismo nombre** que tenían para que Compose los reutilice en
   lugar de crear unos vacíos (que, en el caso de pgVector, se rellenarían con la carga inicial y
   perderían los ejercicios publicados después). Compose avisará de que el volumen "ya existe pero no
   lo creó Compose": es esperado y lo usa igualmente.
5. **Arrancar en la EC2 y mover el DNS**:

   ```bash
   cd /opt/fitcoachia/infra/vector-db
   sudo docker compose -f docker-compose.vector-db.prod.yml up -d --build
   cd /home/<DEPLOY_USER>
   # Propiedad del usuario de despliegue: deploy.yml los sobrescribe por rsync con ese usuario
   sudo install -m 644 -o <DEPLOY_USER> -g <DEPLOY_USER> /opt/fitcoachia/docker-compose.yml /opt/fitcoachia/Makefile .
   sudo make prod-up VERSION=<versión en servicio>
   ```

   Cambiar el registro `A` a la Elastic IP. Al arrancar, la API vuelve a registrar el webhook con
   `bot_telegram_webhook_base_url`, que no cambia.
6. **Actualizar los secretos de GitHub** `SERVER_HOST` (Elastic IP o nombre DNS) y, si cambia,
   `SERVER_USER`. `SERVER_PKEY`, `DOCKER_IMAGE_NAME` y `ENV_FILE_PATH` siguen igual. A partir de aquí
   los despliegues van por `deploy.yml` como hoy.
7. **Comprobar**: `docker ps` (todo `healthy`), `getWebhookInfo` del bot sin errores, un mensaje de
   prueba, la Mini App, y el primer backup en S3 al día siguiente.
8. **Rollback** mientras no se borre nada en el servidor antiguo: devolver el DNS, `make prod-up`
   allí. Los datos escritos en la EC2 entretanto se perderían, así que conviene decidir pronto.

## 6. Backups

[`infra/aws/ec2/backup-postgres.sh`](../infra/aws/ec2/backup-postgres.sh) hace un `pg_dump` en
formato custom de cada base (relacional y vectorial) **dentro de su contenedor**, con las
credenciales que ya tiene el propio contenedor, y lo sube a S3 con el rol de la instancia:

```bash
sudo install -m 750 /opt/fitcoachia/infra/aws/ec2/backup-postgres.sh /usr/local/bin/fitcoach-backup
echo '30 3 * * * root BACKUP_BUCKET=fitcoach-backups-<sufijo> /usr/local/bin/fitcoach-backup >> /var/log/fitcoach-backup.log 2>&1' \
  | sudo tee /etc/cron.d/fitcoach-backup
```

Restaurar una base:

```bash
aws s3 cp s3://fitcoach-backups-<sufijo>/postgres/<fecha>/fitcoach-postgres.dump .
docker exec -i fitcoach-postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < fitcoach-postgres.dump
```

## 7. Coste

`eu-west-1`, bajo demanda, USD/mes, precios de lista de referencia (confirmar en el
[AWS Pricing Calculator](https://calculator.aws/)). No incluye el LLM.

| Concepto | Solo prod (`t3.large`, 8 GB) | Prod + dev (`t3.xlarge`, 16 GB) |
|---|---|---|
| Instancia | 66,60 | 133,20 |
| EBS gp3 (40 / 60 GB) | 3,50 | 5,30 |
| Elastic IP | 3,65 | 3,65 |
| Snapshots + S3 de backups | ~1 | ~1,50 |
| Transferencia (< 100 GB/mes) | 0 | 0 |
| **Total** | **≈ 75** | **≈ 143** |

- Con un **Savings Plan de 1 año** sin pago inicial, la instancia baja ~35 %: ≈ 52 $ y ≈ 100 $.
- El **stack de observabilidad** (Grafana, Loki, Tempo, Prometheus, Collector, Alloy) añade 1,5–2 GB:
  con producción sola cabe justo en `t3.large`; con dev, ya en `t3.xlarge`.
- `t3.medium` (4 GB, ≈ 40 $) no se recomienda: embedder + dos Postgres + API rondan 3–4 GB.
  Medir con `docker stats --no-stream` en el servidor actual antes de bajar de tamaño.

## 8. Qué no cambia y por qué

Para mantener los cambios al mínimo, esta variante deja a propósito como está:

- **Migraciones en el `ENTRYPOINT`** (`src/Dockerfile`): con una sola réplica de la API no hay
  carreras. Solo habría que sacarlas al pasar a varias réplicas (ECS).
- **Dos Postgres en contenedor** y el nombre `fitcoach` en ambas: siguen en contenedores separados,
  así que no chocan.
- **Volcado `pg_dumpall` de PG 18** en la imagen de pgVector: el contenedor es el mismo y se migra el
  volumen, así que no se vuelve a cargar.
- **Docker Hub** como registro y **el DNS** donde esté hoy: Route 53 y ECR no aportan nada aquí.
- **`proxy-network` y las redes internas**: idénticas.

## 9. Puntos a confirmar antes de migrar

1. **Imagen del embedder.** `docker-compose.yml` usa `fitcoachia/embedder:${VERSION}`, pero ningún
   workflow construye ni publica esa imagen. En una máquina nueva, `make prod-up` falla al no poder
   descargarla salvo que se haya publicado a mano para esa versión. Opciones: publicarla en
   `release.yml` junto a la de la app, o construirla en el host con la misma etiqueta antes del
   primer despliegue.
2. **Entorno de desarrollo**: dejarlo en el servidor actual (por defecto en este documento) o
   moverlo a la EC2 con `t3.xlarge`.
3. **Región**: `eu-west-1` (por defecto) o `eu-south-2`.
