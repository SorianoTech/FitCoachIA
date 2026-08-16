# pyproject.toml — Guía de lectura

Este fichero cumple dos roles distintos que conviven en el mismo archivo:

1. **Definición del paquete Python** (`[build-system]`, `[project]`, `[dependency-groups]`, `[tool.hatch.*]`) — qué es `fitcoach`, qué necesita para ejecutarse y cómo se construye/instala con [uv](https://docs.astral.sh/uv/).
2. **Configuración de herramientas** (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`) — cómo se analiza y testea el código.

---

## `[build-system]`

| Clave | Qué hace |
|-------|----------|
| `requires = ["hatchling"]` | Declara qué backend de build hay que instalar para poder construir el paquete (wheel/sdist) |
| `build-backend = "hatchling.build"` | El backend concreto que ejecutará la construcción — [Hatchling](https://hatch.pypa.io/latest/) |

> **¿Por qué Hatchling y no setuptools?**
> Hatchling autodetecta el layout `src/<nombre-paquete>/` sin configuración extra: como `name = "fitcoach"` en `[project]` coincide con el directorio `src/fitcoach/`, encuentra el paquete solo. `[tool.hatch.build.targets.wheel]` más abajo lo hace explícito por si la estructura cambia en el futuro (por ejemplo, si se añaden varios paquetes).

> **¿Es obligatorio este bloque?**
> Antes de esta guía, `pyproject.toml` no tenía `[build-system]` ni `[project]` — solo configuración de herramientas (ruff, mypy...). Eso significaba que `fitcoach` no era un "proyecto" instalable desde el punto de vista de `uv`/`pip`, y que herramientas como `uv init` en subcarpetas fallaban al intentar detectar un workspace padre (no encontraban una tabla `[project]` válida). Añadir estas dos tablas convierte a `fitcoach` en un paquete real.

---

## `[project]`

| Clave | Qué hace |
|-------|----------|
| `name = "fitcoach"` | Nombre del paquete instalable. Debe coincidir con `src/fitcoach/` para que Hatchling lo localice sin configuración extra |
| `version = "0.1.0"` | Versión estática del paquete. Si más adelante se quiere derivar automáticamente de un tag de git, se sustituye por `hatch-vcs` |
| `description` | Resumen corto, aparece en metadatos del paquete (`pip show`, PyPI si se publicara) |
| `readme = "README.md"` | Fichero que se usa como descripción larga del paquete |
| `requires-python = ">=3.11"` | Versión mínima de Python soportada. Alineada con `python:3.11-slim` en `src/Dockerfile` — si un día se sube la imagen base, este valor (y `target-version`/`python_version` de ruff/mypy) debe subir también |
| `dependencies` | Dependencias **directas** de runtime: solo lo que el código de `src/fitcoach` importa explícitamente |

> **¿Por qué no aparecen `starlette`, `anyio`, etc.?**
> Son dependencias **transitivas** (las arrastran `fastapi` y otras). `uv` las resuelve automáticamente al compilar los `requirements`; listarlas a mano en `dependencies` sería redundante y se desincronizaría con el tiempo.
>
> `httpx` sí aparece, y no es una excepción arbitraria: `service/llm/llm_caller.py` lo **importa directamente**. Llegaba transitivo por `fastapi[standard]`, pero depender de un transitivo que tu código importa es frágil — el día que `fastapi` deje de arrastrarlo, la app rompe sin que ningún fichero de dependencias haya cambiado. La regla es: si el código lo importa, se declara.

> **¿Por qué `fastapi[standard]` y no `fastapi` a secas?**
> El extra `standard` incluye `uvicorn`, `fastapi-cli`, `python-multipart`, `email-validator`, etc. — todo lo que `src/Dockerfile` necesita para poder ejecutar `ENTRYPOINT ["fastapi", "run", "fitcoach/main.py"]`. Sin el extra, ese comando no existiría en el entorno.

> **¿Por qué versiones con `>=` y no fijadas como en los `requirements.txt`?**
> `pyproject.toml` declara **intención**: qué necesita el proyecto, con una cota mínima. Los `requirements.txt` son **resultado**: el árbol completo (directo + transitivo) con versiones exactas, generados desde aquí. Esa es la separación clásica entre manifiesto y lockfile. Como `.gitignore` excluye `*.lock`, los ficheros compilados hacen de lockfile versionado del proyecto.

---

## `[dependency-groups]`

| Clave | Qué hace |
|-------|----------|
| `dev = [...]` | Dependencias para **desarrollar** en local (tests, linting, hooks) — nunca se instalan en la imagen de producción |
| `ci = [...]` | Herramientas que solo usa el **pipeline** (bandit, pip-audit, cyclonedx, testcontainers) — no hacen falta ni en producción ni en local |

Es el estándar [PEP 735](https://peps.python.org/pep-0735/), soportado nativamente por `uv`:
- `uv sync` instala el paquete **más** los grupos de dependencias (por defecto, `dev`).
- `uv sync --no-dev` instala solo lo que hay en `[project.dependencies]`.

---

## Generación de los `requirements.txt`

Los dos ficheros son **artefactos compilados**: no se editan a mano. `pyproject.toml` es la única fuente de verdad.

| Fichero | Contiene | Lo consume |
|---------|----------|------------|
| `src/requirements.txt` | Solo `[project.dependencies]` + transitivas | `src/Dockerfile` → imagen de producción |
| `.github/requirements-ci.txt` | Lo anterior **+** grupos `dev` y `ci` | `.github/actions/python-setup` → entorno de CI |

Para regenerarlos tras tocar dependencias en `pyproject.toml`, hay que lanzar **los dos comandos**: si solo se actualiza uno, los pines comunes se desincronizan y CI deja de validar lo que realmente se despliega.

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --no-annotate -o src/requirements.txt
uv pip compile pyproject.toml --group dev --group ci --universal --python-version 3.11 --no-annotate -o .github/requirements-ci.txt
```

- `--universal` es obligatorio: se compila en Windows pero se despliega en Linux. Sin él, el resultado se ata a la plataforma que lo genera y se pierden paquetes con marcador (`uvloop` solo existe fuera de Windows, `colorama` solo en Windows).
- `--python-version 3.11` alinea la resolución con `python:3.11-slim` del `Dockerfile`.
- `--no-annotate` deja solo la lista de pines, sin los comentarios `# via` que indican qué paquete arrastra a cuál. Esa trazabilidad se consulta cuando hace falta con `uv pip tree`.
- Al escribir sobre un fichero existente, `uv` respeta los pines actuales como preferencia: solo mueve lo que la nueva restricción obliga a mover. Para forzar la subida de todo, se añade `--upgrade`.

---

## `[tool.hatch.build.targets.wheel]`

| Clave | Qué hace |
|-------|----------|
| `packages = ["src/fitcoach"]` | Le dice a Hatchling explícitamente dónde está el código fuente del paquete a empaquetar |

Redundante con la autodetección por convención de nombres, pero explícito: si mañana se añade otro paquete bajo `src/` (por ejemplo, un cliente separado), esta línea no cambia de significado por sorpresa.

---

## `[tool.ruff]` — linter y formateador

| Clave | Qué hace |
|-------|----------|
| `target-version = "py311"` | Versión de Python contra la que ruff decide qué sintaxis moderna sugerir (regla `UP`). Debe ir alineada con `requires-python` |
| `line-length = 100` | Longitud máxima de línea antes de marcar/formatear |
| `output-format = "concise"` | Formato de salida de los errores en terminal |
| `extend-exclude` | Rutas y patrones que ruff no analiza (ficheros generados, Docker, requirements, scripts) |
| `[tool.ruff.lint].select` | Familias de reglas activas: `E`/`F` (PEP 8 y errores lógicos), `UP` (sintaxis moderna), `B` (bugs comunes), `C4` (comprehensions), `I` (orden de imports), `N` (naming), `S` (seguridad estática), `T20` (prints residuales), `PT` (buenas prácticas en tests) |
| `ignore = ["B008"]` | Regla desactivada explícitamente (default mutable en argumentos, común y aceptado en FastAPI con `Depends(...)`) |
| `[tool.ruff.lint.per-file-ignores]` | Excepciones por ruta: en `tests/**` se permite `assert` (`S101`) y no se exige docstring (`D`) |

---

## `[tool.mypy]` — análisis estático de tipos

| Clave | Qué hace |
|-------|----------|
| `python_version = "3.11"` | Versión de Python que mypy asume al comprobar tipos. Alineada con `requires-python` / Dockerfile |
| `strict = true` | Activa el conjunto más exigente de comprobaciones de una vez |
| `disallow_untyped_defs` / `disallow_incomplete_defs` | Obliga a anotar tipos en todas las funciones |
| `check_untyped_defs` | Comprueba también el cuerpo de funciones sin anotar (por si se cuelan) |
| `no_implicit_optional` | `def f(x: int = None)` no se acepta como `Optional[int]` implícito; hay que anotarlo explícitamente |
| `warn_redundant_casts` / `warn_unused_ignores` | Avisa de `# type: ignore` o `cast()` que ya no hacen falta |
| `warn_return_any` | Avisa si una función anotada devuelve `Any` de forma implícita |
| `warn_unreachable` | Avisa de código muerto que el chequeo de tipos puede detectar |
| `plugins = ["pydantic.mypy"]` | Plugin que entiende los modelos de Pydantic (necesario para que mypy valide bien `BaseModel`/`BaseSettings`) |
| `exclude = "scripts/|tests/"` | mypy no analiza estas rutas |
| `show_error_codes` / `pretty` | Mejoras de legibilidad en la salida de errores |

---

## `[tool.pytest.ini_options]`

| Clave | Qué hace |
|-------|----------|
| `minversion = "8.0"` | Falla si se ejecuta con una versión de pytest más antigua |
| `testpaths = ["tests/unit"]` | Por defecto, `pytest` solo recoge tests unitarios. Para integración: `pytest tests/integration --no-cov` |
| `pythonpath = ["src"]` | Añade `src/` al path para poder importar `fitcoach` sin instalarlo en modo editable |
| `python_files` / `python_classes` / `python_functions` | Convención de nombres que pytest usa para descubrir tests |
| `addopts` | Flags aplicados siempre: limpia caché, traceback corto, verbose, cobertura activada |
| `log_cli*` | Muestra logs en tiempo real durante la ejecución, con formato y nivel `INFO` |

---

## `[tool.coverage.*]`

| Clave | Qué hace |
|-------|----------|
| `[tool.coverage.run].source = ["src"]` | Solo se mide cobertura del código en `src/`, no de tests ni scripts |
| `[tool.coverage.report].fail_under = 80` | El build falla si la cobertura global cae por debajo del 80% |
