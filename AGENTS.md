# AGENTS.md — FitCoachIA

Conceptual map of the project for any AI assistant (Claude, Copilot, Codex/OpenAI, Cursor...).
Read it fully before changing anything. It describes how the project is **structured today**; it is not a backlog.

Language rules: code, identifiers and this file in **English**; everything under `docs/` and `README.md` in **Spanish**.

---

## 0. Golden rules

1. Do only what was asked. No unrequested features, refactors or rewrites.
2. **Forbidden files**: never read, write, grep, glob or print any `.env` / `.env.*` file (root or `infra/*/.env`).
   The only allowed ones are `*.example` (`.env.example`, `infra/embedder/.env.embedder.example`,
   `infra/vector-db/.env.vector-db.example`, `infra/observability/.env.example`).
   Do not run commands that print resolved env values (e.g. `docker compose config` with `--env-file`).
3. New environment variables go in the `.env.example` of the affected component, never in a real `.env`.
   If a value must change in a real `.env`, propose it in the chat and let the user apply it.
   If a new variable is required to start the app, warn the developer explicitly that it must be set in the real `.env`.
4. **Docs, README, Docker composes and tests must always reflect the code.** Every change keeps them updated in the same
   change, and whenever you touch an area you also fix any stale statement about it you find in those files
   (see the mandatory checklist in section 12).
5. If something cannot be verified in this environment (Docker, network, real `.env`), say so explicitly; never claim it was verified.
6. **Complete every development.** A feature is done only when all the dependencies it actually needs exist:
   tests (OK and KO) and docs always; Alembic migration, env vars, composes, Makefile/workflows, dependencies and other
   associated pieces only if the change requires them (section 12). List the detected ones in the plan; do not add unneeded ones.
7. **Document every development in `docs/`** (Spanish). Pick the existing file whose topic is coherent with the feature
   and extend it if it fits; if none fits, ask the developer, proposing `docs/<feature>.md`, and add it to the docs index (section 12).
8. **Questions about documentation are answered from `docs/` first** (index in section 12), then checked against the code.
   If they disagree, report it, state what should be updated and ask whether to update it; the code is the source of truth.

### Working protocol (developer = supervisor)

The developer decides; the AI analyses, proposes and executes only what was approved.

1. **Analyse before acting.** Do not execute a request literally. Check it against the current design (this file, the code, `docs/`)
   and look for conflicts, side effects and simpler or safer alternatives.
2. **Do not assume the idea is good.** If there is room for improvement, say so and present the alternative with its trade-off
   *before* applying anything, so the developer can weigh it and choose. Agreeing is fine when the idea holds up; say why.
3. **Present a short plan first.** For any non-trivial change, summarize what will change and why (a few lines, no padding):
   files/areas affected, the reason for each change, and anything the developer should be aware of (risks, docs/tests/composes to update).
4. **Wait for explicit approval** before applying it. Never apply a change "because it seems right".
5. **Ask when in doubt.** Any ambiguity, open question or decision not covered by this file goes to the developer; do not pick an option
   on your own. Ask concise, specific questions and offer a recommended default.
6. **Stay inside what was approved.** If new findings change the plan while working, stop and consult again instead of widening the scope.
7. Trivial, unambiguous edits (typos, a rename the developer spelled out) may be applied directly, stating what was done.
   They must not alter the planned development. If applying one changes or leaves the approved plan and it is not trivial,
   ask the developer which change to apply before doing it.

---

## 1. Architecture at a glance

Modular monolith (FastAPI) with layered / ports-and-adapters structure. Dependency rule:
`api -> service -> domain <- repository (ports) <- infrastructure (adapters)`. `main.py` is the composition root.

