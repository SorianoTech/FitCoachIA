# Golden set del agente entrenador

Casos fijos para ajustar el `SKILL.md` y el `system_prompt.txt` del entrenador comparando
ejecuciones entre sí. Cada caso es una carpeta `cases/<caso>/` con:

- `profile.json`: un `InterviewerProfile` válido (lo que entregaría el entrevistador).
- `catalogue.json`: el catálogo que devolvió la recuperación real (embedder + pgVector) para ese
  perfil, congelado para que las ejecuciones sean repetibles.

| Caso | Qué pone a prueba |
| --- | --- |
| `beginner_gym_lose_fat` | Principiante, 3 días × 45 min, volumen bajo (9 series) |
| `intermediate_gym_gain_muscle_4d` | Split torso/pierna de 4 días, 75 min, 16 series |
| `knee_injury_home` | Lesión de rodilla (sin flexión profunda ni impacto), casa, 40 min |
| `shoulder_injury_gym_5d` | Lesión de hombro (nada por encima de la cabeza), 5 días |
| `red_flags_conservative` | Banderas rojas: plan conservador y derivación a un profesional |
| `short_sessions_outdoors_2d` | Rendimiento, exterior, solo peso corporal y bandas, 2 × 30 min |
| `advanced_performance_6d` | Avanzado, 6 días × 90 min, volumen alto (22 series) |
| `poor_sleep_mixed_3d` | Sueño pobre e historial de abandono: empezar por debajo del techo |

## Uso

```bash
# Un caso
make trainer-debug ARGS="--case-dir evals/trainer/cases/knee_injury_home"

# Regenerar los catálogos tras cambiar la recuperación o el corpus
# (requiere vector_database_url y embedder_url apuntando a servicios en marcha)
make trainer-refresh-catalogues
```

Los catálogos reflejan la recuperación del momento en que se congelaron. Si un plan es malo porque
el catálogo no ofrece buenas opciones (por ejemplo, ningún ejercicio de espalda), el problema está
en la recuperación, no en el prompt: el evaluador lo indica en la cobertura del catálogo.

Los perfiles son ficticios: no añadas aquí datos de usuarios reales.
