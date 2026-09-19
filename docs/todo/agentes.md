## Documento de Arquitectura Técnica: Sistema Multiagente de Bienestar con LangGraph

## 1. Introducción y Objetivo del Proyecto
El objetivo de este proyecto es desarrollar un sistema automatizado e inteligente para la creación de planes personalizados de fitness, nutrición y motivación. A diferencia de las automatizaciones lineales tradicionales, implementaremos un enfoque Multiagente utilizando LangGraph. Esto nos permitirá orquestar diferentes especialistas de IA que colaboran entre sí, validan mutua y cíclicamente sus propuestas, y aseguran una coherencia total en el plan final entregado al cliente antes de cualquier intervención humana.
------------------------------
## 2. ¿Por qué LangGraph y no LangChain tradicional?


* Flujos Cíclicos (Bucles de Corrección): Necesitamos que los agentes vuelvan atrás si se detectan incongruencias (ej. un plan nutricional que no cubre el gasto calórico del mesociclo). LangChain es estrictamente lineal; LangGraph nos da la capacidad de crear ciclos basados en estados.
* Estado Global Compartido (Stateful): Todos los agentes escribirán y leerán de una memoria central estructurada (TypedDict), evitando la pérdida de contexto entre traspasos de tareas.
* Control de Calidad Autónomo: El último agente actúa como supervisor antes de cerrar el flujo. Si el plan no es perfecto, se redirige de forma dinámica.


------------------------------
## 3. Arquitectura del Grafo
El sistema se compone de 4 Nodos (Agentes) y un Borde Condicional (Router) que controla el flujo lógico:

                  ┌──────────────────────┐
                  │ 1. Agente Secretario │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ 2. Agente Entrenador │◄────────────────┐
                  └──────────┬───────────┘                 │
                             │                             │
                             ▼                             │ (Si revisión = False)
                  ┌──────────────────────┐                 │
                  │3. Agente Nutricionista│                │
                  └──────────┬───────────┘                 │
                             │                             │
                             ▼                             │
                  ┌──────────────────────┐                 │
                  │4. Coach / Supervisor ├─────────────────┘
                  └──────────┬───────────┘
                             │
                             │ (Si revisión = True)
                             ▼
                          [ FIN ]

------------------------------
## 4. Definición de los Componentes## A. El Estado Global (State)
Es la estructura de datos unificada que viaja por el grafo. Todo desarrollador debe respetar estas claves:

| Clave | Tipo | Descripción |
|---|---|---|
| entrevista_raw | str | Transcripción en bruto de la entrevista inicial con el cliente. |
| perfil_cliente | dict | Datos estructurados (Objetivos, lesiones, patologías, horarios). |
| plan_entrenamiento | dict | Estructura detallada del mesociclo generado. |
| plan_nutricion | dict | Plan de alimentación y suplementación calórica correspondiente. |
| recursos_coaching | dict | Estrategia mental, enlaces a vídeos propios, bibliografía y RRSS. |
| revision_valida | bool | Flag que determina si el plan completo pasa el control de calidad. |
| errores_detectados | str | Feedback textual en caso de que se requiera una corrección en bucle. |

## B. Los Nodos (Agentes)

   1. Agente Secretario (agente_secretario)
   * Input: entrevista_raw
      * Output: perfil_cliente
      * Responsabilidad: Parsear la entrevista inicial. Debe extraer con alta precisión restricciones médicas o lesiones (ej. "condromalacia rotuliana") y objetivos principales.
   2. Agente Entrenador (agente_entrenador)
   * Input: perfil_cliente (y errores_detectados si viene de un bucle).
      * Output: plan_entrenamiento
      * Responsabilidad: Diseñar el mesociclo de entrenamiento adaptado milimétricamente a las lesiones y horarios.
   3. Agente Nutricionista (agente_nutricionista)
   * Input: perfil_cliente, plan_entrenamiento
      * Output: plan_nutricion
      * Responsabilidad: Calcular las necesidades energéticas y macronutrientes basándose estrictamente en el volumen de entrenamiento diseñado por el Agente 2.
   4. Agente Coach + Supervisor (agente_coach_supervisor)
   * Input: Todos los campos anteriores del estado.
      * Output: recursos_coaching, revision_valida, errores_detectados
      * Responsabilidad: Generar el material motivacional y de apoyo técnico. Adicionalmente, actúa como evaluador. Si detecta un desbalance (ej. dieta de 1500 kcal para un entrenamiento enfocado a hipertrofia pesada), marca revision_valida = False y detalla el motivo en errores_detectados.

## C. El Borde Condicional (Router)
Una función de enrutamiento evalúa revision_valida:

*
* Si es True -> Envía el flujo a END.
* Si es False -> Envía el flujo de vuelta a agente_entrenador aportando el contexto de los errores encontrados para su reajuste.
*

------------------------------
## 5. Próximos Pasos para el Equipo de Desarrollo

   1. Validación del Esqueleto: Probar el flujo lógico localmente con datos simulados (mocks) para asegurar que LangGraph procesa el bucle correctamente.
   2. Prompt Engineering: Diseñar y refinar los SystemPrompts de cada agente utilizando LangChain para estructurar las salidas de los LLMs obligatoriamente en formato JSON.
   3. Human-in-the-loop (Fase 2): Implementar un nodo de interrupción (interrupt_before o interrupt_after) en el Supervisor para que un profesional humano valide o edite el plan antes de consolidarlo en la base de datos.

------------------------------
Si lo consideras oportuno, dime:

* ¿Quieres que agregue una sección técnica sobre cómo persistir el estado en una base de datos (PostgreSQL/Redis) usando Checkpointers de LangGraph?
* ¿Te gustaría que redactemos la especificación exacta del formato JSON que debe escupir cada uno de los 4 agentes?
