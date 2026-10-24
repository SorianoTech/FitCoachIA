# Probar OpenRouter como modelo LLM

## Configuración de desarrollo

Configura OpenRouter como endpoint compatible con OpenAI en `.env.dev`:

```dotenv
ia_base_url=https://openrouter.ai/api/v1
ia_token=<API_KEY_DE_OPENROUTER>
ia_model=<proveedor/modelo>
ia_temperature=0.5
ia_max_tokens=512
```

El valor de `ia_model` debe incluir el proveedor, por ejemplo `openai/gpt-4o-mini`. Consulta el
catálogo de OpenRouter para seleccionar un identificador de modelo disponible para la cuenta.

No incluyas claves reales en ficheros versionados, comandos guardados ni conversaciones. Solicítalas
de forma interactiva y revoca cualquier clave expuesta.

## Listar modelos

```bash
read -rsp "API key de OpenRouter: " OPENROUTER_API_KEY; echo

curl --fail --silent --show-error \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/models

unset OPENROUTER_API_KEY
```

## Probar una inferencia

Sustituye el modelo por uno disponible para la clave:

```bash
read -rsp "API key de OpenRouter: " OPENROUTER_API_KEY; echo

curl --fail --silent --show-error \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  https://openrouter.ai/api/v1/chat/completions \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "Responde únicamente: conectado"}],
    "max_tokens": 10
  }'

unset OPENROUTER_API_KEY
```

Una respuesta con `choices[0].message.content` confirma que OpenRouter está disponible.

## Aplicar la configuración

Reinicia el entorno de desarrollo después de modificar `.env.dev`:

```bash
make dev-down
make dev-up
```
