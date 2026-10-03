# Panel administrador de cuotas

La Mini App muestra «Administración» solo a usuarios autorizados por entorno.
No es un mecanismo para otorgar permisos desde el panel: la API valida cada
petición usando `initData` firmado de Telegram y la lista de administradores.

```dotenv
miniapp_admin_chat_ids=123456789,987654321
```

Son ids positivos de usuarios/chats privados, separados por comas.
Una lista vacía deshabilita el acceso administrativo para todos. Cambiar
administradores requiere recrear/reiniciar la aplicación (`make dev-app`).
No basta con ocultar controles en el frontend: usuarios no autorizados reciben
403 desde el servidor. El acceso no exige que el administrador tenga un plan.

## Configurar cuotas

El panel permite consultar consumo por usuario/chat, editar límites globales,
crear excepciones individuales y eliminarlas. La precedencia es:

1. Excepción individual guardada en PostgreSQL.
2. Configuración global guardada en PostgreSQL.
3. Valores `rate_limit_*` del entorno.

Cada configuración contiene límite de tokens, ratio blando y ventana móvil en
minutos. Se aplica en la siguiente comprobación de cuota, sin reiniciar.
«Restaurar entorno» elimina solo la configuración global, no las excepciones.
«Eliminar excepción» hace que ese usuario vuelva a heredar la configuración global.
El panel no borra `token_usage`, no reinicia consumos y no activa llamadas bloqueadas
retroactivamente. Las sesiones LLM ya autorizadas pueden terminar y superar el
umbral; no es un techo de gasto estricto ni limita la cuenta del proveedor.

El consumo y disponible orientativo se calculan en la ventana efectiva de cada
usuario, incluyendo llamadas fallidas con tokens registrados. El diario y lectura
determinista siguen disponibles con cuota agotada.
Los cambios quedan auditados con administrador, usuario objetivo, valores anterior/
nuevo y fecha. No se muestran perfiles, registros de salud ni mensajes del usuario.

## Despliegue

Mismo contenedor, puerto y Proxy Host de Nginx Proxy Manager que la Mini App.
La imagen incluye el panel; aplicar la migración Alembic al desplegar.
No se necesita otro dominio, puerto o contenedor, ni permisos nuevos en Telegram.
Ver [telegram-miniapp.md](telegram-miniapp.md) para HTTPS y configuración del proxy.
