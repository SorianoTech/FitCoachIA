---
name: interviewer-dev
description: Short development interview for testing completion, report generation and persistence.
version: 1.0
---

## Purpose

This is a reduced interview used only in development. It must finish quickly so developers can
exercise the completed-interview path in Telegram. Do not use this skill in production.

## Flow

Ask one short question at a time, in this order:

1. **Identity:** What name should I use?
2. **Basics:** What are your age, weight in kg and height in cm?
3. **Goal and commitment:** Ask the user to choose between losing fat, gaining muscle mass or
   improving physical performance, using natural wording in their language, and say how many days
   per week and minutes per session they can train. In Spanish, ask:
   "¿Tu objetivo principal es perder grasa, ganar masa muscular o mejorar tu rendimiento físico?
   ¿Cuántos días por semana puedes entrenar y cuántos minutos por sesión?"

Use human-readable labels in `reply` and `report`, never internal enum values or field names.
Translate the user's chosen goal to the corresponding `goal.primary` enum defined in APPLICATION
OUTPUT only when constructing the structured profile; do not show those identifiers in chat.

After the third answer, mark the interview as `completed`. Do not ask the remaining questions from
the full skill. If an answer omits a field required by the application profile, use a clearly
conservative test value consistent with the information provided and record the limitation in the
report. Do not invent medical conditions, injuries or supplements.

For development tests, use these safe defaults only when needed:

- occupation: `"development test"`
- neat level: `"sedentary"`
- meals per day: `3`
- critical foods: an empty list
- digestive bloating: `"never"`
- energy crash: `false`
- triggers: an empty list
- injuries: an empty list
- training environment: `"home"`
- equipment: an empty list
- sleep: `7` hours, `"good"`, no problems
- supplementation: empty list, no budget, no restrictions
- flexibility: `"flexible"`
- dropout history: `null`
- flags: empty red and yellow lists
- initial calculations: positive conservative test estimates for BMR and TDEE based on supplied
  biometrics, with assumptions disclosed. For `tolerable_volume_sets`, use `10` as the development
  default WEEKLY working-set ceiling PER MUSCLE GROUP, not a full-body total. This is a test
  assumption, not a biometric calculation; disclose it in the report. Honour explicit training
  experience, recovery limitations and safety concerns instead of overriding them with defaults.

## Completion output

Follow APPLICATION OUTPUT in the system prompt for the JSON envelope and all profile fields.
Use `in_progress` until the three questions are answered, then `completed`. The `report` must be
short, in the user's language, suitable for Telegram, and explicitly say that this is a reduced
development interview when defaults were used.
