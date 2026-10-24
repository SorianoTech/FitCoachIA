# Diagrama: despliegue AWS en una única EC2

Fichero editable: [`despliegue-aws-ec2.drawio`](despliegue-aws-ec2.drawio) (abrir con draw.io).
Descripción completa del despliegue en [despliegue-aws-ec2.md](despliegue-aws-ec2.md).

## Flujo

1. Telegram (webhook), los usuarios de la Mini App y el operador llegan por DNS a la **Elastic IP**.
2. La Elastic IP entra por los puertos 80/443 en **Nginx Proxy Manager** (TLS), dentro de la EC2.
3. NPM enruta a `fitcoach-ia` (API + bot + scheduler) y a Grafana, ambos en `proxy-network`.
4. `fitcoach-ia` usa, en `fitcoach-internal`, el embedder, PostgreSQL 16, pgvector y envía OTLP
   al OTel Collector.
5. Collector y Alloy (logs por el socket de Docker) alimentan Loki/Tempo/Prometheus; Grafana los lee
   y también consulta PostgreSQL para los dashboards de negocio.
6. GitHub Actions despliega por SSH (22) con `sudo -n make up`.
7. Cada noche (03:30) un cron hace `pg_dump` a S3; DLM crea un snapshot diario del volumen EBS (03:00 UTC).
8. Salida HTTPS hacia LLM, Telegram, Sentry y GitHub. El equipo accede por Session Manager.

## Servicios

| Servicio | Función |
|---|---|
| EC2 `t3.large` | Ejecuta todos los contenedores (Compose) |
| Elastic IP | IP fija para DNS y `SERVER_HOST` |
| S3 | Backups de Postgres con retención |
| EBS gp3 + DLM | Disco cifrado de 60 GB con snapshots diarios |
| Systems Manager | Shell y túneles sin abrir puertos |

## Decisiones de diseño

- Una sola instancia reproduce el servidor actual sin cambios en Compose, `Makefile` ni `deploy.yml`.
- Observabilidad propia (no CloudWatch/X-Ray) dentro de la misma máquina.
- Secretos en `/etc/fitcoachia/<entorno>/.env.*`, fuera de CloudFormation.
- Solo se exponen 80/443 a internet; el 22 se limita a `SshIngressCidr`.

Nota: el acceso del operador a Grafana pasa por NPM (`grafana.fitcoach...`); no se dibuja esa arista
para evitar cruces.
