# Despliegue en AWS sobre una única instancia EC2

Variante de despliegue en AWS que **reproduce el servidor actual** en una instancia EC2 con los
mínimos cambios en el repositorio. Los Compose, el `Makefile`, el `deploy.yml` por SSH, los ficheros
`/etc/fitcoachia/<entorno>/.env.<entorno>`, Nginx Proxy Manager y el stack de observabilidad del
proyecto (Grafana, Loki, Tempo, Prometheus, OTel Collector y Alloy) se usan igual que hoy; lo único
que cambia es la máquina en la que corren. La infraestructura de AWS se crea con una plantilla de
**CloudFormation**: [`infra/aws/ec2/fitcoach-ec2.cfn.yaml`](../infra/aws/ec2/fitcoach-ec2.cfn.yaml).

No se usan servicios de observabilidad de AWS (CloudWatch Logs, X-Ray, Managed Grafana): trazas,
logs y métricas siguen en el stack de [observabilidad.md](observabilidad.md).

Para el contexto general ver [entornos-y-despliegue.md](entornos-y-despliegue.md) y
[ci-cd.md](ci-cd.md).

---

## 1. Resumen

| Pieza | Hoy (servidor actual) | En AWS | ¿Cambia algo en el repo? |
|---|---|---|---|
| Máquina | Servidor propio | EC2 `t3.large` (2 vCPU, 8 GB, x86_64), Ubuntu 24.04 LTS | No |
| Infraestructura | Manual | Plantilla CloudFormation | Fichero nuevo |
| Contenedores | `docker-compose.yml` + Compose de pgVector | Los mismos | No |
| Observabilidad | `infra/observability/compose.yml` | El mismo, en la misma instancia | No |
| Proxy y TLS | Nginx Proxy Manager en `proxy-network` | El mismo, con [nginx-proxy-manager.compose.yml](../infra/aws/ec2/nginx-proxy-manager.compose.yml) | Fichero nuevo de referencia |
| Secretos | `/etc/fitcoachia/prod/.env.prod` (root) e `infra/*/.env` | Igual | No |
| Despliegue | `deploy.yml`: SSH + `sudo make prod-up` | Igual; solo cambian los secretos `SERVER_*` de GitHub | No |
| Imágenes | Docker Hub | Docker Hub | No |
| Dominio | DNS actual | Mismos dominios; registros `A` a la Elastic IP | No |
| Backups | — | Snapshots EBS diarios (DLM) + `pg_dump` nocturno a S3 | Script nuevo |
| Huérfanos al desplegar | `prod-up` no los quitaba | `dev-up` y `prod-up` llevan `--remove-orphans` | Arreglo en el `Makefile` |

Se elige **x86_64** (`t3`) y no Graviton (`t4g`) porque las imágenes actuales solo se publican para
`amd64` y porque permite copiar los volúmenes de Postgres tal cual. Pasar a ARM exige builds
multiarquitectura y queda como mejora posterior.

