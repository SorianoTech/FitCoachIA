# Variables para personalizar fácilmente
DOCKER=docker
IMAGE_BASE=fitcoachia/fitcoach-app
IMAGE_LATEST=$(IMAGE_BASE):latest
CONTAINER_NAME=fitcoach-ia
PORT=8000
version ?= latest
BASE_PACKAGE=src
BASE_TEST_PACKAGE=tests
UNIT_TEST_PACKAGE=$(BASE_TEST_PACKAGE)/unit_test
IT_TEST_PACKAGE=$(BASE_TEST_PACKAGE)/it

# Prefiere .venv (layout por defecto de uv) y cae a venv si no existe.
VENV:=$(if $(wildcard .venv),.venv,venv)
PYTEST=$(VENV)/Scripts/pytest.exe

COMPOSE_IT=tests/docker-compose-test.yml
IT_PORT ?= 8001
IT_BASE_URL ?= http://localhost:$(IT_PORT)
export IT_PORT
export IT_BASE_URL

COMPOSE_UP=$(DOCKER) compose -f $(COMPOSE_IT) up -d --build --wait
COMPOSE_DOWN=$(DOCKER) compose -f $(COMPOSE_IT) down -v --remove-orphans

# Fichero de entorno del sistema; si no existe se usa el .env del repositorio
ENV_FILE ?= /etc/fitcoachia/dev/.env.dev
ENV_FALLBACK=.env

COMPOSE_APP=$(DOCKER) compose
APP_SERVICE=fitcoach-ia
INTERNAL_NETWORK ?= fitcoach-internal
PROXY_NETWORK ?= proxy-network
# La BD vectorial tiene su propio proyecto y ciclo de vida: los ejercicios se
# cargan una sola vez y sobreviven a los despliegues de la app.
COMPOSE_VECTOR=$(DOCKER) compose -f infra/vector-db/docker-compose.vector-db.yml
# rag-doc (FAQ sobre docs/ e infra/) tambien tiene su propio proyecto y ciclo de vida.
COMPOSE_RAG=$(DOCKER) compose -f infra/rag-doc/docker-compose.rag-doc.yml

define ensure_networks
for network in "$(INTERNAL_NETWORK)" "$(PROXY_NETWORK)"; do \
	$(DOCKER) network inspect "$$network" >/dev/null 2>&1 || $(DOCKER) network create "$$network"; \
done
endef

define resolve_env
if [ -r "$(ENV_FILE)" ]; then \
	RESOLVED_ENV_FILE="$(ENV_FILE)"; \
elif [ -f "$(ENV_FALLBACK)" ]; then \
	RESOLVED_ENV_FILE="$(ENV_FALLBACK)"; \
	echo ">> $(ENV_FILE) no encontrado o ilegible -> usando $(ENV_FALLBACK)"; \
else \
	echo "ERROR: no existe $(ENV_FILE) ni $(ENV_FALLBACK) (si el primero es de root, ejecuta con sudo)"; \
	exit 1; \
fi; \
echo ">> fichero de entorno: $$RESOLVED_ENV_FILE"; \
export FITCOACH_ENV_FILE="$$RESOLVED_ENV_FILE"
endef

.PHONY: container build run stop clean all help clean-image clean-images logs tests networks up app down app-logs vector-up vector-down vector-logs rag-up rag-down rag-logs rag-index rag-eval trainer-debug trainer-compare trainer-refresh-catalogues
# Usa siempre el pytest del venv del proyecto, evitando depender de cuál
# pytest gane por orden del PATH del shell. En CI (sin venv, deps instaladas
# --system) se sobreescribe con `make tests PYTEST=pytest`.

