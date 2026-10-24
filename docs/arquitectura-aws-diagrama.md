# Diagrama de arquitectura AWS de FitCoachIA

Diagrama editable: [arquitectura-aws-diagrama.drawio](./arquitectura-aws-diagrama.drawio).
La arquitectura y sus decisiones están descritas en [arquitectura-aws.md](./arquitectura-aws.md).

## Flujo principal

1. Telegram y la Mini App acceden por HTTPS; Route 53 resuelve el dominio y AWS WAF filtra las solicitudes.
2. El Application Load Balancer distribuye las solicitudes entre tareas de FitCoachIA en ECS Fargate.
3. La API consulta PostgreSQL Multi-AZ y el servicio privado de embeddings para recuperar ejercicios con pgVector.
4. La API sale por NAT Gateway hacia la API de Telegram y el proveedor LLM OpenAI-compatible.
5. GitHub Actions se autentica mediante OIDC, publica imágenes versionadas en ECR y despliega la aplicación.
6. Los backups de datos y la replicación de imágenes permiten activar la región secundaria en modo pilot light.

## Servicios representados

| Servicio | Función |
|---|---|
| Route 53, AWS WAF y Application Load Balancer | DNS, filtrado web y entrada HTTPS |
| ECS Fargate | API de FitCoachIA y servicio de embeddings |
| Amazon RDS for PostgreSQL Multi-AZ | Base de conversación y catálogo pgVector con roles separados |
| NAT Gateway | Salida controlada hacia Telegram y el proveedor LLM |
| Secrets Manager y KMS | Protección y cifrado de secretos y datos |
| CloudWatch | Centralización de logs y alarmas |
| ECR y GitHub Actions OIDC | Publicación de imágenes y despliegues |
| Región secundaria | Recuperación regional pilot light |

## Decisiones clave

- Las tareas de aplicación corren en subredes privadas y RDS no tiene acceso público.
- El diseño de producción reparte capacidad entre varias AZ; la región secundaria reduce el coste frente a un warm standby.
- Conversación y catálogo pueden compartir inicialmente la instancia RDS Multi-AZ, pero mantienen bases de datos y permisos separados. El aislamiento físico puede añadirse si las métricas lo requieren.
- Los objetivos ilustrativos de RPO (15 minutos) y RTO (4 horas) deben validarse mediante pruebas reales.
- El diagrama es una propuesta; no representa infraestructura desplegada ni una estimación de coste.
