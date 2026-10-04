# Telegram Mini App: consulta y registro de entrenamiento

## Objetivo y alcance

Entregar las cuatro fases: consulta visual, registro de sesiones y series, historial
y progreso, y reutilizacion de los flujos del entrenador para sustituciones y
renovaciones. El bot conserva la conversacion, RAG, recordatorios y confirmacion.
Consultar y registrar no consume LLM.

## Fases

1. Consulta: React/TypeScript/Vite bajo `/miniapp/`, API FastAPI bajo
   `/api/miniapp`, autenticacion con `initData` firmado por Telegram, semana
   calculada por el calendario existente y selector manual. Acceso desde el
   menu del bot y desde `/train`.
2. Registro: diario independiente de `training_sessions`, que actualmente
   representa estado conversacional. Una sesion por slot semana/dia/mesociclo,
   prescripcion congelada de su version, series realizadas, carga opcional,
   repeticiones o duracion, RPE opcional y ejercicios omitidos.
   Inicio idempotente y guardado con revision optimista; sesiones finalizadas
   de solo lectura. Guardado explicito, sin almacenar datos de salud en el navegador.
3. Historial: consultas deterministas y progreso por ejercicio del catalogo.
   Diferenciar valores desconocidos de cero; no comparar automaticamente
   variantes distintas ni interpretar una carga como rendimiento equivalente.
4. Entrenador: abrir sustitucion o revision desde la Mini App y continuar en
   el chat con los controles existentes. RAG y aceptacion permanecen en el
   backend. La renovacion recibe un resumen acotado de sesiones realmente
   registradas del mismo mesociclo, incluidas versiones por sustitucion.
   Registrar todas las sesiones no confirma automaticamente el cierre del ciclo.

## Invariantes

- La identidad procede exclusivamente del usuario en `initData` validado;
  primera entrega limitada a chats privados. Nunca aceptar un `chat_id` del cliente.
- Verificar firma, timestamp, formato y propiedad de cada recurso.
  El secreto del webhook no autentica esta API.
- No enviar tokens a URLs ni logs. Servir API y frontend desde el mismo dominio HTTPS.
- Validar indices, series y valores finitos contra la prescripcion congelada.
  No editar planes desde registros; conservar historial al cambiar de version.
- Reintentos no duplican sesiones; conflictos no sobrescriben registros.
  Un fallo de guardado no se presenta como exito.
- El calendario no demuestra ejecucion, y un registro es autodeclarado.
  No inferir kilos, molestias, recuperacion ni mejoras ausentes.
- `/interview` conserva su semantica de reset: elimina tambien el diario asociado.
- No incluir datos de salud en almacenamiento local, telemetria ni analitica externa.

## Despliegue

La imagen compila el frontend en una etapa Node y copia los estaticos a la
imagen Python. Sin nuevo servicio ni dependencia Python. Migracion Alembic
aditiva para el diario. Configurar `miniapp_url` con la URL HTTPS publica
terminada en `/miniapp/`; omitirla mantiene los menus actuales.
El servidor sirve estaticos y no habilita CORS global.
El proxy del despliegue es Nginx Proxy Manager: reutilizar el Proxy Host de
la API, certificado SSL/Force SSL y destino HTTP puerto 8000. Conservar prefijos,
sin nuevo puerto, Custom Locations, autenticacion Basic ni cache del diario.
Decision confirmada: mantener frontend compilado y FastAPI en una unica imagen
y contenedor de aplicacion; no desplegar un contenedor frontend independiente.

## Progreso

Las cuatro fases estan implementadas: consulta, diario persistido, historial/
progreso e integracion con los flujos del bot y contexto de renovacion.
Validacion integral: 590 pruebas Python correctas y cobertura global 89.53%;
35 pruebas frontend y compilacion TypeScript/Vite correctas. Ruff y mypy
correctos, con exclusion del problema de formato preexistente en
docs/plan/toon-rag-optimization.md. Imagen completa construida y arrancada
con DB/stubs aislados; migracion, estaticos y rechazo 401 sin Telegram comprobados.
Pendiente comprobacion manual del WebView tras desplegar la URL HTTPS:
no se ha modificado el entorno dev ni Nginx Proxy Manager.

## Validacion

Pruebas de firma/expiracion/propiedad, schemas de registros, concurrencia y
reintentos con PostgreSQL aislado; frontend con tipos/build y pruebas de helpers.
Probar que consultas y guardado no invocan el modelo, que la renovacion
recibe resultados reales sin inventar adherencia, y que cambios siguen
requiriendo confirmacion. Suite global con cobertura minima del 80%.
El arranque real desde Telegram requiere URL HTTPS y configuracion del bot;
las pruebas con stubs no sustituyen esa comprobacion manual.