help:
	@echo "Comandos disponibles Docker"
	@echo "  make container                      - Consulta los contenedores"
	@echo "  make build [version=x.y.z]          - Construye la imagen de Docker (Por defecto, latest). Si indicas version, genera las imagenes latest y x.y.z (Defecto: latest)"
	@echo "  make run [version=x.y.z]            - Ejecuta el contenedor con la imagen (previamente generada) latest o version x.y.z indicada en el puerto $(PORT)"
	@echo "  make stop                           - Detiene y elimina el contenedor si está corriendo"
	@echo "  make logs                           - Muestra los logs del contenedor"
	@echo "  make clean                          - Detiene el contenedor y elimina todas las imagenes $(IMAGE_BASE)"
	@echo "  make all                            - Construye y ejecuta todo (limpiando primero)"
	@echo "  make clean-images                   - Elimina todas las imagenes en local"
	@echo "  make clean-image [version=x.y.z]    - Elimina solo la imagen de la version indicada (Defecto: latest)"
	@echo "  make tests                          - execute all tests (unit test and it tests). Analiza cobertura y falla si cobertura < 80% "
	@echo "  make networks                       - Crea las redes Docker compartidas (internal, proxy y observabilidad)"
	@echo "  make up                             - Construye y levanta la app. Usa $(ENV_FILE) si existe, si no $(ENV_FALLBACK)"
	@echo "  make app                            - Reconstruye y reinicia solo la API (sin embedder ni postgres)"
	@echo "  make down                           - Detiene la app"
	@echo "  make app-logs                       - Muestra los logs de la app"
	@echo "  make vector-up                      - Levanta pgVector y pgAdmin con el catalogo de ejercicios"
	@echo "  make vector-down                    - Detiene la base de datos vectorial (conserva el volumen)"
	@echo "  make vector-logs                    - Muestra los logs de la base de datos vectorial"
	@echo "  make rag-up                         - Levanta rag-doc (FAQ sobre docs/ e infra/) y su Qdrant"
	@echo "  make rag-down                       - Detiene rag-doc (conserva el volumen de Qdrant)"
	@echo "  make rag-logs                       - Muestra los logs de rag-doc"
	@echo "  make rag-index                      - Reindexa en Qdrant la lista blanca de infra/rag-doc/sources.yml"
	@echo "  make rag-eval ARGS=\"...\"            - Eval offline de retrieval de rag-doc (limitada a 2 CPUs y 3 GB; ARGS=\"--variants min300\")"
	@echo "  make trainer-debug ARGS=\"...\"       - Ejecuta el entrenador offline y guarda artefactos en runs/trainer (ver docs/trainer-agent.md)"
	@echo "  make trainer-compare ARGS=\"...\"     - Compara skills/modelos sobre el golden set"
	@echo "  make trainer-refresh-catalogues     - Regenera los catalogos congelados de evals/trainer/cases con la recuperacion real"

container:
	@$(DOCKER) ps -a

networks:
	@$(ensure_networks)

build:
	@$(DOCKER) build -t $(IMAGE_BASE):$(version) -f src/Dockerfile .
	@if [ "$(version)" != "latest" ]; then \
		$(DOCKER) tag $(IMAGE_BASE):$(version) $(IMAGE_LATEST); \
		echo "Imagen construida: $(IMAGE_BASE):$(version) (también etiquetada como latest)"; \
	else \
		echo "Imagen construida: $(IMAGE_LATEST)"; \
	fi

up:
	@$(ensure_networks); \
	$(resolve_env); \
	$(COMPOSE_APP) --env-file "$$FITCOACH_ENV_FILE" up -d --build --remove-orphans

# Reconstruye solo la API: --no-deps evita reconstruir el embedder (lento) y postgres,
# que deben estar ya levantados con `make up`.
app:
	@$(ensure_networks); \
	$(resolve_env); \
	$(COMPOSE_APP) --env-file "$$FITCOACH_ENV_FILE" up -d --build --no-deps $(APP_SERVICE)

down:
	@$(resolve_env); \
	$(COMPOSE_APP) --env-file "$$FITCOACH_ENV_FILE" down --remove-orphans

app-logs:
	@$(resolve_env); \
	$(COMPOSE_APP) --env-file "$$FITCOACH_ENV_FILE" logs -f

vector-up:
	@$(COMPOSE_VECTOR) up -d --build

# Sin -v a proposito: el volumen guarda la carga inicial de 283 MB y volver a
# crearlo tarda varios minutos. Para borrarlo de verdad, hazlo explicitamente.
vector-down:
	@$(COMPOSE_VECTOR) down --remove-orphans

vector-logs:
	@$(COMPOSE_VECTOR) logs -f

