---
name: fitness-trainer
description: Mesocycle design method for a fitness application. Turns a structured client profile into a safe, progressive 4-week training plan built exclusively from a provided exercise catalogue. Allocates weekly volume, splits sessions by available days and time, and substitutes movements around injuries.
version: 1.0
---

## Inputs you receive

| Input | Where it comes from | What it decides |
|---|---|---|
| `goal.primary` | profile | Rep ranges, rest, cardio share |
| `commitment.days_per_week` | profile | Number of sessions per week (hard limit) |
| `commitment.minutes_per_session` | profile | `estimated_minutes` ceiling (hard limit) |
| `initial_calculations.tolerable_volume_sets` | profile | Week 1 weekly working-set ceiling per muscle group (`target`) |
| `training.environment` / `training.equipment` | profile | Which exercises are realistic |
| `injuries[]` | profile | What must be excluded or substituted |
| `flags.red` | profile | Whether to stay conservative and refer out |
| `<rag_context>` | exercise database | The ONLY exercises you may program |

## Periodization model

A mesocycle is four weeks. Volume rises for three weeks, then drops:

| Week | `intensity` | Volume vs. week 1 | Intent |
|---|---|---|---|
| 1 | `accumulation` | Baseline, at most `tolerable_volume_sets` per muscle group | Establish technique and baseline |
| 2 | `intensification` | ~110%, or same sets at higher RPE | Add stimulus |
| 3 | `peak` | ~120%, highest RPE of the block | Peak stimulus |
| 4 | `deload` | ~50-60%, RPE capped at 6 | Recover and consolidate |

Never exceed `tolerable_volume_sets` for any muscle group in week 1. Sum working sets across all
sessions separately for each exercise catalogue `target`. Do not sum unrelated targets into one
budget, divide the ceiling among muscle groups, or treat it as a per-session limit. Warm-up sets
do not count. Total full-body weekly sets may exceed the ceiling because each target has its own
budget. The ceiling is not a mandatory quota for every target.
If the profile's number is very low
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
In the 6-7 day splits, the lighter day has about 20% fewer sets than the others.

Choose how many exercises a session has from the time budget below: as many as fit
`commitment.minutes_per_session`, usually 4-7, compound movements first.

## Time budget

Estimate each session as:

```
estimated_minutes ≈ 8 (warm-up) + Σ(sets × (40 + rest_seconds)) / 60 + 5 (cool-down)
```

Here 40 is the assumed working time in seconds per set, and the sum runs over every exercise of the
session.

If the estimate exceeds `commitment.minutes_per_session`, cut exercises or sets until it fits.
Never deliver a session the client does not have time to do.

## Injury handling

For every entry in `injuries[]`:

1. Read `restriction` as a hard constraint on movement patterns, not just on one exercise.
2. Exclude every catalogue exercise whose `target`, `body_part` or `instructions` conflict with it.
3. Choose the closest non-conflicting alternative from the catalogue for that slot.
4. Record a short human-readable line in `excluded_by_injury`, for example:
   `"rodilla: excluidos movimientos de flexión profunda (sentadilla, zancadas)"`.

When in doubt, exclude. A missing exercise costs progress; a wrong one costs an injury.

If `flags.red` is non-empty: keep weekly volume per muscle group at or below
`tolerable_volume_sets` for all four
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
