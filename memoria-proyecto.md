# Plan: Memoria del proyecto FitCoachIA (≤ 20 páginas, formato .docx)

## Goal
Redactar la memoria/resumen ejecutivo de FitCoachIA (en español) con los 9 apartados exigidos y exportarla a `.docx`, usando como fuente `docs/` y el código.

## Tasks
- [x] 1. Decidir ubicación y formato: borrador en `docs/memoria-proyecto.md` (español, índice de docs) y export a `.docx` con `pandoc` (hay que instalarlo; no está) → Verify: `pandoc --version`
- [x] 2. Reunir datos de negocio (apartado 2): `README.md`, `docs/plan/metricas-negogio-y-tecnicas.md`, `docs/encuestas-satisfaccion.md`; el análisis de mercado requiere fuentes externas → Verify: lista de cifras con fuente
- [x] 3. Contribución individual (apartado 3): `docs/AUTHORS.md` + `git shortlog -sn` (SorianoTech/Sergio Soriano, Raúl, Ángel Pérez, Juan Martínez) → Verify: **el usuario confirma roles por persona** (no se pueden deducir solo de commits)
- [x] 4. Arquitectura (apartado 4): diagrama de capas/puertos y de despliegue (Mermaid → PNG), justificar FastAPI, Postgres+pgVector, embedder, Telegram, OpenTelemetry, AWS EC2; fuentes `docs/despliegue-aws-ec2*.md`, `docs/modelo-datos.md` → Verify: diagramas renderizan
- [x] 5. Diseño de la IA (apartado 5, 30 %): agentes Entrevistador/Entrenador/Curador, RAG de ejercicios, memoria, evaluador, planes de 4 semanas; fuentes `docs/interviewer-agent.md`, `trainer-agent.md`, `rag-recuperacion-ejercicios.md`, `memoria-agentes.md`, `plan-evaluator.md` → Verify: cada afirmación contrastada con el código en `src/fitcoach/service/agent/`
- [x] 6. Proceso de IA (apartado 6): modelos preentrenados vía API OpenAI-compatible (sin fine-tuning), embeddings all-MiniLM-L6-v2 local, prompts/skills → Verify: valores de `settings.py`
- [x] 7. DevOps (apartado 7, 20 %): CI/CD (`docs/ci-cd.md`), `make tests` y cobertura ≥ 80 %, versionado/releases, observabilidad (Grafana/Loki/Tempo) → Verify: datos coinciden con `.github/workflows`
- [x] 8. Evaluación (apartado 8): métricas técnicas (latencia, tokens/coste desde `token_usage`, cobertura) y funcionales (encuestas semanales) → Verify: **pedir al usuario datos reales de producción/pruebas**; no inventar cifras
- [x] 9. Introducción/resumen ejecutivo y conclusiones/trabajo futuro (apartados 1 y 9, a partir de `docs/todo/`, `AGENTS.md` §3) → Verify: se escriben al final
- [x] 10. Verificación: exportar `.docx`, comprobar ≤ 20 páginas (convertir a PDF y contar), revisar índice y diagramas → Verify: `.docx` abre y numera 9 apartados

## Done When
- [x] Existe el `.docx` con los 9 apartados, ≤ 20 páginas, sin cifras inventadas.

## Notes / preguntas abiertas
- AGENTS.md: docs en español y todo documento nuevo en `docs/` debe añadirse al índice de docs (§12) → propongo `docs/memoria-proyecto.md` (y tocar `AGENTS.md` índice). ¿De acuerdo, o prefieres solo el `.docx` fuera del repo?
- Necesito: roles de cada miembro, datos reales de evaluación y si hay análisis de mercado ya hecho.
- Dependencia nueva `pandoc` solo local (no entra en `pyproject.toml`).
