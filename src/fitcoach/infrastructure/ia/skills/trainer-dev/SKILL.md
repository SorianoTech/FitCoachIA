---
name: trainer-dev
description: Reduced mesocycle generation for testing the plan contract, retrieval grounding and persistence.
version: 1.0
---

## Purpose

This is a reduced trainer used only in development. It must produce a valid plan quickly and
cheaply so developers can exercise the `/train` path, the exercise-id validation and the
persistence of `training_plans` without spending 4096 tokens per iteration. Do not use this skill
in production.

## Flow

Design **week 1 properly** and derive the other three from it:

`tolerable_volume_sets` is a weekly working-set ceiling PER MUSCLE GROUP (catalogue `target`),
not the total for the whole body or a daily budget. Sum sets over all sessions separately for each
target. Do not divide the ceiling among unrelated targets; total full-body sets may exceed it.
Warm-up sets do not count and the ceiling is not a mandatory quota.

1. Week 1 (`accumulation`): pick at most **3 exercises per day**, only from `<rag_context>`.
   Give every exercise an `rpe` no higher than 8. For each catalogue `target`, the sum of weekly
   sets must not exceed `initial_calculations.tolerable_volume_sets`.
2. Week 2 (`intensification`): keep the same exercises and sets; raise each `rpe` by 0.5.
3. Week 3 (`peak`): keep the same exercises and add one set to the first exercise of each day,
   unless a safety, volume or time constraint forbids it. Cap every `rpe` at 9.
4. Week 4 (`deload`): keep the safest core exercises and reduce **total weekly sets** to 50-60% of
   week 1. Cap every `rpe` at 6. Drop an exercise when keeping one set of everything would leave too
   much volume.

Keep `days_per_week` equal to the profile's `commitment.days_per_week`, and keep every day's
`estimated_minutes` under `commitment.minutes_per_session`. Check the estimate with:

```
8 + Σ(sets × (40 + rest_seconds)) / 60 + 5
```

If that estimate does not fit, remove sets or exercises before returning the plan.

## Red flags

When `flags.red` is non-empty, safety overrides the normal progression:

- Keep every week's sets per catalogue `target` at or below
  `initial_calculations.tolerable_volume_sets`.
- Never use RPE 9 or higher. Progress weeks 2-3 only with a small RPE increase capped at 8 when
  adding sets would exceed the ceiling.
- Keep week 4 at 50-60% of week 1 and RPE no higher than 6.
- State clearly in `report` that a qualified professional should clear the client before starting.

## Rules that still apply

These are not relaxed in development — they are what the tests exercise:

- Every `exercise_id` MUST come from `<rag_context>`; never invent one.
- Use the exact catalogue `name` for each id and do not repeat an id within one day.
- `weeks` has exactly 4 entries, numbered 1-4.
- Each week has exactly `days_per_week` entries, with distinct `day` values.
- Injuries in the profile are still excluded, and still recorded in `excluded_by_injury`.
- The output is still the strict JSON contract of the system prompt.

## Shortcuts allowed in development

- `progression_notes` may be a single short sentence.
- `notes` on each exercise may be omitted.
- The split may be full body every day regardless of `days_per_week`.
- `report` may be two sentences: what the plan is, and one safe next step.

## Follow-up questions

Answer in one or two sentences using the system prompt's `answer` contract. Do not regenerate the
plan in an answer turn.
