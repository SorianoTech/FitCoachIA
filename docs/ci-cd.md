# Flujo CI/CD

Este documento describe el pipeline de integración, entrega y despliegue continuo de FitCoachIA:
qué dispara cada pieza, qué objetivo cumple dentro del ciclo y cómo fluye una ejecución de
principio a fin.

> Para cómo encajan el despliegue, el `Makefile` y los ficheros de entorno de cada entorno, ver
> [entornos-y-despliegue.md](entornos-y-despliegue.md). Para los comandos, [Makefile.md](Makefile.md).

## 1. Alcance

Cubre los workflows de GitHub Actions y las composite actions que forman el pipeline, más el hook
de pre-commit que actúa como primera barrera antes de llegar a CI. **No** cubre los workflows
`validate-develop-merge.yml` y `validate-main-merge.yml`: no compilan, testean ni despliegan nada,
solo validan el origen de un PR, por lo que se documentan aparte en el [Anexo A](#anexo-a--políticas-de-integración-de-ramas).

| Pieza | Ruta | Tipo |
|---|---|---|
| Pre-commit | [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) | Hook local |
| Test and build project | [`.github/workflows/build.yml`](../.github/workflows/build.yml) | Workflow |
| Generate and deploy release | [`.github/workflows/release.yml`](../.github/workflows/release.yml) | Workflow |
| Deploy release | [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | Workflow (reusable) |
| Python setup custom | [`.github/actions/python-setup/action.yml`](../.github/actions/python-setup/action.yml) | Composite action |
| Quality assurance | [`.github/actions/quality-check/action.yml`](../.github/actions/quality-check/action.yml) | Composite action |

La frontera entre **Delivery** y **Deployment** está en el `workflow_dispatch` de `release.yml`:
build, escaneo y publicación del artefacto son automáticos, pero **liberar una versión es una
decisión humana** (quién dispara el workflow y con qué versión). Una vez lanzada, el despliegue en
el servidor es 100 % automático y encadenado.

## 2. El pipeline por fases

Cada fase de la metodología DevOps se corresponde con una pieza concreta del repo. Por cada
herramienta se indica su **objetivo** dentro del ciclo, no el comando exacto que ejecuta.

### 2.1 Pre-CI (shift-left local) — `.pre-commit-config.yaml`

**Dispara**: `git commit`. Primera barrera, antes de que el código salga del equipo del
desarrollador; su objetivo es abaratar el coste de un error (detectarlo en segundos en local, no
en minutos en CI).

| Herramienta | Objetivo |
|---|---|
| Hooks básicos (whitespace, EOF, YAML, merge conflicts, ficheros grandes, `no-commit-to-branch`) | Higiene mínima del repo; bloquea de raíz el commit directo a `main`/`develop`. |
| `gitleaks` | Evita que un secreto llegue a existir en el historial de Git. |
| `ruff` + `ruff-format` | Estilo y errores estáticos detectables sin ejecutar el código; feedback inmediato. |
| `bandit` | Primera pasada de SAST sobre `src/`: patrones inseguros conocidos (`eval`, `subprocess`, etc.). |
| `cfn-lint` | Valida la plantilla de CloudFormation (`infra/aws/ec2/*.cfn.yaml`) antes de crear o actualizar la pila; `check-yaml` la excluye porque no entiende las etiquetas `!Ref`/`!Sub`. |

### 2.2 Continuous Integration — `build.yml`

**Dispara**: `push` y `pull_request` sobre `feature/**`, `feat/**`, `fix/**`, `bugfix/**` (se
ignoran cambios que solo tocan documentación). Tres jobs encadenados por `needs`:
`quality-security-gate` → `semgrep-analysis` → `test-gate`.

> ⚠️ El filtro de `pull_request` se evalúa sobre la rama **base**: un PR `feature/x → develop` no
> vuelve a disparar este workflow, porque esos commits ya se validaron en el `push` a la rama de
> trabajo. Ver [Anexo B](#anexo-b--notas-de-estado).

**Job `quality-security-gate`** — repite y endurece lo que el pre-commit ya comprobó en local
(ahora bloqueante para todo el equipo, no solo para quien hizo el commit), y añade auditoría de
dependencias:

| Herramienta | Objetivo |
|---|---|
| `pip-audit` (antes de instalar) | Corta el pipeline si una dependencia a instalar tiene una vulnerabilidad `HIGH`/`CRITICAL`, antes de traer código potencialmente vulnerable al runner. |
| `ruff` | Lint bloqueante para todo el equipo. |
| `mypy` | Seguridad de tipos estática; detecta errores que los tests no siempre cubren. |
| `gitleaks` | Segunda barrera anti-secretos, por si el hook local se saltó (`--no-verify`). |
| `pip-audit` (tras instalar) | Segunda pasada, ya sobre el entorno realmente instalado. |
| `bandit` | SAST bloqueante sobre `src/fitcoach/`. |

**Job `semgrep-analysis`** — SAST complementario a `bandit`, con reglas más amplias
(`p/python` + `p/owasp-top-ten`) y capacidad de detectar patrones entre archivos. Analiza solo el
diff en PRs, no el repo completo. **No bloquea el merge** (`continue-on-error: true`): su ratio de
falsos positivos es mayor que el de `bandit`, así que su valor está en la trazabilidad continua de
hallazgos — sube el resultado en formato SARIF a la pestaña **Security** de GitHub — no en cortar
el flujo de trabajo del equipo.

### 2.3 Continuous Testing — `build.yml` (job `test-gate`)

Valida comportamiento funcional real (unitarios + integración) contra el mismo stack que se usaría
en local (app + Postgres vía Docker), para que el resultado en CI nunca diverja del de desarrollo.
Esa equivalencia no es una coincidencia: el job ejecuta **`make tests`**, el mismo target que se
usa en local. Gate: cobertura mínima del 80 % como proxy de calidad.

### 2.4 Continuous Delivery — `release.yml`

**Dispara**: `workflow_dispatch` manual con input `version` (`X.Y.Z`) — publicar una versión es una
decisión humana explícita. **Guardia**: solo se ejecuta si la rama es `develop` o `release/**`.

Objetivo general: convertir un commit en un release versionado, escaneado y trazable. No se publica
ninguna imagen en un registro: la imagen se construye en el servidor al desplegar. El orden es
deliberado — **se construye y escanea la imagen antes de crear el tag/release**:

| Paso | Objetivo |
|---|---|
| Validar formato semver + que el tag de la versión no exista ya en el repositorio | Evita releases ambiguos o sobrescribir un tag ya publicado. |
| Build de la imagen sin publicarla (`push: false`) | Permite escanearla antes de crear el release. |
| **Trivy** (escaneo de la imagen) | Equivalente a Semgrep pero sobre el artefacto construido (paquetes de SO + librerías del contenedor), no sobre el código fuente. Informativo, no bloquea el release; sube SARIF a la misma pestaña **Security** de GitHub que Semgrep, como un hallazgo distinto. |
| **GitHub Release** (tag + notas autogeneradas) | El artefacto final y trazable que queda publicado en GitHub (pestaña *Releases*, no *Security*): la versión pasa a existir oficialmente aquí. |

> Semgrep y Trivy son dos escáneres distintos en dos momentos distintos del ciclo — código fuente
> en CI, imagen construida en el release — pero ambos convergen en la misma pestaña Security de
> GitHub. El único fichero que se publica fuera de esa pestaña es la propia **GitHub Release**.

### 2.5 Continuous Deployment — `deploy.yml`

**Dispara**: automáticamente al terminar `Release`, o de forma independiente vía
`workflow_dispatch` para redesplegar una versión ya publicada. Los datos de conexión SSH viajan
como `secrets` (no `inputs`) para que GitHub los enmascare en los logs.

Patrón: **build en el servidor y verificación de salud**. El workflow hace checkout del tag de la
versión, copia el repositorio por rsync a `~/fitcoachia` en el servidor, ejecuta `sudo -n make up`
(construye la imagen y levanta el stack) y espera a que Docker marque `fitcoach-ia` como `healthy`
(`healthcheck` de `docker-compose.yml`, sondeado hasta 10 intentos). Si no lo consigue, el workflow
falla y vuelca los últimos logs; **no hay rollback automático**: para volver atrás se relanza
`deploy.yml` con la versión anterior. Esto implica una ventana breve sin servicio en cada despliegue:
el proxy devuelve 502 y Telegram reintenta los updates, así que no se pierden mensajes.

**Prerrequisitos que CI nunca provee**, deben existir ya en el servidor: el fichero
`/etc/fitcoachia/dev/.env.dev` con permisos restringidos (no legible por el usuario de
despliegue; si no existe se usa `.env` del repositorio, que el rsync no copia), una regla `sudoers`
NOPASSWD para ese usuario (ver [`docs/how-to.md`](how-to.md)) y la capacidad de crear las redes Docker
externas `fitcoach-internal` y `proxy-network`. `make up` las crea de forma idempotente si todavía no
existen.

### 2.6 Continuous Monitoring

No hay un job dedicado; el monitoreo continuo se apoya en dos señales que ya generan las fases
anteriores:

- **`healthcheck` del contenedor** sobre `/health` — decide el resultado del despliegue (y su
  rollback), y después sigue sondeando cada 5 min como señal de salud continua en producción.
- **Pestaña Security de GitHub** — acumula los SARIF de Semgrep (CI, código fuente) y Trivy
  (release, imagen construida) como registro continuo de hallazgos, independiente de si bloquearon
  o no el pipeline que los generó.

## 3. Diagramas

### 3.1 Flujo global

```mermaid
flowchart TD
    subgraph LOCAL["Pre-CI (local)"]
        A[git commit] --> A1[pre-commit hooks]
    end

    A1 --> B[push a feature/** · feat/** · fix/** · bugfix/**]

    subgraph CI["Continuous Integration — build.yml"]
        B --> C[quality-security-gate]
        C -->|ok| D[semgrep-analysis]
        C -->|falla| X1[❌ pipeline detenido]
        D --> D1[[SARIF Semgrep]]
    end

    subgraph CT["Continuous Testing — build.yml"]
        D --> E[test-gate: cobertura >= 80%]
        E -->|falla| X2[❌ pipeline detenido]
    end

    E -->|ok| F[PR a develop] --> G[Merge en develop]

    subgraph CD1["Continuous Delivery — release.yml"]
        G -.->|workflow_dispatch manual\ninput: version X.Y.Z| H[Release: checks + build imagen]
        H -->|falla algún check| X3[❌ release abortado]
        H --> H1[Trivy scan]
        H1 --> H2[[SARIF Trivy]]
        H1 --> H3[GitHub Release\ntag + notas]
    end

    subgraph MON["Continuous Monitoring"]
        SEC[(GitHub Security tab)]
        D1 --> SEC
        H2 --> SEC
    end

    subgraph CD2["Continuous Deployment — deploy.yml"]
        H3 -->|ok| I[checkout del tag + ssh-deploy: rsync\ndel repositorio a ~/fitcoachia]
        I --> K[sudo -n make up\nconstruye y levanta]
        K --> L{Docker lo marca healthy\n·Continuous Monitoring·}
        L -->|sí| M[✅ versión operativa]
        L -->|no| N[❌ workflow en rojo\nrollback = relanzar con la versión anterior]
    end
```

### 3.2 Secuencia de despliegue

```mermaid
sequenceDiagram
    participant R as Runner (GitHub Actions)
    participant S as Servidor (SSH)

    Note over R,S: Continuous Deployment — deploy.yml
    R->>R: checkout del tag de la versión
    R->>S: rsync del repositorio a ~/fitcoachia
    R->>S: SCRIPT_BEFORE (sesión SSH 1)
    activate S
    S->>S: Verificar sudo -n
    deactivate S
    R->>S: SCRIPT_AFTER (sesión SSH 2)
    activate S
    S->>S: sudo -n make up
    Note right of S: Continuous Monitoring
    S->>S: Esperar 5s + 10 intentos x 5s\ndocker inspect .State.Health.Status
    alt healthy
        S-->>R: exit 0
    else unhealthy o se agotan los intentos
        S->>S: Volcar últimas 50 líneas de log
        S-->>R: exit 1 (workflow en rojo)
    end
    deactivate S
```

> `SCRIPT_BEFORE` y `SCRIPT_AFTER` son **sesiones SSH distintas**: las variables no cruzan entre
> ellas. Detalle completo del
> despliegue y de los targets del `Makefile` en
> [entornos-y-despliegue.md](entornos-y-despliegue.md).

## 4. Gates, secretos y artefactos

### Gates

| Gate | Dónde | Bloquea o informa |
|---|---|---|
| `pip-audit` (OSV, HIGH/CRITICAL) | `python-setup`, antes de instalar | Bloquea |
| `ruff` / `mypy` / `gitleaks` / `pip-audit` / `bandit` | `quality-check` | Bloquea |
| Semgrep (`p/python`, `p/owasp-top-ten`) | `build.yml` → `semgrep-analysis` | Informa (SARIF) |
| Cobertura de tests ≥ 80 % | `build.yml` → `test-gate` | Bloquea |
| Formato semver de la versión | `release.yml`, `deploy.yml` | Bloquea |
| Versión no debe existir ya como tag | `release.yml` | Bloquea |
| Trivy (imagen, HIGH/CRITICAL) | `release.yml` | Informa (SARIF) |
| Origen de release: `develop` o `release/*` | `release.yml` (`if:`) | Bloquea |
| Estado `healthy` del contenedor tras el despliegue | `deploy.yml` | Bloquea (workflow en rojo; sin rollback automático) |

### Artefactos publicados

| Artefacto | Generado por | Dónde se ve |
|---|---|---|
| SARIF Semgrep | `build.yml` → `semgrep-analysis` | Pestaña *Security* (code scanning) |
| SARIF Trivy | `release.yml` | Pestaña *Security* (code scanning) |
| GitHub Release (tag + notas) | `release.yml` | Pestaña *Releases* |

### Secretos

| Secreto | Usado en |
|---|---|
| `SERVER_HOST`, `SERVER_USER`, `SERVER_PKEY` | `deploy.yml` (conexión SSH al servidor) |

Ningún workflow expone valores de estos secretos en logs; `deploy.yml` los declara como `secrets`
del `workflow_call` precisamente para garantizar el enmascarado.

---

## Anexo A — Políticas de integración de ramas

> Esta sección queda fuera del ciclo CI/CD descrito arriba: estos workflows no compilan, no
> testean ni despliegan nada. Su único propósito es validar **desde qué rama** se puede abrir un PR
> contra `develop` o `main`, como política de integración (equivalente a una regla de branch
> protection).

- **[`validate-develop-merge.yml`](../.github/workflows/validate-develop-merge.yml)** — en cada PR
  contra `develop`, comprueba que la rama de origen (`head_ref`) empiece por `feature/` o `fix/`;
  si no, falla el check y el PR queda bloqueado.
- **[`validate-main-merge.yml`](../.github/workflows/validate-main-merge.yml)** — en cada PR contra
  `main`, exige que la rama de origen sea exactamente `develop`.

Ambas se apoyan en el hook `no-commit-to-branch` de pre-commit (`main`, `develop`), que impide de
raíz el commit directo a esas ramas en local.

```mermaid
flowchart LR
    subgraph POLICY["Política de integración de ramas (fuera del ciclo CI/CD)"]
        FEAT["feature/** · fix/**"] -->|PR validado por\nvalidate-develop-merge.yml| DEV[develop]
        DEV -->|PR validado por\nvalidate-main-merge.yml| MAIN[main]
    end
    DEV -.->|workflow_dispatch\nrelease.yml| REL["Release + Deploy"]
```

## Anexo B — Notas de estado

Observaciones sobre el estado actual del pipeline que conviene tener presentes al interpretar una
ejecución o al modificar los workflows:

| Observación | Detalle |
|---|---|
| PR a `develop` no re-ejecuta `build.yml` | El filtro `pull_request.branches` evalúa la rama **base**, no la de origen; la validación de esos commits ya ocurrió en el `push` a la rama de trabajo. |
| `bugfix/**` se valida pero no se puede fusionar | `build.yml` dispara sobre `bugfix/**`, pero `validate-develop-merge.yml` solo admite `feature/`, `feat/` y `fix/`: un PR desde `bugfix/**` a `develop` queda bloqueado pese a haber pasado CI. |
| Versión del proyecto desincronizada | `pyproject.toml` declara `0.1.0` mientras los tags Git ya están en `0.4.2`; no hay bump automático de versión. |
| `README.md` desactualizado | La sección `## CI/CD` describe workflows que ya no existen (`validate-merge-source.yml`) y afirma que `release.yml` se dispara con push a `main`, cuando en realidad es manual (`workflow_dispatch`) desde `develop`/`release/*`. |
