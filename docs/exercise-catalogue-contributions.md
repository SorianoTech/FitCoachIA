# Contribuciones al catálogo de ejercicios

FitCoachIA permite que los usuarios propongan ejercicios desde Telegram para ampliar el catálogo
global utilizado por el RAG. Una propuesta nunca se publica directamente desde el LLM: pasa por
validación estructural, detección de duplicados, confirmación del usuario y moderación humana.

El objetivo es incorporar ejercicios útiles sin permitir que descripciones incompletas, movimientos
inventados o contenido malicioso degraden los planes y las alternativas ofrecidas por el
entrenador.

## Flujo completo

1. El usuario inicia el alta con `/add_exercise` o con una frase explícita como
   «Quiero añadir un ejercicio de espalda».
2. `ExerciseCuratorChain` utiliza el modelo configurado para convertir la descripción en una
   propuesta estructurada.
3. Si falta información, el curator hace una sola pregunta concreta. El borrador queda persistido
   y puede continuar en el siguiente mensaje, aunque la aplicación se reinicie.
4. El backend valida equipamiento, target anatómico, longitudes, instrucciones y estructura.
5. Se genera un embedding con el mismo servicio y dimensiones que utiliza el catálogo.
6. `ExerciseDuplicateDetector` compara la propuesta con los ejercicios existentes y marca posibles
   duplicados.
7. El usuario revisa la previsualización y pulsa **Confirmar** o **Cancelar**. También puede
   responder `confirmar`, explicar una corrección o escribir `cancelar`.
8. Una propuesta confirmada pasa a estado `pending`; todavía no es visible para el RAG.
9. Un moderador la aprueba o rechaza desde Telegram.
10. La aprobación genera el embedding definitivo, publica el ejercicio en pgVector y cambia la
    solicitud a `approved`.
11. El ejercicio queda disponible inmediatamente para generaciones de planes y búsquedas de
    alternativas que cumplan sus filtros de target y equipamiento.

## Comandos

### Usuario

| Comando o respuesta | Acción |
|---|---|
| `/add_exercise` | Inicia una conversación guiada |
| `/add_exercise DESCRIPCIÓN` | Genera directamente una propuesta |
| Botón **Confirmar** | Envía el borrador completo a moderación |
| Botón **Cancelar** | Descarta el borrador |
| `confirmar` | Envía el borrador completo a moderación |
| `cancelar` | Descarta el borrador |

La detección en lenguaje natural exige una intención explícita de añadir, registrar o crear un
ejercicio. Frases casuales como «me gusta el remo» continúan por el flujo conversacional normal y
no abren una propuesta.

Los botones inline incluyen el ID de la propuesta. Si el usuario pulsa un botón antiguo después de
cancelar, confirmar o sustituir el borrador, el backend rechaza la acción sin modificar la
propuesta activa. En grupos se mantiene la respuesta por texto para evitar que otro miembro pulse
los controles del autor.

### Moderador

| Comando | Acción |
|---|---|
| `/review_exercises` | Lista hasta 20 propuestas pendientes |
| `/approve_exercise ID` | Publica la propuesta en pgVector |
| `/reject_exercise ID MOTIVO` | Rechaza y notifica el motivo al usuario |

Los comandos administrativos no aparecen en el menú general. La autorización usa el ID numérico
del usuario de Telegram, no su nombre de usuario.

## Propuesta estructurada

El curator produce los campos canónicos que consume el catálogo:

- `name`
- `category`
- `body_part`
- `equipment`
- `target`
- `secondary_muscles`
- `instructions_en`
- `quality`

`equipment` debe pertenecer al vocabulario de `domain/exercise_catalogue.py`. `target` debe
pertenecer a uno de los targets anatómicos conocidos; el grupo muscular se deriva de ese target y
no se acepta como una clasificación libre del modelo.

Las instrucciones se guardan en inglés para mantener la coherencia con el corpus actual. El texto
conversacional que recibe el usuario sigue su idioma, con español como valor predeterminado.

## Evaluación de calidad mediante IA

La misma llamada que genera la propuesta añade una evaluación para facilitar la moderación:

```json
{
  "validity": "valid",
  "confidence": 0.91,
  "rationale": "It is a coherent loaded horizontal pulling movement.",
  "safety_notes": ["Secure the backpack before starting."]
}
```

`validity` puede ser:

- `valid`: movimiento reconocible y biomecánicamente coherente.
- `uncertain`: podría ser válido, pero la descripción o la evidencia son insuficientes.
- `invalid`: movimiento incoherente, inventado o no utilizable como ejercicio seguro.

Esta valoración es una ayuda, no una autoridad. No aprueba ni rechaza automáticamente y el
moderador conserva siempre la decisión final. La puntuación de confianza tampoco representa una
probabilidad clínica ni sustituye la revisión de seguridad.

El curator devuelve `rejected` sin crear una propuesta publicable cuando detecta contenido
peligroso, autolesivo, médico, sexual o ajeno al ejercicio físico.

## Estados y persistencia

Las solicitudes viven en `exercise_submissions`, dentro de la base PostgreSQL principal:

| Estado | Significado |
|---|---|
| `draft` | Conversación abierta; puede estar esperando una aclaración |
| `pending` | Confirmada por el usuario y pendiente de moderación |
| `approved` | Publicada correctamente en pgVector |
| `rejected` | Rechazada por un moderador |
| `cancelled` | Cancelada por el usuario o por una respuesta no publicable |

La fila conserva:

- ID del chat y thread de Telegram.
- Descripción original y aclaraciones.
- Propuesta estructurada.
- Modelo del curator que la produjo.
- Posible ejercicio duplicado.
- Moderador, motivo y fecha de revisión.
- ID definitivo del ejercicio publicado.