rag-up:
	@$(ensure_networks)
	@$(COMPOSE_RAG) up -d --build

# Sin -v a proposito: el indice de Qdrant se conserva entre despliegues.
rag-down:
	@$(COMPOSE_RAG) down --remove-orphans

rag-logs:
	@$(COMPOSE_RAG) logs -f

# Reindexa la lista blanca infra/rag-doc/sources.yml en Qdrant (idempotente)
rag-index:
	@$(ensure_networks)
	@$(COMPOSE_RAG) up -d qdrant
	@$(COMPOSE_RAG) --profile index run --rm --build indexer

# Eval offline de retrieval (sin LLM); el contenedor limita CPU/RAM para no bloquear el servidor
rag-eval:
	@mkdir -p infra/rag-doc/eval/results && chmod 777 infra/rag-doc/eval/results
	@$(COMPOSE_RAG) --profile eval run --rm --build evaluator python /app/eval/retrieval_eval.py $(ARGS)

# Depuracion offline del entrenador: sin Telegram ni BD de conversaciones.
trainer-debug:
	@$(resolve_env); \
	uv run python -m fitcoach.devtools.trainer_debug $(ARGS)

trainer-compare:
	@$(resolve_env); \
	uv run python -m fitcoach.devtools.trainer_compare $(ARGS)

TRAINER_CASES=evals/trainer/cases

trainer-refresh-catalogues:
	@$(resolve_env); \
	for case in $(TRAINER_CASES)/*/; do \
		uv run python -m fitcoach.devtools.trainer_debug --case-dir "$$case" --live-retrieval \
			--save-catalogue "$$case/catalogue.json" --render-only --out /tmp/fitcoach-trainer-render || exit 1; \
	done

tests:
	@if ! $(COMPOSE_UP); then \
		echo "ERROR: el entorno de test no ha arrancado; revisa los logs de arriba"; \
		$(DOCKER) compose -f $(COMPOSE_IT) logs --tail 40 fitcoach-ia; \
		$(COMPOSE_DOWN); \
		exit 1; \
	fi; \
	$(PYTEST) --cov=$(BASE_PACKAGE)/fitcoach --cov-fail-under=80 -o testpaths="$(UNIT_TEST_PACKAGE) $(IT_TEST_PACKAGE)"; \
	STATUS=$$?; \
	$(COMPOSE_DOWN); \
	exit $$STATUS

run:
	$(eval TARGET_IMAGE := $(IMAGE_BASE):$(version))
	@$(DOCKER) run -d --name $(CONTAINER_NAME) -p $(PORT):$(PORT) --env-file .env \
		$(if $(log_level),-e log_level=$(log_level),) $(TARGET_IMAGE)
	@echo "Aplicación corriendo en http://localhost:$(PORT)"

stop:
	@$(DOCKER) stop $(CONTAINER_NAME) || true
	@$(DOCKER) rm $(CONTAINER_NAME) || true

logs:
	@$(DOCKER) logs -f $(CONTAINER_NAME)

clean: stop clean-images

all: clean build run

# Borra unicamente la imagen de la version indicada, respetando el resto de tags
clean-image:
	@IMAGE=$$($(DOCKER) images --filter "reference=$(IMAGE_BASE):$(version)" -q); \
	if [ -z "$$IMAGE" ]; then \
		echo "No se encontro la imagen $(IMAGE_BASE):$(version). Nada que eliminar."; \
		exit 0; \
	fi; \
	echo "Eliminando $(IMAGE_BASE):$(version)..."; \
	$(DOCKER) rmi $(IMAGE_BASE):$(version)

# Borra todas las imagenes que contengan el nombre fitcoachia/fitcoach-app. Busca los IDs, elimina duplicados y borra las imagenes
clean-images:
	@IMAGES=$$($(DOCKER) images --filter "reference=$(IMAGE_BASE)" -q | sort -u); \
	if [ -z "$$IMAGES" ]; then \
		echo "No se encontraron imágenes de $(IMAGE_BASE). Nada que eliminar."; \
	else \
		echo "Eliminando imágenes de $(IMAGE_BASE)..."; \
		$(DOCKER) rmi -f $$IMAGES; \
		echo "Imágenes eliminadas correctamente."; \
	fi
