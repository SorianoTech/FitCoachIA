# Bots de Telegram por entorno

## Usar un bot para cada entorno

Desarrollo y producción deben usar bots de Telegram diferentes. Cada bot tiene un token propio y
Telegram solo permite un webhook activo por bot. Compartir un token puede hacer que las pruebas de
desarrollo desvíen actualizaciones destinadas a producción.

| Entorno | Bot | Configuración | Webhook |
|---|---|---|---|
| Desarrollo | Bot de pruebas | `.env.dev` | URL temporal o túnel HTTPS de desarrollo |
| Producción | Bot público | `.env.prod` o variables del servidor | Dominio HTTPS público detrás del proxy |

## Configurar variables

La aplicación carga `.env.<APP_ENV>` antes de `.env`. Los Compose asignan `APP_ENV=dev` al entorno
de desarrollo y `APP_ENV=prod` al de producción.

En `.env.dev`, define el token y URL del bot de pruebas:

```dotenv
bot_telegram_url=https://api.telegram.org/bot
bot_telegram_token=<token-del-bot-de-desarrollo>
bot_telegram_commands=start:Inicia FitCoach,interview:Entrevista,doubts:Resuelve dudas,progress:Tu progreso
```

En producción, define las mismas variables con el token del bot público mediante `.env.prod` o
variables de entorno gestionadas por el servidor. No incluyas tokens reales en archivos
versionados.

## Registrar cada webhook

Después de iniciar cada entorno, registra su webhook usando el token del bot correspondiente:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL_PUBLICA>/webhook/response"
```

El webhook debe usar HTTPS. El de desarrollo puede usar un túnel temporal; producción debe usar su
dominio público configurado en Nginx Proxy Manager.

Comprueba el webhook actual con:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

## Verificación

1. Envía `/start` al bot de desarrollo y confirma que responde el contenedor `dev-fitcoach-ia`.
2. Envía `/start` al bot público y confirma que responde `fitcoach-ia`.
3. Comprueba que las conversaciones se guardan en las bases de datos separadas de cada entorno.
