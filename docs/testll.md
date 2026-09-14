# Comprobar conectividad con el servidor LLM

## Comprobar el contenedor

El servidor del modelo debe estar en estado `Up` y publicar el puerto configurado:

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
```

Un estado `Exited (137)` o `Restarting (137)` indica que el proceso fue terminado con `SIGKILL`.
La causa habitual es falta de memoria. Mientras el contenedor no se mantenga en ejecución, la API
del modelo no estará disponible.

## Consultar los modelos disponibles

No escribas el token en el comando ni lo guardes en el historial de la terminal. Solicítalo de
forma interactiva:

```bash
read -rsp "Token del modelo: " MODEL_TOKEN; echo
curl --fail --silent --show-error \
  -H "Authorization: Bearer $MODEL_TOKEN" \
  http://127.0.0.1:11555/v1/models
unset MODEL_TOKEN
```

Una respuesta JSON con una lista de modelos confirma que la API OpenAI-compatible está accesible.

## Ejecutar una inferencia de prueba

Sustituye `NOMBRE_DEL_MODELO` por uno de los valores devueltos por `/v1/models`:

```bash
read -rsp "Token del modelo: " MODEL_TOKEN; echo
curl --fail --silent --show-error \
  -H "Authorization: Bearer $MODEL_TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:11555/v1/chat/completions \
  -d '{
    "model": "NOMBRE_DEL_MODELO",
    "messages": [{"role": "user", "content": "Responde únicamente: conectado"}],
    "max_tokens": 10
  }'
unset MODEL_TOKEN
```

Si la respuesta contiene un mensaje del asistente, FitCoach puede utilizar ese endpoint con:

```dotenv
ia_base_url=http://127.0.0.1:11555
ia_model=NOMBRE_DEL_MODELO
ia_token=<token-del-modelo>
```

Cuando FitCoach se ejecute en otro contenedor de la misma red Docker, usa el nombre DNS del servicio
LLM en `ia_base_url`, por ejemplo `http://fitcoach-llm:11555`, en lugar de `127.0.0.1`.
