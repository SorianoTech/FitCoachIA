# Telegram Mini App

La Mini App vive en `/miniapp/` y utiliza la API `/api/miniapp` del mismo servidor.
No requiere un servicio adicional ni cuenta aparte. El bot sigue generando planes,
gestionando RAG, revisiones, confirmaciones y avisos.

## Habilitarla

En el entorno del bot, configurar:

```dotenv
miniapp_url=https://api.tudominio.com/miniapp/
miniapp_auth_max_age_seconds=86400
```

La URL debe apuntar al mismo origen HTTPS que sirve la API, sin query ni fragmento.
Reconstruir y reiniciar la aplicación (`make dev-app` en desarrollo con PostgreSQL
y embedder ya activos). La imagen compila el frontend y aplica las migraciones
Alembic al arrancar. No recrear ni borrar el volumen de PostgreSQL.
El arranque registra el botón de menú y `/train` incorpora «Abrir entrenamiento».
Sin `miniapp_url` se mantienen los accesos textuales; el menú del bot vuelve a comandos.
En BotFather puede configurarse adicionalmente como Main Mini App con la misma URL.

### Nginx Proxy Manager

Usar el mismo **Proxy Host** que ya publica el webhook; no crear otro puerto
ni otro servicio. En desarrollo, si Nginx Proxy Manager comparte `proxy-network`,
el destino es `http://fitcoach-ia-dev:8000` (nombre de servicio de Compose).
En otros entornos, usar el nombre del servicio API correspondiente.
Si el proxy está en otro servidor, usar la dirección y puerto publicados de la
API, limitando su acceso al proxy.

En el Proxy Host:

- **Domain Names:** el dominio público de la API.
- **Scheme:** `http` hacia el contenedor; **Forward Port:** `8000`.
- **SSL:** certificado válido y **Force SSL** habilitado.
- Mantener el paso de `/webhook/response`, `/miniapp/` y `/api/miniapp/`
  sin reescribir ni eliminar prefijos. No hacen falta Custom Locations.
- No activar caché para `/api/miniapp/`. Evitar Access Lists con autenticación
  adicional en estas rutas: Telegram no aporta credenciales HTTP Basic.

Configurar `miniapp_url=https://DOMINIO/miniapp/` con ese mismo dominio.
No aplicar políticas `X-Frame-Options: DENY` o `frame-ancestors 'none'` a la
interfaz: pueden bloquear Telegram Web. No se necesitan WebSockets para esta
entrega, ni un proxy separado para Vite: se sirven archivos compilados.

## Uso

- Seleccionar semana y sesión; la semana inicial se calcula por el calendario UTC
  del mesociclo, no por entrenamientos detectados. Sin fecha, elegir manualmente.
- Iniciar o reanudar la sesión. La prescripción conserva la versión original aunque
  posteriormente se cambien ejercicios.
- Registrar repeticiones o duración, carga opcional y RPE opcional por serie.
  Omitir explícitamente ejercicios no realizados; no registrar ceros como desconocidos.
- Guardar y comprobar el estado de guardado. El temporizador de descanso es local:
  no garantiza avisos con Telegram cerrado.
- Finalizar cuando los ejercicios estén completados u omitidos; el registro final
  es de solo lectura. No hay edición retroactiva en esta entrega.
- Consultar historial y progreso por ejercicio. Los totales describen registros,
  no prueban por sí solos mejora ni equivalencia entre ejercicios.
- «Cambiar un ejercicio» y «Revisar mesociclo» envían los controles al chat.
  La Mini App no activa cambios: la confirmación sigue siendo obligatoria.

Una sesión por slot semana/día/mesociclo: se reanuda el registro existente, no se
crean intentos adicionales. El diario no soporta aún sesiones libres o entrenamientos
repetidos del mismo slot. No se asignan días de la semana automáticamente.

## API y seguridad

Todas las peticiones requieren `X-Telegram-Init-Data` con el `initData` original
del SDK de Telegram. El backend verifica HMAC, antigüedad y usuario; nunca usa
`initDataUnsafe` como autorización ni acepta `chat_id` del cliente. Abrir la URL
fuera de Telegram no permite acceder a registros. Esta entrega es para chats privados.
La caducidad obliga a reabrir desde el bot; el token del bot nunca llega al navegador.

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/miniapp/bootstrap` | Plan vigente, ciclo y semana de calendario |
| GET | `/api/miniapp/sessions` | Historial reciente, acotado |
| POST | `/api/miniapp/sessions` | Inicio/reanudación idempotente por UUID |
| GET | `/api/miniapp/sessions/{id}` | Detalle propio y prescripción congelada |
| PATCH | `/api/miniapp/sessions/{id}` | Guardado con revisión optimista o finalización |
| GET | `/api/miniapp/progress` | Observaciones por ejercicio sin LLM |
| POST | `/api/miniapp/actions` | Continuar cambio o revisión en el bot |

Un conflicto `409` requiere recargar, no sobrescribe cambios. Un recurso ajeno
responde `404`. Las respuestas de la API llevan `Cache-Control: no-store`;
el frontend no guarda registros ni credenciales en `localStorage`.
Los datos son autodeclarados y sensibles: no enviarlos a analítica externa.
`/interview` reinicia el perfil y elimina planes y registros asociados; no usarlo
para una actualización pequeña del perfil.

La renovación recibe un resumen del diario del mesociclo anterior, a través de
`recorded_performance`, separado de `prescribed_summary`. No modifica la fecha del
ciclo ni confirma automáticamente su cierre, ni interpreta falta de registros como
sesiones no realizadas.

## Desarrollo

Requiere Node 22+ además del entorno Python:

```bash
cd frontend
npm ci
npm test
npm run build
```

FastAPI sirve `frontend/dist` al ejecutarse desde el repositorio; reiniciar el
servidor tras la primera compilación. La imagen usa una etapa Node separada y
solo copia los estáticos: Node no queda en producción.
La apertura real, teclado y navegación deben comprobarse también en Telegram
móvil/escritorio con la URL HTTPS desplegada; las pruebas locales no verifican
el comportamiento de todos los WebViews.