```
src/fitcoach/
  main.py            FastAPI app + lifespan (fail-fast validation of ALL settings, telemetry, pool shutdown)
  api/               HTTP only: parse request, wire dependencies, delegate. Endpoints: / , /health , /webhook/response
  service/           Use cases. conversation_service.py routes Telegram commands; agent/ holds the LLM chains
  domain/            Pydantic entities/value objects, enums, errors, user-facing texts (constants.py). No I/O
  repository/        Ports (typing.Protocol): ConversationRepository, ExerciseRepository,
                     TrainingRepository, EvaluationRepository
  infrastructure/    Adapters: bot, config, database, vectordb, ia, prompts, observability, jobs
```

Key facts per layer:

- **api/webhook.py**: Telegram sends raw JSON; `parse_update` builds a `telegram.Update` (400 on malformed JSON).
  After a valid update it **always returns `{"ok": true}`** (Telegram retries non-2xx). `ConversationService.handle_update`
  never propagates exceptions: it logs and replies with a user-facing fallback.
- **service/conversation_service.py**: strips emojis before command detection, keeps `message_thread_id` when replying,
  prefixes logs with an update/chat/thread/message/user context, routes `Commands` (`domain/telegram.py`):
  `/start`, `/interview`, `/train`, `/doubts`, `/progress` and free messages (by interview/training state).
  `callback_query` and `poll_answer` updates are handled before command routing.
