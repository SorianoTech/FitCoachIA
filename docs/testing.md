# Ejecución de tests

Esta guía recoge los comandos habituales para validar FitCoachIA desde la raíz del repositorio.
El proyecto usa Python 3.12, `uv` para gestionar el entorno y `pytest` como framework de tests.

## Preparar el entorno

Instala todas las dependencias de desarrollo:

```bash
uv sync --all-groups
```

No es necesario activar manualmente el entorno virtual: los comandos `uv run` utilizan el
entorno del proyecto.

## Suite completa

La validación completa levanta la infraestructura de integración con Docker, ejecuta los tests
unitarios y de integración, y exige una cobertura global mínima del 80 %:

```bash
make tests
```

Este es el comando recomendado antes de abrir o actualizar una pull request. El target elimina el
stack de test al terminar, tanto si los tests pasan como si fallan.

La ejecución equivalente de `pytest`, cuando la infraestructura de integración ya está disponible,
es:

```bash
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80
```

## Tests unitarios

Los tests unitarios no necesitan Docker, red ni servicios externos:

```bash
uv run pytest tests/unit_test --no-cov
```

Para ejecutar un fichero concreto sin aplicar las opciones globales de cobertura y verbosidad:

```bash
uv run pytest -o addopts='' tests/unit_test/test_conversation_service.py --no-cov -q
```

Para ejecutar un único test, usa su `node id`:

```bash
uv run pytest -o addopts='' \
  tests/unit_test/test_conversation_service.py::TestRemoveEmojis::test_removes_emoji_and_collapses_leftover_whitespace \
  --no-cov -q
```

También se pueden seleccionar tests por una parte de su nombre:

```bash
uv run pytest -o addopts='' tests/unit_test -k "quota" --no-cov -q
```

## Tests de integración

Los tests de `tests/it` necesitan el stack definido en `tests/docker-compose-test.yml`. La forma
más sencilla y segura de ejecutarlos junto con su infraestructura es:

```bash
make tests
```

Si el entorno de integración ya está levantado, pueden ejecutarse directamente:

```bash
uv run pytest tests/it --no-cov
```

## Cobertura

Para comprobar explícitamente el umbral global del 80 %:

```bash
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80
```

El informe detallado por líneas puede generarse añadiendo `--cov-report=term-missing`:

```bash
uv run pytest tests --cov=src/fitcoach --cov-fail-under=80 --cov-report=term-missing
```

## Calidad antes de entregar cambios

Además de los tests, ejecuta las comprobaciones de estilo, formato y tipos:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Una validación completa debe dejar todos estos comandos sin errores y mantener la cobertura global
por encima del 80 %.

## Diagnóstico de fallos

- Usa el primer traceback como causa principal; los fallos posteriores pueden ser consecuencias.
- Ejecuta primero el test que falla mediante su `node id` para reducir ruido.
- Los unitarios deben ser herméticos: no deben depender de `.env`, red, Docker ni servicios reales.
- Si falla la integración, revisa los logs del stack:

  ```bash
  docker compose -f tests/docker-compose-test.yml logs --tail 100
  ```

- Si `pytest` recoge más tests de los esperados, usa `-o addopts=''` en ejecuciones focalizadas.
