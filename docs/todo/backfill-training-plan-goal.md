# Alinear `training_plans.goal` con el JSON del plan (Alembic)

La columna `goal` copia `plan->>'goal'` para que Grafana y las encuestas no tengan que analizar el
JSON. La rellena la migración de datos
[`d9a1b3c5e7f2`](../../alembic/versions/d9a1b3c5e7f2_backfill_training_plan_goal.py):

```sql
UPDATE training_plans SET goal = plan->>'goal' WHERE goal IS NULL;
```

Solo toca filas con `goal` nulo, así que es idempotente.

## Aplicarla

Se aplica sola al levantar la app: el ENTRYPOINT del contenedor ejecuta `alembic upgrade head` antes
de arrancar la API. A mano, con la base levantada:

```bash
alembic upgrade head
```

## Volver a ejecutarla

Alembic ejecuta cada migración una sola vez. Si hay planes creados con `goal = NULL` después de
migrar (pasa en dev hasta que el código guarde `goal=` al crear un plan, paso 3 de las encuestas),
se repite bajando y subiendo solo la revisión de datos:

```bash
alembic downgrade c2d8e4f6a1b3
alembic upgrade head
```

Es seguro: el `downgrade()` de `d9a1b3c5e7f2` no hace nada, de modo que la columna y sus datos se
conservan y la subida vuelve a rellenar los nulos. **No bajar más allá de `c2d8e4f6a1b3`**: esa
revisión borra la columna `goal` y la tabla `training_evaluation`.

## Verificar

Debe devolver 0:

```sql
SELECT count(*) AS desalineados
FROM training_plans
WHERE goal IS DISTINCT FROM plan->>'goal';
```

Si no devuelve 0, localizar los planes afectados:

```sql
SELECT id, chat_id, version, goal, plan->>'goal' AS goal_json
FROM training_plans
WHERE goal IS DISTINCT FROM plan->>'goal';
```

## Cuándo se puede borrar este documento

Cuando el paso 3 esté desplegado en todos los entornos y la verificación devuelva 0 en cada uno.