- **service/agent/**: `llm_chain.py` (`BaseLLMChain`: one invocation, token usage, provider-error mapping,
  JSON validation with a single repair attempt), `interviewer_chain.py`, `trainer_chain.py` (subclasses),
  `agent_factory.py` (composes system prompts), `exercise_retriever.py` + `rag_context.py` (RAG for the trainer).
- **domain/**: `agents.py` (`AgentType`, `Agent`, `InterviewerAgent`, `TrainerAgent`), `interviewer_profile.py`,
  `trainer_plan.py`, `conversation.py`, `exercise.py`, `token_usage.py`, `agent_errors.py` (`AgentError`/`AgentErrorCode`),
  `constants.py` (**all user-facing texts and cleaning/logging limits live here**), `telegram.py`.
- **infrastructure/**:
  - `config/settings.py` (pydantic-settings, one class per prefix) and `logging_config.py` (`log_`).
  - `database/` SQLAlchemy async models, session, `PostgresConversationRepository`, FastAPI dependencies.
  - `vectordb/` read-only pgVector models/session/`PgVectorExerciseRepository`.
  - `ia/` `embedder_client.py` and `skills/<skill>/SKILL.md` (agent knowledge, `-dev` variants are lighter versions).
  - `prompts/` `<agent>/system_prompt.txt` + `prompt_loader.py`.
  - `bot/telegram_bot.py` (python-telegram-bot, `to_bot_command`), `observability/telemetry.py` (OpenTelemetry).
  - `jobs/` standalone workers run as separate containers with the app image (`python -m ...`):
    `training_reminders.py` (mesocycle due reminders) and `evaluation.py` (weekly satisfaction polls).
    Both share `worker_loop.py` (periodic loop, SIGTERM, one DB session per tick) and
    `telegram_delivery.py` (Telegram error -> retry/fail with the configurable `RetryPolicy`).
- **Weekly polls**: `training_evaluation` is both outbox and result. The 4 rows of a cycle are inserted in the
  same transaction that dates the cycle (`schedule_evaluations`); `close_cycle` and `/interview` cancel the pending
  ones (`cancel_pending_evaluations`). Votes arrive as `poll_answer` updates handled by `ConversationService`.
  Details in `docs/encuestas-satisfaccion.md`.
- Cached providers (`lru_cache`): `_create_bot`, `get_settings`, `get_ia_settings`, `get_database_settings`,
  `get_vector_database_settings`, `get_embedder_settings`, `get_interviewer_chain`, `get_trainer_chain`.
- Observability: OpenTelemetry traces (exported only if `otel_exporter_otlp_endpoint` is set), structured JSON logs and
  `token_usage` rows per LLM call. Backend stack lives in `infra/observability`.

---

## 2. External services

| Service | Role | Adapter / location | Config prefix |
|---|---|---|---|
| Telegram | Only entry point (webhook) and output channel | `infrastructure/bot`, `api/webhook.py` | `bot_telegram_*` |
| PostgreSQL (conversational) | Messages, interview profiles, training plans, token usage, model prices | `infrastructure/database`, **Alembic** | `database_*` |
| PostgreSQL + pgVector (exercise catalogue) | Read-only RAG corpus, separate server and role | `infrastructure/vectordb`, DDL in `infra/vector-db/ddl` | `vector_database_*` |
| Embedder service | Query embeddings; **must use the same model as the corpus** (all-MiniLM-L6-v2, 384 dims) | `infrastructure/ia/embedder_client.py`, `infra/embedder` | `embedder_*` |
| LLM | Any **OpenAI-compatible** API through `langchain-openai` (`ChatOpenAI`); provider is swappable | `service/agent/*_chain.py` | `ia_*` |
| Observability (OpenTelemetry) | Traces and logs | `infrastructure/observability`, `infra/observability` | `otel_*`, `log_*` |

---

## 3. Agents (today: Interviewer, Trainer; designed to grow)

- **Interviewer (agent 1)**: structured interview -> `InterviewerProfile` (JSON validated by Pydantic).
- **Trainer (agent 2)**: profile + RAG exercises -> 4-week `TrainingPlan`; must pick exercises only from the retrieved corpus.
- `AgentType` already reserves `NUTRITIONIST` and `COACH` (placeholders, no implementation).

Each agent is made of the same pieces. To add one, mirror the existing ones:

1. `domain/agents.py`: value in `AgentType` + `<Name>Agent` entity; output model in `domain/<name>_*.py`.
2. `infrastructure/prompts/<agent>/system_prompt.txt` (placeholders `{{skill_content}}`, `{{rag_context}}`)
   and `infrastructure/ia/skills/<agent>/SKILL.md` (+ optional `<agent>-dev`).
3. `service/agent/agent_factory.py`: `build_<agent>_agent`.
4. `service/agent/<agent>_chain.py`: subclass of `BaseLLMChain` + cached `get_<agent>_chain()` built with `ChatOpenAI`.
5. `IASettings` fields prefixed `ia_<agent>_*` (skill, max tokens, timeout, history window) + `.env.example`.
6. Telegram command: entry in `bot_telegram_commands` (`name:description`), `Commands` enum, routing in `ConversationService`.
7. Persistence: methods in the `ConversationRepository` port and `PostgresConversationRepository`; schema change => Alembic migration.
8. Wiring in `api/webhook.py` (`get_conversation_service`) and, if needed, lifespan validation in `main.py`.
9. Tests (unit + IT with the stub server) and `docs/<agent>-agent.md`.

---

## 4. Configuration

- Precedence: OS env vars > `.env.<APP_ENV>` > `.env` > defaults (`APP_ENV` defaults to `dev`).
- One `BaseSettings` class per prefix in `infrastructure/config/settings.py`; `main.py` lifespan instantiates all of them
  so a missing/malformed value aborts startup (fail fast).
- `bot_telegram_commands` is `name:description` pairs joined by commas; validate through `to_bot_command`.
- New variable => add it (commented/with placeholder) to the matching `.env.example`, document it in `docs/how-to.md`,
  and add it to the compose files that need it (section 8).
- Tests that touch cached settings: call `cache_clear()` or build settings with `_env_file=None`.

---

## 5. Database

- **Conversational DB** (SQLAlchemy 2 async + asyncpg): models in `infrastructure/database/models.py`; versioned with **Alembic**
  (`alembic/`, `alembic.ini`; `alembic/env.py` reads `database_url` and `Base.metadata`). The container ENTRYPOINT runs
  `alembic upgrade head` before starting the API.
  - Every table is defined in `infrastructure/database/models.py` (the only module `alembic/env.py` imports; models
    elsewhere are missed by autogenerate).
  - Any model/schema change (new table, column, index, constraint) => new revision in `alembic/versions/`
    (autogenerate, then review by hand).
  - Migrations must be backward compatible: add first, deploy code, remove later. Never rename/drop columns in use.
  - Keep data migrations separate from schema migrations. Keep the `ConversationRepository` port, its Postgres
    implementation and the tests in sync.
- **Vector DB** (pgVector, read-only role `fitcoach_ro`): **not** managed by Alembic. Schema and data are numbered SQL scripts in
  `infra/vector-db/ddl/` (`NNN_YYYY-MM-DD_<name>.sql`), with its own lifecycle (`make vector-up`). Document changes in `docs/vector-db.md`.

---

## 6. Dependencies (mandatory flow)

`pyproject.toml` is the single source of truth for the app. **Never edit `src/requirements.txt` or `.github/requirements-ci.txt` by hand.**

1. **Ask the user** what the new library is for: runtime (app), `test`, `lint`, `ci` or `dev` (local only).
2. Add it to the right place in `pyproject.toml` (`[project].dependencies` for runtime, otherwise the matching `[dependency-groups]`).
3. Regenerate both files from the TOML:
   ```bash
   uv pip compile pyproject.toml --universal --python-version 3.11 --no-annotate -o src/requirements.txt
   uv pip compile pyproject.toml --group dev --group ci --universal --python-version 3.11 --no-annotate -o .github/requirements-ci.txt
   ```
4. Update `docs/toml.md`.

Out of scope of this flow (independent images with their own pins): `infra/embedder/requirements.txt`,
`infra/vector-db/loader/requirements.txt`.

---

## 7. Makefile and CI/CD

The `Makefile` is the shared entry point for local use and GitHub workflows (`.github/`). Do not duplicate its logic in YAML.

- Targets: `build`, `run`, `stop`, `logs`, `clean*`, `tests`, `dev-up|down|logs`, `prod-up|down|logs`, `vector-up|down|logs`.
- `make tests`: starts `tests/docker-compose-test.yml`, runs unit + IT with coverage >= 80 %, tears it down.
  CI calls `make tests PYTEST=pytest`.
- `make prod-up` is what `deploy.yml` runs on the server. The deploy copies **only** `docker-compose.yml` and `Makefile`,
  so the prod compose cannot depend on other repo files.
- Workflows: `build.yml` (quality + security + semgrep + tests on `feat/**`, `feature/**`, `fix/**`, `bugfix/**`),
  `release.yml` (image build, Trivy, GitHub release, then `deploy.yml`), `validate-*-merge.yml`.
  Composite actions: `.github/actions/python-setup` and `quality-check` (ruff, mypy, gitleaks, pip-audit, bandit).
- Branch flow: `feat|feature|fix|bugfix/*` -> `develop` -> `main`. Direct commits to `main`/`develop` are blocked.
- A change to targets, workflows or actions => update `docs/Makefile.md` / `docs/ci-cd.md`.

---

## 8. Containers and environments

| File | Purpose | Notes |
|---|---|---|
| `docker-compose.dev.yml` | Development stack (`build:`), incl. `training-reminders-dev` and `evaluation-dev` workers | Reference one: change here first |
| `docker-compose.local.yml` | Local all-in-one stack, used to **try changes locally** | Reads root `.env` |
| `docker-compose.yml` | Production (`image:` published, no `build:`) | Adapt, do not copy, from dev |
| `tests/docker-compose-test.yml` | Integration tests (app + Postgres + pgVector + stub server) | Must always work with `make tests` |
| `infra/vector-db/docker-compose.vector-db*.yml` | pgVector catalogue (independent lifecycle) | Not part of app compose |
| `infra/observability/compose.yml` | Grafana/Loki/Tempo/Prometheus/OTel collector | Independent of app code |
| `infra/embedder/` | Embedder image (own Dockerfile, requirements) | Independent of app code |

Workflow for a compose-affecting change: edit **dev** -> try it with **local** -> if it works, replicate in **prod**
(keep prod-specific things: `image:`, `restart`, healthchecks, networks, env files) -> keep the **test** compose runnable.
Dockerfile (`src/Dockerfile`): multi-stage, non-root user, context = repo root (`docker build -f src/Dockerfile .`);
it only copies `src/requirements.txt`, `src/fitcoach`, `alembic` and `alembic.ini`.

`.dockerignore` and `.gitignore` must stay current. Rule for `.dockerignore`: anything not needed to build the image
stays out of the build context.

---

## 9. Tests

- `tests/unit_test/` (isolated, no network/Docker; mock repositories, bots and chains with `AsyncMock`),
  `tests/it/` (FastAPI + lifespan against the real containers of the test compose), `tests/fixtures/`
  (`stub_server.py` fakes Telegram, LLM and embedder; `exercises_min.sql` is the minimal pgVector corpus).
- Discovery: `test_*.py`, classes `Test*`, functions `test_*`; name tests by scenario and expected result.
- **Every test level covers both the OK (happy path) and the KO (failure path) cases.**
- Coverage >= 80 % on `src/fitcoach`. Do not test trivial getters/DTOs.
- Override dependencies at the FastAPI boundary (`app.dependency_overrides`, e.g. `get_bot`, `get_conversation_service`).
- New external dependency or endpoint => extend the stub server / fixtures / test compose accordingly.
- Commands: `make tests` (full), `uv run pytest tests/unit_test --no-cov` (unit only).

---

## 10. Verification before finishing

Always try to run, when available, what the repo enforces (report anything you could not run):

1. `pre-commit run --all-files` (hooks in `.pre-commit-config.yaml`: hygiene, gitleaks, ruff, ruff-format, bandit).
2. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/` (strict), `uv run pip-audit`.
3. `make tests` (needs Docker).

---

## 11. Style

- Python 3.11, line length 100, ruff rules E,F,UP,B,C4,I,N,S,T20,PT, mypy strict, Pydantic v2.
- Match surrounding code: naming, typing, idioms. Prefer composition and ports over inheritance and concrete imports.
- Comments: terse, one short line stating the goal only. Anything longer goes to `docs/`.
- User-facing texts and limits go in `domain/constants.py`; no scattered literals.
- Logging through `logging` with the conversation context prefix; never `print`.

---

## 12. Mandatory maintenance checklist

Update every item that the change touches, in the same change:

| If you change... | Also update |
|---|---|
| Any behaviour, flow or design | the matching file in `docs/` (Spanish), chosen as in golden rule 7 — **mandatory** |
| Code | unit + IT tests (OK and KO cases) — **mandatory** |
| Services, ports, env vars | `docker-compose.dev.yml`, `docker-compose.local.yml`, `docker-compose.yml`, `tests/docker-compose-test.yml` as needed |
| Env vars | the matching `.env.example` (+ `docs/how-to.md`) |
| DB models | Alembic revision (conversational DB) or `infra/vector-db/ddl` script (vector DB) |
| Dependencies | `pyproject.toml` -> regenerate both requirements files -> `docs/toml.md` |
| Project structure (folders, files, composes), Makefile commands, Docker build/run, CI/CD workflows, setup | `README.md` — check its project tree, command table and CI/CD table against the real repo |
| New generated/local files | `.gitignore` and `.dockerignore` |
| Makefile, workflows, actions | `docs/Makefile.md`, `docs/ci-cd.md` |
| Architecture, layers, agents, this map | this `AGENTS.md` |

Docs index: `docs/how-to.md` (setup/run), `docs/interviewer-agent.md`, `docs/trainer-agent.md`, `docs/train-command-flow.md`,
`docs/encuestas-satisfaccion.md` (weekly polls + configurable retry properties of both workers),
`docs/vector-db.md`, `docs/modelo-datos.md`, `docs/entornos-y-despliegue.md`, `docs/observabilidad.md` + `docs/OTLP.md` + `docs/queries-reference.md` + `docs/dashboard-logs-guide.md`,
`docs/ci-cd.md`, `docs/Makefile.md`, `docs/Dockerfile-guide.md`, `docs/toml.md`, `docs/telegram-environments.md`.
`docs/plan/` holds design notes and `docs/todo/` the backlog.
