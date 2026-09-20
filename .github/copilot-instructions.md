# FitCoachIA Copilot Instructions

## Tooling and validation

- Python 3.11 is the project baseline. Use `uv sync --all-groups` to prepare a local environment; `pyproject.toml` is the dependency source of truth.
- Run the full test suite and enforce the global 80% coverage threshold with `uv run pytest tests --cov=src/fitcoach --cov-fail-under=80` (or `make tests`).
- Unit and integration tests are separate directories:
  - `uv run pytest tests/unit_test --no-cov` / `make unit_tests`
  - `uv run pytest tests/it --no-cov` / `make it_tests`
  - Run an individual test with its node id, for example: `uv run pytest tests/unit_test/test_conversation_service.py::TestRemoveEmojis::test_removes_emoji_and_collapses_leftover_whitespace --no-cov`.
- Run quality checks with `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src/`. Ruff targets Python 3.11, uses a 100-character line length, and its configured rule families include import ordering, security, and pytest rules. Mypy is strict.
- Build the production image with `make build` (the Docker build context is `./src`); `make run` starts it using the root `.env` file on port 8000.
- When changing dependencies, regenerate both checked-in compiled requirements files; do not edit either by hand:

  ```bash
  uv pip compile pyproject.toml --universal --python-version 3.11 --no-annotate -o src/requirements.txt
  uv pip compile pyproject.toml --group dev --group ci --universal --python-version 3.11 --no-annotate -o .github/requirements-ci.txt
  ```

## Architecture

- `fitcoach.main` owns the FastAPI app and lifespan. Startup configures logging and fails fast by validating both Telegram and LLM settings plus every configured Telegram command. It mounts the simple `/test` word-counter router and the `/webhook` Telegram router.
- API modules should only translate HTTP and wire dependencies. Put message-processing decisions in `service/`: `ConversationService` receives a Telegram `Bot` and an `LLM`, normalizes incoming text, routes `/start`, `/interview`, `/doubts`, and `/progress`, and otherwise builds the model input and replies to Telegram.
- The webhook accepts raw JSON and converts it to `telegram.Update` in `parse_update`. It must return 400 for malformed JSON, but return `{"ok": true}` after valid updates even if downstream processing fails: Telegram retries non-2xx webhook deliveries. `ConversationService.handle_update` therefore logs and sends a user-facing fallback instead of propagating ordinary processing failures.
- Telegram and LLM collaborators are FastAPI dependencies. `get_bot`, `_create_bot`, `get_settings`, `get_ia_settings`, and `get_interviewer_chain` are cached so their HTTP connection pools and configuration are shared. Tests override `get_bot`/`get_interviewer_chain` at the FastAPI app boundary and pass `AsyncMock` collaborators to services.
- The LLM adapter posts OpenAI-compatible chat-completions requests to `{ia_base_url}/v1/chat/completions`. `IAInput`/`IAMessage` in `domain/entities.py` are the boundary representation and serialize to `{"role", "content"}` dictionaries.
- Agent creation is centralized in `service/agent/agent_factory.py`. `PromptLoader` optionally composes an agent's `system_prompt.txt` with its `SKILL.md`, replaces `{{skill_content}}`, and intentionally leaves `{{rag_context}}` for request-time insertion by the domain agent.

## Repository-specific conventions

- Configuration comes from OS environment variables first, then `.env.<APP_ENV>`, then `.env`; `APP_ENV` defaults to `dev`. Telegram settings use `bot_telegram_*`; LLM settings use the `ia_` prefix. Keep `.env.example` aligned when adding required settings.
- `bot_telegram_commands` is a comma-separated list of `name:description` entries. Preserve this format and validate entries through `to_bot_command`; malformed command configuration must prevent application startup.
- Keep user-facing Telegram text and message-cleaning/logging limits in `domain/constants.py`, rather than scattering literals across controllers and services.
- `ConversationService` deliberately strips emoji before command detection or LLM input, preserves Telegram forum `message_thread_id` when replying, and includes an update/chat/thread/message/user prefix on its logs. Preserve those behaviors when adding message flows.
- For tests that exercise cached settings, clear the relevant `lru_cache` functions or construct `Settings`/`IASettings` with `_env_file=None` so local `.env` files cannot affect the result.
- Follow the existing test layout and naming: `tests/unit_test` for isolated unit tests, `tests/it` for FastAPI/lifespan integration tests, and `test_*.py` / `Test*` / `test_*` discovery names.
