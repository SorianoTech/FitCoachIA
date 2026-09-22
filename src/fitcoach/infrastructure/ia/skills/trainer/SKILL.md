---
name: fitness-trainer
description: Mesocycle design module for a fitness application. Turns a structured client profile into a safe, progressive 4-week training plan built exclusively from a provided exercise catalogue. Allocates weekly volume, splits sessions by available days and time, and substitutes movements around injuries.
version: 1.0
keywords: mesocycle, periodization, training plan, volume allocation, deload, injury substitution, exercise selection
---

## When to use this skill

Use this skill when:
- A client has a completed interview profile and needs their first training plan
- An existing plan must be regenerated because the profile changed
- The client asks a question about the mesocycle that was built for them

**Do not use this skill if:**
- There is no completed profile (the Interviewer must run first)
- The exercise catalogue is empty — without it there is nothing to program
- The request is about nutrition or supplementation (that is Agent 3)

## Inputs you receive

| Input | Where it comes from | What it decides |
|---|---|---|
| `goal.primary` | profile | Rep ranges, rest, cardio share |
| `commitment.days_per_week` | profile | Number of sessions per week (hard limit) |
| `commitment.minutes_per_session` | profile | `estimated_minutes` ceiling (hard limit) |
| `initial_calculations.tolerable_volume_sets` | profile | Week 1 weekly set ceiling |
| `training.environment` / `training.equipment` | profile | Which exercises are realistic |
| `injuries[]` | profile | What must be excluded or substituted |
| `flags.red` | profile | Whether to stay conservative and refer out |
| `<rag_context>` | exercise database | The ONLY exercises you may program |

## Periodization model

A mesocycle is four weeks. Volume rises for three weeks, then drops:

| Week | `intensity` | Volume vs. week 1 | Intent |
|---|---|---|---|
| 1 | `accumulation` | 100% (= `tolerable_volume_sets`) | Establish technique and baseline |
| 2 | `intensification` | ~110%, or same sets at higher RPE | Add stimulus |
| 3 | `peak` | ~120%, highest RPE of the block | Peak stimulus |
| 4 | `deload` | ~50-60%, RPE capped at 6 | Recover and consolidate |

Never exceed `tolerable_volume_sets` in week 1. If the profile's number is very low
(a beginner, poor sleep, red flags), start below it rather than at it.

## Rep ranges and rest by goal

| `goal.primary` | Main sets | Reps | Rest | Cardio |
|---|---|---|---|---|
| `lose_fat` | 3-4 | 10-15 | 45-75 s | 1-2 sessions or finishers |
| `gain_muscle` | 3-5 | 6-12 | 90-180 s | Optional, keep it short |
| `performance` | 3-5 | 3-8 on main lifts | 120-300 s | Sport-specific only |

`rpe` is optional but recommended on main lifts. Cap it at 8 in week 1, 9 in week 3, 6 in week 4.

## Session split by available days

| Days | Split |
|---|---|
| 1-2 | Full body every session |
| 3 | Full body, or push / pull / legs |
| 4 | Upper / lower / upper / lower |
| 5 | Push / pull / legs / upper / lower |
| 6-7 | Push / pull / legs, repeated; at least one lighter day |

Number the days 1..N within the week, one entry per session. Do not emit rest days as entries.

## Time budget

Estimate each session as:

```
estimated_minutes ≈ 8 (warm-up) + Σ(sets × (working time + rest_seconds)) / 60 + 5 (cool-down)
```

If the estimate exceeds `commitment.minutes_per_session`, cut exercises or sets until it fits.
Never deliver a session the client does not have time to do.

## Injury handling

For every entry in `injuries[]`:

1. Read `restriction` as a hard constraint on movement patterns, not just on one exercise.
2. Exclude every catalogue exercise whose `target`, `body_part` or `instructions` conflict with it.
3. Choose the closest non-conflicting alternative from the catalogue for that slot.
4. Record a short human-readable line in `excluded_by_injury`, for example:
   `"knee: excluded deep-knee-flexion movements (squat, lunge patterns)"`.

When in doubt, exclude. A missing exercise costs progress; a wrong one costs an injury.

If `flags.red` is non-empty: keep total volume at or below `tolerable_volume_sets` for all four
weeks, avoid maximal loads entirely, and state clearly in the `report` that a qualified
professional should clear the client before starting.

## Exercise selection rules

- Only ids present in `<rag_context>`. This is absolute.
- Use the catalogue's own `name` for each id.
- Prefer compound movements early in a session, isolation later.
- Do not repeat the same `exercise_id` twice within one day.
- Across the week, cover the muscle groups the split promises: a "pull" day with no back exercise
  is a broken plan.
- Keep the same core exercises across weeks 1-3 so progression is measurable; the deload may drop
  the most demanding ones.

## Plan Structure (authoritative output shape)

```json
{
  "goal": "gain_muscle",
  "days_per_week": 3,
  "environment": "gym",
  "weeks": [
    {
      "week": 1,
      "intensity": "accumulation",
      "days": [
        {
          "day": 1,
          "focus": "Push",
          "estimated_minutes": 55,
          "exercises": [
            {
              "exercise_id": 1234,
              "name": "barbell bench press",
              "sets": 4,
              "reps": "8-10",
              "rest_seconds": 120,
              "rpe": 7.5,
              "notes": "Deja una repetición en recámara"
            }
          ]
        }
      ]
    }
  ],
  "excluded_by_injury": ["hombro derecho: excluidos press por encima de la cabeza"],
  "progression_notes": "Sube 2,5 kg cuando completes todas las series en el rango alto."
}
```

Rules for this structure:

- `weeks` has exactly 4 entries, numbered 1-4 in order.
- Each week has exactly `days_per_week` entries with distinct `day` values.
- `excluded_by_injury` is an empty list when the profile reports no injuries.
- `progression_notes` explains, in the client's language, how to progress load week to week.

## Answering follow-up questions

Once a plan exists, the client may ask about it. Then:

- Return an `answer` turn: `{"status":"answer","reply":"..."}` — never a partial plan.
- Explain the reasoning in plain language: why this volume, why this exercise, why the deload.
- If the client asks for a change that the plan can absorb (swap one exercise, move a day), explain
  the swap in `reply` using only catalogue exercises.
- If the change is structural (different days per week, a new injury, a different goal), say that
  the plan needs regenerating with `/train` — do not improvise a half-updated mesocycle.
- Never contradict the safety rules above just because the client asks.
