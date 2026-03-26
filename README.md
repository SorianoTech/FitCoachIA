# FitCoach IA - Entrenador Personal Inteligente (TFM)

## 📝 Descripción del Proyecto
**FitCoach IA** es una solución integral de salud y bienestar desarrollada como Trabajo de Fin de Máster (TFM) dentro del **Proyecto Júpiter** . La plataforma utiliza un ecosistema de **IA Generativa** para democratizar el acceso a planes de entrenamiento y nutrición altamente personalizados, basándose en el análisis de datos individuales y hábitos del usuario.

El sistema es capaz de transformar una entrevista inicial en un **Plan Personalizado de 4 semanas** (mesociclo) que abarca entrenamiento, alimentación, suplementación y motivación.

## Arquitectura Multi-Agente (IA Generativa)
El núcleo de FitCoach IA se basa en LLMs con prompts específicos para orquestar cuatro agentes especializados:

*   **Agente 1 (Secretario):** Transcribe entrevistas y genera informes estructurados del cliente.
*   **Agente 2 (Entrenador):** Diseña planes de entrenamiento optimizados en mesociclos.
*   **Agente 3 (Nutricionista):** Elabora planes de alimentación y suplementación a medida.
*   **Agente 4 (Coaching):** Proporciona soporte motivacional y recursos multimedia personalizados (bibliografía, vídeos, RRSS).

## Stack Tecnológico y Requisitos Técnicos
Este proyecto cumple con los estándares de desarrollo profesional exigidos en el máster:

### Inteligencia Artificial y Datos
- **LLMs:** Uso de APIs de modelos fundacionales (OpenAI/Anthropic) o modelos open-source locales.
- **Bases de Datos Vectoriales:** Implementación obligatoria para la recuperación de recomendaciones semánticas y gestión de conocimientos.
- **Machine Learning:** Redes neuronales para optimización de rutinas basadas en datos históricos de usuarios.

### DevOps e Infraestructura
- **Contenerización:** Todos los agentes y servicios están **dockerizados** para garantizar la portabilidad.
- **CI/CD:** Pipelines automatizados para pruebas unitarias/integradas y despliegue continuo.
- **Cloud:** Despliegue en la nube utilizando **AWS (EC2 y S3)**.
- **Monitorización:** Sistema de logging integrado para trazabilidad de datos y rendimiento del sistema.

### Interfaces de Usuario
- **Web Panel:** Interfaz visual para que el usuario consulte sus datos, rutinas y nutrición.
- **Chatbot (Telegram):** Canal de comunicación directo para actualizar progresos e interactuar con el entrenador en tiempo real.

## Instalación y Despliegue
Instrucciones para poner en marcha el sistema utilizando los scripts de despliegue incluidos:

```bash
# Clonar el repositorio
git clone https://github.com/usuario/proyecto-jupiter.git

# Ejecutar despliegue con Docker
cd docker
bash deploy.sh
```

## Pruebas
Para ejecutar las pruebas unitarias e integradas:

```
pytest tests/
```

## Licencia y Cita

Este proyecto está bajo la licencia **Creative Commons Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)**. 

Si utilizas este trabajo en una investigación académica o proyecto, por favor cítalo como:
> [Apellidos, N. de los autores]. (Año). [Título del TFM]. Repositorio de GitHub. [Enlace al repo].