Solo puede existir un borrador abierto por chat. Pueden existir varias solicitudes pendientes o
históricas del mismo usuario.

## Separación entre PostgreSQL y pgVector

Las propuestas y su auditoría pertenecen a PostgreSQL. El catálogo RAG continúa en una base
pgVector separada:

```text
Telegram
   │
   ▼
ExerciseSubmissionService
   │
   ├── PostgreSQL: exercise_submissions
   │
   └── moderación aprobada
           │
           ▼
       Embedder
           │
           ▼
PgVectorExercisePublisher
   │
   ├── exercises
   └── exercise_publications
```

La aplicación recupera ejercicios con `fitcoach_ro`, un rol de solo lectura. La publicación utiliza
`fitcoach_writer`, que solo puede:

- Consultar IDs necesarios para la publicación.
- Utilizar `exercises_id_seq`.
- Insertar columnas de ejercicios.
- Leer e insertar el enlace de idempotencia en `exercise_publications`.

No puede borrar ejercicios, modificar el corpus inicial ni administrar la base de datos.

`exercise_publications` relaciona cada `submission_id` con un único `exercise_id`. Si pgVector
confirma la inserción pero falla la actualización de PostgreSQL, un nuevo intento recupera el mismo
ejercicio en lugar de crear otro.

## Configuración

### Aplicación

Variables de `/etc/fitcoachia/prod/.env.prod` o del fichero correspondiente al entorno:

```env
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,train:Tu plan de entrenamiento,add_exercise:Propón un ejercicio,doubts:Resuelve dudas,progress:Tu progreso

bot_telegram_exercise_admin_ids=123456789,987654321

ia_exercise_curator_model=gpt-5.4-mini
ia_exercise_curator_temperature=0.1
ia_exercise_curator_max_tokens=1200
ia_exercise_curator_timeout=30
ia_exercise_duplicate_similarity_threshold=0.92

vector_database_writer_url=postgresql+asyncpg://fitcoach_writer:CONTRASEÑA@pgvector-prod:5432/fitcoach
```

El modelo del curator reutiliza `ia_base_url` e `ia_token`; solo cambia el identificador, la
temperatura y sus límites. El proveedor OpenAI-compatible configurado debe admitir el modelo y
structured outputs mediante JSON Schema.

Si la contraseña del writer contiene caracteres reservados, debe codificarse para URL.

### pgVector

El entorno de pgVector necesita:

```env
VECTOR_DB_WRITER_PASSWORD=CONTRASEÑA
```

La contraseña debe coincidir con la utilizada en `vector_database_writer_url`.

## Despliegue

La aplicación ejecuta `alembic upgrade head` al arrancar. Esto crea
`exercise_submissions` mediante las revisiones:

- `b6e4f2a1c9d8`
- `c7a9e2d4f6b1`

pgVector no está gestionado por Alembic. En instalaciones con un volumen existente, los scripts de
`docker-entrypoint-initdb.d` no vuelven a ejecutarse y debe aplicarse manualmente:

```bash
docker exec -i pgvector-prod \
  psql -v ON_ERROR_STOP=1 -U fitcoach -d fitcoach \
  < infra/vector-db/ddl/003_2026-10-04_exercise-writer.sql
```

El DDL es repetible: crea la tabla si falta, ajusta la secuencia después del corpus inicial, crea o
actualiza el rol y reaplica sus permisos.

Después se despliega la aplicación:

```bash
make build version=VERSION
make prod-up VERSION=VERSION
```

No se debe eliminar el volumen de pgVector durante esta actualización.

## Verificación operativa

Comprueba la migración principal:

```bash
docker exec fitcoach-postgres \
  psql -U fitcoach -d fitcoach \
  -c "SELECT version_num FROM alembic_version;"
```

Comprueba la infraestructura de publicación:

```bash
docker exec pgvector-prod \
  psql -U fitcoach -d fitcoach \
  -c "\d exercise_publications"

docker exec pgvector-prod \
  psql -U fitcoach -d fitcoach \
  -c "\du fitcoach_writer"
```

Después realiza el flujo desde Telegram, aprueba la solicitud y verifica:

```bash
docker exec pgvector-prod \
  psql -U fitcoach -d fitcoach \
  -c "SELECT p.submission_id, e.id, e.name, e.target
      FROM exercise_publications p
      JOIN exercises e ON e.id = p.exercise_id
      ORDER BY p.created_at DESC
      LIMIT 10;"
```

## Pruebas

Las pruebas unitarias cubren:

- Salida estructurada y modelo configurable.
- Validación de catálogo.
- Evaluación de calidad.
- Detección de duplicados.
- Conversación guiada.
- Permisos de moderación.
- Publicación idempotente.

La integración `tests/it/test_exercise_moderation.py` crea una solicitud pendiente, la aprueba por
el webhook y comprueba el estado en PostgreSQL y el ejercicio con embedding en pgVector.

Ejecuta todo el entorno:

```bash
make tests
```

La cobertura global debe mantenerse por encima del 80%.

## Fallos y recuperación

- **El curator no responde:** la propuesta no cambia de estado y el usuario recibe el mensaje seguro
  correspondiente al proveedor.
- **El embedder falla:** no se publica ni se marca la solicitud como aprobada.
- **pgVector no tiene writer configurado:** la revisión puede consultarse, pero la aprobación
  responde que la publicación no está disponible.
- **Fallo después de insertar en pgVector:** repetir la aprobación reutiliza el enlace de
  `exercise_publications`.
- **Posible duplicado:** se muestra al usuario y al moderador, pero no se decide automáticamente.
- **Rollback de aplicación:** las tablas nuevas son compatibles con versiones anteriores, que las
  ignoran. No se recomienda borrar propuestas ni ejercicios publicados durante un rollback.
