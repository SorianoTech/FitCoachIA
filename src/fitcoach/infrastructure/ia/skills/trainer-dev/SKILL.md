---
name: fitness-trainer-dev
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

1. Week 1 (`accumulation`): pick at most **3 exercises per day**, only from `<rag_context>`.
2. Week 2 (`intensification`): the same exercises and sets, `rpe` raised by 0.5.
3. Week 3 (`peak`): the same exercises, one extra set on the first exercise of each day.
4. Week 4 (`deload`): the same exercises, half the sets (minimum 1), `rpe` capped at 6.

Keep `days_per_week` equal to the profile's `commitment.days_per_week`, and keep every day's
`estimated_minutes` under `commitment.minutes_per_session`.

## Rules that still apply

These are not relaxed in development — they are what the tests exercise:

- Every `exercise_id` MUST come from `<rag_context>`; never invent one.
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

Answer in one or two sentences, with `{"status":"answer","reply":"..."}`. Do not regenerate the
plan in an answer turn.