Coste orientativo en `eu-west-1`, bajo demanda: **≈ 77 USD/mes** solo producción con observabilidad
(≈ 54 $ con un Savings Plan de 1 año). Detalle en la [sección 9](#9-coste).

## 2. Diagrama

```
                        Internet
   Telegram ──webhook──┐        ┌── Usuario (Mini App)      Operador ──► grafana.<dominio>
                       ▼        ▼                                              │
         DNS: api.<dominio>, grafana.<dominio>  A  →  Elastic IP ◄─────────────┘
                       │
┌──────────── EC2 t3.large · Ubuntu 24.04 · SG: 80, 443, 22 ─────────────────────────┐
│  proxy-network                                                                      │
│   ├─ nginx-proxy-manager :80 :443 (admin :81 solo en 127.0.0.1)                     │
│   ├─ fitcoach-ia (API + bot + scheduler) :8000                                      │
│   └─ fitcoach-grafana :3000                                                         │
│                                                                                     │
│  fitcoach-prod-internal                                                             │
│   ├─ fitcoach-ia ──► fitcoach-embedder :8100                                        │
│   ├─ fitcoach-ia ──► fitcoach-postgres (PG 16) ◄── Grafana (dashboards de negocio)  │
│   ├─ fitcoach-ia ──► pgvector-prod (PG 18 + pgvector)                               │
│   └─ fitcoach-ia ──OTLP──► fitcoach-otel-collector :4317                            │
│                                                                                     │
│  observability                                                                      │
│   collector ─► Loki / Tempo / Prometheus ◄── Grafana                                │
│   Alloy ─► Loki (logs de fitcoach-ia vía socket de Docker)                          │
│                                                                                     │
│  Volumen raíz gp3 (no se borra al terminar la instancia) · cron 03:30 ─► S3         │
└─────────────────────────────────────────────────────────────────────────────────────┘
        │ salida HTTPS: Telegram, OpenAI/OpenRouter, Sentry, Docker Hub, GitHub
        ▼
GitHub Actions ──SSH (deploy.yml sin cambios)──► sudo make prod-up VERSION=x.y.z
```

## 3. Qué crea la plantilla

| Recurso | Para qué |
|---|---|
| Security group | 443 y 80 desde internet (IPv4 e IPv6); 22 desde `SshIngressCidr` |
| Instancia EC2 | Ubuntu 24.04, `t3.large` por defecto, crédito *unlimited*, IMDSv2 obligatorio, protección contra terminación, disco gp3 cifrado de 60 GB que **no** se borra si se termina la instancia |
| Elastic IP | IP fija para el DNS y para el secreto `SERVER_HOST`; se reasocia sola si la instancia se sustituye |
| Rol de instancia | Session Manager (shell y túneles sin abrir puertos) y escritura en `postgres/` del bucket de backups |
| Bucket S3 | Backups de Postgres, cifrado, sin acceso público, borra los volcados a los `BackupRetentionDays` días. Se conserva si se borra la pila |
| Política DLM | Snapshot diario de la instancia a las 03:00 UTC, conserva `SnapshotRetentionCount` |

El *user data* de la instancia deja la máquina como el servidor actual:

1. Docker Engine (≥ 25, necesario por `start_interval` de los healthchecks), el plugin Compose,
   `make`, `git` y la AWS CLI.
2. Rotación de logs de Docker (`json-file`, 3 × 10 MB por contenedor). Alloy los sigue leyendo por
   la API de Docker.
3. 2 GB de swap.
4. Usuario de despliegue en el grupo `docker`, con la clave pública de GitHub Actions y la regla
   `sudoers` que exige `deploy.yml` ([how-to.md](how-to.md#desplegar-producción)).
5. `/etc/fitcoachia/prod` y `/etc/fitcoachia/dev` propiedad de root con permisos `700`.
6. Las redes `proxy-network`, `fitcoach-prod-internal` y `fitcoach-dev-internal` (el Compose de
   observabilidad exige las dos internas aunque dev no corra aquí).
7. El repositorio en `/opt/fitcoachia` (rama o tag `RepositoryRef`), y una copia de
   `docker-compose.yml` y `Makefile` en el *home* del usuario de despliegue, que es donde
   `deploy.yml` los sobrescribe.
8. El backup nocturno (`/etc/cron.d/fitcoach-backup`) y Nginx Proxy Manager arrancado.

No arranca la app, pgVector ni la observabilidad: necesitan ficheros `.env` con secretos, que no
deben pasar por CloudFormation (quedarían visibles en el *user data*). Su salida queda en
`/var/log/cloud-init-output.log`.

**Cuidado con las actualizaciones de la pila**: cambiar `ImageId` o `SubnetId` **sustituye la
instancia**. El disco antiguo no se borra, pero la nueva arranca vacía. Por eso la AMI va fijada como
parámetro y no se resuelve sola. Cambiar `InstanceType` solo la para y la arranca. Cambiar parámetros
del *user data* no lo vuelve a ejecutar.

## 4. Crear la pila

Región por defecto `eu-west-1` (Irlanda); `eu-south-2` (Madrid) también vale. Los comandos van en
dos versiones, cada una con su etiqueta: **PowerShell (Windows)** y **bash (Linux, macOS, WSL)**;
los que sirven igual en las dos se indican como tales. Todos usan explícitamente el perfil de
la AWS CLI, aquí `fitcoach`: si el perfil se llama de otra forma, `aws configure list-profiles` lo
muestra.

### 4.1 Requisitos en el equipo desde el que se lanza

- **AWS CLI v2** (`aws --version`). La v1 no admite SSO.
- **Plugin de Session Manager** para la AWS CLI, necesario para `aws ssm start-session` (instalador
  oficial de AWS para Windows, macOS o Linux).
- **Perfil SSO** de un usuario de IAM Identity Center con permisos de administrador (la pila crea
  roles de IAM). Nunca el usuario root. Se crea una vez con `aws configure sso`; la sesión caduca a las
  pocas horas y se renueva con `aws sso login`.

Las variables de PowerShell de esta sección (`$AwsProfile`, `$Region`, `$PubKey`, `$Ami`...) son
variables normales de la sesión: no llevan `$env:`, que solo se usa para variables de entorno
([about_Variables](https://learn.microsoft.com/es-es/powershell/module/microsoft.powershell.core/about/about_variables),
[about_Environment_Variables](https://learn.microsoft.com/es-es/powershell/module/microsoft.powershell.core/about/about_environment_variables)).
Funcionan porque PowerShell sustituye su valor en el argumento antes de lanzar `aws`. Duran lo que
dura la ventana, así que los bloques se ejecutan en orden en la misma.

**PowerShell (Windows):**

```powershell
$AwsProfile = "fitcoach"
$Region = "eu-west-1"
aws sso login --profile $AwsProfile
aws sts get-caller-identity --profile $AwsProfile   # debe devolver la cuenta y el rol
```

**bash (Linux, macOS, WSL):**

```bash
AWS_PROFILE_NAME=fitcoach
REGION=eu-west-1
aws sso login --profile "$AWS_PROFILE_NAME"
aws sts get-caller-identity --profile "$AWS_PROFILE_NAME"
```

### 4.2 Clave SSH de despliegue

La instancia se crea con la clave pública que se le pase en `DeploySshPublicKey`, y la escribe en el
`authorized_keys` del usuario de despliegue al arrancar. Es la clave que usará `deploy.yml`: su parte
privada debe acabar en el secreto `SERVER_PKEY` de GitHub. Se genera una pareja nueva, sin contraseña
(GitHub Actions no puede teclearla):

**PowerShell (Windows):**

```powershell
New-Item -ItemType Directory -Force $HOME\.ssh | Out-Null
ssh-keygen -t ed25519 -f $HOME\.ssh\fitcoach-deploy -C github-actions-deploy   # Enter dos veces
$PubKey = (Get-Content $HOME\.ssh\fitcoach-deploy.pub -Raw).Trim()
```

**bash (Linux, macOS, WSL):**

```bash
ssh-keygen -t ed25519 -f ~/.ssh/fitcoach-deploy -C github-actions-deploy -N ''
PUBKEY=$(cat ~/.ssh/fitcoach-deploy.pub)
```

- La clave privada (`fitcoach-deploy`, sin `.pub`) la guarda un administrador del repositorio en
  `SERVER_PKEY` **en el momento de migrar** ([sección 7](#7-migrar-desde-el-servidor-actual), paso 6),
  junto con `SERVER_HOST` y `SERVER_USER`. Hasta entonces `deploy.yml` sigue desplegando en el
  servidor actual con la clave de siempre. Se entrega por un canal seguro, nunca por chat o correo
  sin cifrar.
- Para entrar en la instancia no hace falta esta clave: cada integrante usa Session Manager con su
  propio usuario ([sección 6](#6-acceso-del-equipo)).
- Cambiar `DeploySshPublicKey` en una actualización de la pila no tiene efecto (el *user data* solo
  se ejecuta en el primer arranque): habría que editar el `authorized_keys` desde Session Manager.

### 4.3 AMI, VPC y subred

**PowerShell (Windows):**

```powershell
$Ami = aws ssm get-parameter --profile $AwsProfile --region $Region `
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id `
  --query Parameter.Value --output text
$VpcId = aws ec2 describe-vpcs --profile $AwsProfile --region $Region `
  --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text
aws ec2 describe-subnets --profile $AwsProfile --region $Region `
  --filters "Name=vpc-id,Values=$VpcId" --query "Subnets[].[SubnetId,AvailabilityZone]" --output table
$SubnetId = "subnet-xxxxxxxx"   # una de la tabla anterior
```

**bash (Linux, macOS, WSL):**

```bash
AMI=$(aws ssm get-parameter --profile "$AWS_PROFILE_NAME" --region "$REGION" \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)
VPC_ID=$(aws ec2 describe-vpcs --profile "$AWS_PROFILE_NAME" --region "$REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
aws ec2 describe-subnets --profile "$AWS_PROFILE_NAME" --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" --query 'Subnets[].[SubnetId,AvailabilityZone]' --output table
SUBNET_ID=subnet-xxxxxxxx   # una de la tabla anterior
```

La AMI queda fijada en la pila: así una actualización no sustituye la instancia por sorpresa.

### 4.4 Crear el change set, revisarlo y ejecutarlo

`RepositoryRef` es la rama o el tag que la instancia clona en `/opt/fitcoachia`. Debe contener
`infra/aws/ec2/`: si no, el arranque falla al no encontrar el script de backup. Mientras esta carpeta
no esté en `develop` (el valor por defecto), usar `feat/cloud-architecture`.

`--no-execute-changeset` prepara los cambios sin aplicarlos, para revisarlos antes:

**PowerShell (Windows):**

```powershell
aws cloudformation deploy --profile $AwsProfile --region $Region `
  --stack-name fitcoach-prod `
  --template-file infra/aws/ec2/fitcoach-ec2.cfn.yaml `
  --capabilities CAPABILITY_IAM `
  --no-execute-changeset `
  --parameter-overrides "VpcId=$VpcId" "SubnetId=$SubnetId" "ImageId=$Ami" `
    "DeploySshPublicKey=$PubKey" "RepositoryRef=feat/cloud-architecture"
```

**bash (Linux, macOS, WSL):**

```bash
aws cloudformation deploy --profile "$AWS_PROFILE_NAME" --region "$REGION" \
  --stack-name fitcoach-prod \
  --template-file infra/aws/ec2/fitcoach-ec2.cfn.yaml \
  --capabilities CAPABILITY_IAM \
  --no-execute-changeset \
  --parameter-overrides "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ImageId=$AMI" \
    "DeploySshPublicKey=$PUBKEY" "RepositoryRef=feat/cloud-architecture"
```

El comando termina imprimiendo el ARN del change set. Para revisarlo y ejecutarlo (los mismos
comandos en las dos shells, cada uno en una línea):

**PowerShell y bash (iguales):**

```shell
aws cloudformation describe-change-set --profile fitcoach --region eu-west-1 --change-set-name <arn-del-change-set> --query "Changes[].ResourceChange.[Action,LogicalResourceId,Replacement]" --output table
aws cloudformation execute-change-set --profile fitcoach --region eu-west-1 --change-set-name <arn-del-change-set>
aws cloudformation wait stack-create-complete --profile fitcoach --region eu-west-1 --stack-name fitcoach-prod
```

En una **actualización** de la pila, comprobar antes de ejecutar que `Instance` no aparece con
`Replacement` a `True`: eso sustituiría la máquina. Se usa `stack-update-complete` en lugar de
`stack-create-complete`. También se puede revisar y ejecutar desde la consola de CloudFormation
(pestaña *Change sets*).

### 4.5 Después de crearla

Protección contra borrado y salidas de la pila:

**PowerShell y bash (iguales):**

```shell
aws cloudformation update-termination-protection --profile fitcoach --region eu-west-1 --enable-termination-protection --stack-name fitcoach-prod
aws cloudformation describe-stacks --profile fitcoach --region eu-west-1 --stack-name fitcoach-prod --query "Stacks[0].Outputs" --output table
```

Tras crearse la pila, el *user data* tarda unos minutos más en instalar Docker y clonar el repositorio; su
salida queda en `/var/log/cloud-init-output.log`.

La plantilla se valida con `cfn-lint`, el validador de AWS para CloudFormation. Corre como hook de
pre-commit al cambiar la plantilla; para lanzarlo a mano: `pre-commit run cfn-lint --all-files`, o
`cfn-lint infra/aws/ec2/fitcoach-ec2.cfn.yaml` si está instalado (`uv tool install cfn-lint`).

## 5. Completar la instancia

Una sola vez, por Session Manager (`SessionCommand` en las salidas de la pila, añadiendo
`--profile fitcoach`):

```bash
# Secretos: copiar los ficheros del servidor actual. Son distintos entre sí.
sudo install -m 600 -o root -g root ./app.env.prod /etc/fitcoachia/prod/.env.prod
sudo install -m 600 -o root -g root ./vector-db.env.prod /opt/fitcoachia/infra/vector-db/.env.prod
sudo install -m 600 -o root -g root ./observability.env /opt/fitcoachia/infra/observability/.env

# Si los repositorios de Docker Hub son privados, login como usuario de despliegue
sudo -iu <DEPLOY_USER> docker login
```

Valores a revisar en esos ficheros, que dependen de esta máquina:

- `.env.prod` de la app: `otel_exporter_otlp_endpoint=http://fitcoach-otel-collector:4317`, igual que
  hoy ([observabilidad.md](observabilidad.md)).
- `infra/observability/.env`: `DEPLOYMENT_ENVIRONMENT=prod` y `FITCOACH_POSTGRES_PROD_*` con las
  credenciales del Postgres de producción. `FITCOACH_POSTGRES_DEV_PASSWORD` es obligatoria para el
  Compose; si dev no corre en esta instancia, cualquier valor sirve y el datasource «PostgreSQL Dev»
  quedará en error.

## 6. Acceso del equipo

Cada integrante entra en la instancia **con su propio usuario de AWS a través de Session Manager**,
sin claves SSH compartidas y sin usar el puerto 22 (que queda solo para `deploy.yml`). La plantilla ya
da a la instancia el permiso de Session Manager; no hace falta cambiarla.

- Cada sesión queda registrada a nombre de quien la abre.
- No hay claves de equipo que guardar ni rotar.
- Quitar el acceso a alguien es desactivar su usuario en IAM Identity Center.

No se debe repartir una clave común ni la clave de `deploy.yml` ([sección 4.2](#42-clave-ssh-de-despliegue)):
no se sabría quién hace qué y, si alguien deja el proyecto, habría que cambiarla para todos.

### 6.1 Usuarios en IAM Identity Center (un administrador, una vez)

1. En IAM Identity Center, crear un usuario por integrante (o un grupo `fitcoach` con los cuatro).
2. Asignarles la cuenta de AWS con un *permission set*:
   - `AdministratorAccess` para quien vaya a crear o actualizar la pila.
   - Para quien solo necesita entrar en la máquina, un *permission set* propio (p. ej.
     `FitCoachInstanceAccess`) con esta política en línea, sustituyendo `<cuenta>` e `<instance-id>`
     (este último sale en las salidas de la pila, `InstanceId`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "StartSessionOnFitCoachInstance",
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": [
        "arn:aws:ec2:eu-west-1:<cuenta>:instance/<instance-id>",
        "arn:aws:ssm:eu-west-1::document/AWS-StartSSHSession",
        "arn:aws:ssm:eu-west-1::document/AWS-StartPortForwardingSession",
        "arn:aws:ssm:eu-west-1:<cuenta>:document/SSM-SessionManagerRunShell"
      ]
    },
    {
      "Sid": "ManageOwnSessions",
      "Effect": "Allow",
      "Action": ["ssm:TerminateSession", "ssm:ResumeSession"],
      "Resource": "arn:aws:ssm:*:*:session/*"
    },
    {
      "Sid": "TemporarySshKey",
      "Effect": "Allow",
      "Action": "ec2-instance-connect:SendSSHPublicKey",
      "Resource": "arn:aws:ec2:eu-west-1:<cuenta>:instance/<instance-id>",
      "Condition": { "StringEquals": { "ec2:osuser": "ubuntu" } }
    },
    {
      "Sid": "Discover",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ssm:DescribeInstanceInformation",
        "ssm:DescribeSessions",
        "ssm:GetConnectionStatus"
      ],
      "Resource": "*"
    }
  ]
}
```

### 6.2 Entrar en la instancia (cada integrante)

Requisitos en su equipo, los mismos de la [sección 4.1](#41-requisitos-en-el-equipo-desde-el-que-se-lanza):
AWS CLI v2, el plugin de Session Manager y un perfil SSO propio creado con `aws configure sso`. El
`<instance-id>` está en las salidas de la pila.

**PowerShell (Windows):**

```powershell
$AwsProfile = "fitcoach"            # el nombre de su perfil SSO
$InstanceId = "i-xxxxxxxxxxxxxxxxx"
aws sso login --profile $AwsProfile
aws ssm start-session --profile $AwsProfile --region eu-west-1 --target $InstanceId
```

**bash (Linux, macOS, WSL):**

```bash
AWS_PROFILE_NAME=fitcoach            # el nombre de su perfil SSO
INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
aws sso login --profile "$AWS_PROFILE_NAME"
aws ssm start-session --profile "$AWS_PROFILE_NAME" --region eu-west-1 --target "$INSTANCE_ID"
```

Se entra como `ssm-user`, que tiene `sudo`. Para trabajar con más comodidad: `sudo -iu ubuntu` o
`bash -l`. Los túneles a paneles internos (Nginx Proxy Manager, sección 7) usan la misma sesión.

### 6.3 SSH de verdad, por encima de Session Manager (opcional)

Para `scp`, `rsync` o VS Code Remote-SSH hace falta SSH. Se puede usar sin abrir el puerto 22 a las
personas y sin claves permanentes en el servidor: cada integrante tiene **su propia clave**, la envía
a la instancia con EC2 Instance Connect (vale 60 segundos, el tiempo de abrir la conexión) y la
conexión viaja por Session Manager. Ubuntu 24.04 ya trae EC2 Instance Connect instalado.

1. **Una vez**, generar la clave personal (con contraseña: es solo suya) y añadir el alias a
   `~/.ssh/config`.

   **PowerShell (Windows):**

   ```powershell
   New-Item -ItemType Directory -Force $HOME\.ssh | Out-Null
   ssh-keygen -t ed25519 -f $HOME\.ssh\fitcoach-personal -C "<su-nombre>"
   ```

   Añadir a `$HOME\.ssh\config` (sustituyendo el perfil y el `instance-id`):

   ```text
   Host fitcoach-ec2
       HostName i-xxxxxxxxxxxxxxxxx
       User ubuntu
       IdentityFile ~/.ssh/fitcoach-personal
       ProxyCommand C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe "aws ssm start-session --profile fitcoach --region eu-west-1 --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p"
   ```

   **bash (Linux, macOS, WSL):**

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/fitcoach-personal -C "<su-nombre>"
   ```

   Añadir a `~/.ssh/config`:

   ```text
   Host fitcoach-ec2
       HostName i-xxxxxxxxxxxxxxxxx
       User ubuntu
       IdentityFile ~/.ssh/fitcoach-personal
       ProxyCommand sh -c "aws ssm start-session --profile fitcoach --region eu-west-1 --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
   ```

2. **Cada vez**, enviar la clave pública y conectar en menos de 60 segundos.

   **PowerShell (Windows):**

   ```powershell
   aws ec2-instance-connect send-ssh-public-key --profile $AwsProfile --region eu-west-1 --instance-id $InstanceId --instance-os-user ubuntu --ssh-public-key "file://$HOME/.ssh/fitcoach-personal.pub"
   ssh fitcoach-ec2
   ```

   **bash (Linux, macOS, WSL):**

   ```bash
   aws ec2-instance-connect send-ssh-public-key --profile "$AWS_PROFILE_NAME" --region eu-west-1 --instance-id "$INSTANCE_ID" --instance-os-user ubuntu --ssh-public-key "file://$HOME/.ssh/fitcoach-personal.pub"
   ssh fitcoach-ec2
   ```

   La clave solo hace falta para abrir la conexión: una sesión ya abierta sigue viva aunque pasen los
   60 segundos. VS Code Remote-SSH usa el alias `fitcoach-ec2`; si se reconecta, hay que volver a
   enviar la clave.

## 7. Migrar desde el servidor actual

El orden importa: **nunca puede haber dos producciones vivas con el mismo bot**, porque las dos
registrarían el webhook y sus schedulers enviarían avisos y encuestas desde bases distintas.

1. **Días antes**: bajar a 60 s el TTL de los registros DNS de la API y de Grafana.
2. **Proxy Hosts** en Nginx Proxy Manager (ya arrancado por la plantilla). Admin por túnel:

   **PowerShell y bash (iguales):**

   ```shell
   aws ssm start-session --profile fitcoach --region eu-west-1 --target <instance-id> --document-name AWS-StartPortForwardingSession --parameters "portNumber=81,localPortNumber=8081"
   ```

   Con el túnel abierto, el panel queda en `http://localhost:8081`. En PowerShell, las comillas de
   `--parameters` son obligatorias: sin ellas la coma parte el argumento en dos.

   - API, igual que hoy ([telegram-miniapp.md](telegram-miniapp.md#nginx-proxy-manager)): destino
     `fitcoach-ia-prod`, puerto `8000`, `http`, Force SSL.
   - Grafana, igual que hoy ([observabilidad.md](observabilidad.md)): destino `fitcoach-grafana`,
     puerto `3000`, Force SSL y, si se quiere, una *Access List*.

   Para tener los certificados **antes** del cambio de DNS, pedirlos con reto DNS-01 desde NPM (si
   el proveedor de DNS está soportado); si no, pedirlos justo después del paso 5, con unos minutos de
   errores TLS que Telegram reintenta.
3. **Parar producción en el servidor actual** (Telegram guarda los updates pendientes hasta 24 h):

   ```bash
   sudo make prod-down
   docker compose -f infra/vector-db/docker-compose.vector-db.prod.yml down   # desde infra/vector-db
   ```

4. **Copiar los volúmenes de Postgres.** Misma imagen, misma versión mayor y misma arquitectura
   (x86_64), así que se copian los ficheros tal cual, sin `pg_dump`/`pg_restore` y sin tocar el DDL
   de pgVector:

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

   Los volúmenes de observabilidad (`fitcoach-observability-*`) son opcionales: los dashboards y
   datasources se aprovisionan desde el repositorio, así que solo se pierde el histórico de métricas,
   logs y trazas y lo que se haya creado a mano en Grafana. Si se quiere conservar, se copian igual.
5. **Arrancar en la EC2 y mover el DNS**:

   ```bash
   cd /opt/fitcoachia/infra/observability && sudo docker compose up -d
   cd /opt/fitcoachia/infra/vector-db && sudo docker compose -f docker-compose.vector-db.prod.yml up -d --build
   cd /home/<DEPLOY_USER> && sudo make prod-up VERSION=<versión en servicio>
   ```

   Cambiar los registros `A` a la Elastic IP. Al arrancar, la API vuelve a registrar el webhook con
   `bot_telegram_webhook_base_url`, que no cambia.
6. **Actualizar los secretos de GitHub** (lo hace un administrador del repositorio): `SERVER_PKEY`
   con la clave privada de la [sección 4.2](#42-clave-ssh-de-despliegue), `SERVER_HOST` (Elastic IP
   o nombre DNS) y `SERVER_USER` (`DeployUser`, por defecto `fitcoach`). `DOCKER_IMAGE_NAME` y
   `ENV_FILE_PATH` siguen igual. A partir de aquí
   los despliegues van por `deploy.yml` como hoy.
7. **Comprobar**: `docker ps` (todo `healthy`), `getWebhookInfo` del bot sin errores, un mensaje de
   prueba, la Mini App, que en Grafana aparecen logs y trazas de `prod`, y el primer backup en S3 al
   día siguiente (`/var/log/fitcoach-backup.log`).
8. **Rollback** mientras no se borre nada en el servidor antiguo: devolver el DNS, `make prod-up`
   allí. Los datos escritos en la EC2 entretanto se perderían, así que conviene decidir pronto.

## 8. Backups

[`infra/aws/ec2/backup-postgres.sh`](../infra/aws/ec2/backup-postgres.sh) hace un `pg_dump` en
formato custom de cada base (relacional y vectorial) **dentro de su contenedor**, con las
credenciales que ya tiene el propio contenedor, y lo sube a `s3://<bucket>/postgres/<fecha>/` con el
rol de la instancia. La plantilla lo instala en `/usr/local/bin/fitcoach-backup` y lo programa a las
03:30 UTC.

Restaurar una base:

```bash
aws s3 cp s3://<bucket>/postgres/<fecha>/fitcoach-postgres.dump .
docker exec -i fitcoach-postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < fitcoach-postgres.dump
```

Los snapshots diarios de DLM recuperan la máquina entera, incluido el histórico de observabilidad.

## 9. Coste

`eu-west-1`, bajo demanda, USD/mes, precios de lista de referencia (confirmar en el
[AWS Pricing Calculator](https://calculator.aws/)). No incluye el LLM.

| Concepto | Prod + observabilidad (`t3.large`, 8 GB) | Prod + dev + observabilidad (`t3.xlarge`, 16 GB) |
|---|---|---|
| Instancia | 66,60 | 133,20 |
| EBS gp3 (60 / 80 GB) | 5,30 | 7,05 |
| Elastic IP | 3,65 | 3,65 |
| Snapshots + S3 de backups | ~1,50 | ~2 |
| Transferencia (< 100 GB/mes) | 0 | 0 |
| **Total** | **≈ 77** | **≈ 146** |

- Con un **Savings Plan de 1 año** sin pago inicial, la instancia baja ~35 %: ≈ 54 $ y ≈ 100 $.
- Memoria estimada con `t3.large`: producción 3–4,3 GB (embedder 1,5–2 GB, API, dos Postgres) más
  1,2–1,6 GB del stack de observabilidad y ~0,4 GB del sistema: **≈ 4,6–6,3 GB de 8**, más 2 GB de
  swap. Cabe, pero sin mucho margen. Medir con `docker stats --no-stream` en el servidor actual y, si
  pasa de 6 GB, usar `t3.xlarge`.
- Disco: Prometheus guarda 30 días, Loki 14 y Tempo 7. Con el tráfico actual son pocos GB.
- El stack no incluye métricas del host (CPU, RAM, disco de la instancia). Si se quieren en
  Grafana, el paso natural es añadir `node-exporter` al Compose de observabilidad.

## 10. Qué no cambia y por qué

Para mantener los cambios al mínimo, esta variante deja a propósito como está:

- **Migraciones en el `ENTRYPOINT`** (`src/Dockerfile`): con una sola réplica de la API no hay
  carreras.
- **Dos Postgres en contenedor** y el nombre `fitcoach` en ambas: siguen en contenedores separados.
- **Volcado `pg_dumpall` de PG 18** en la imagen de pgVector: se migra el volumen, así que no se
  vuelve a cargar.
- **Docker Hub** como registro y **el DNS** donde esté hoy: Route 53 y ECR no aportan nada aquí.
- **Observabilidad**: el mismo Compose y la misma configuración; ningún servicio de AWS la sustituye.
- **`proxy-network` y las redes internas**: idénticas.

## 11. Puntos a confirmar antes de migrar

1. **Imagen del embedder.** `docker-compose.yml` usa `fitcoachia/embedder:${VERSION}`, pero ningún
   workflow construye ni publica esa imagen. En una máquina nueva, `make prod-up` falla al no poder
   descargarla salvo que se haya publicado a mano para esa versión.
2. **Entorno de desarrollo**: dejarlo en el servidor actual (por defecto en este documento) o
   moverlo a la EC2 con `t3.xlarge`.
3. **Región**: `eu-west-1` (por defecto) o `eu-south-2`.
