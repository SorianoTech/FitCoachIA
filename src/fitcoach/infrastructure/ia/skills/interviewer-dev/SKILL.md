---
name: interviewer-dev
description: Short development interview for testing completion, report generation and persistence.
version: 1.0
---

## Purpose

This is a reduced interview used only in development. It must finish quickly so developers can
exercise the completed-interview path in Telegram. Do not use this skill in production.

## Flow

Ask one step per message, in this order:

1. **Identity:** What name should I use?
2. **Basics:** What are your age, weight in kg and height in cm?
3. **Goal and commitment:** Ask the user to choose between losing fat, gaining muscle mass or
   improving physical performance, and say how many days per week and minutes per session they
   can train. Ask:
   "¿Tu objetivo principal es perder grasa, ganar masa muscular o mejorar tu rendimiento físico?
   ¿Cuántos días por semana puedes entrenar y cuántos minutos por sesión?"

Use human-readable labels in `reply` and `report`, never internal enum values or field names.
Translate the user's chosen goal to the corresponding `goal.primary` enum defined in APPLICATION
OUTPUT only when constructing the structured profile; do not show those identifiers in chat.

Core data must come from the user, never from defaults: name, age, weight, height, primary goal,
days per week and minutes per session. If an answer leaves any of them out or outside the profile's
ranges, ask for it again once instead of completing. Defaults below apply only to what this reduced
interview does not ask.

After the third answer, mark the interview as `completed`. Do not ask the remaining questions from
the full skill. If an answer omits a field required by the application profile, use a clearly
conservative test value consistent with the information provided and record the limitation in the
report. Do not invent medical conditions, injuries or supplements.

For development tests, use these safe defaults only when needed:

- composition (perceived and estimated), occupation description, nutrition general pattern: a short
  non-empty placeholder such as `"not assessed (development test)"`
- goal: secondary `null`, timeframe `12` weeks, realistic expectation `true`
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
- flags: empty red and yellow lists, unless the supplied data triggers a red flag from the system
  prompt guardrails (for example BMI below 13.5 or above 45); then record it and recommend a
  qualified professional in the `report`
- initial calculations: `bmi` = kg / m²; `bmr` = 10 × kg + 6.25 × cm − 5 × age − 78 (Mifflin-St
  Jeor with the sex-neutral midpoint, since the sex is not asked here); `estimated_tdee` = `bmr` ×
  (1.2 + 0.03 × days per week). Round to integers and disclose the assumptions. For
  `tolerable_volume_sets`, use `10` as the development default WEEKLY working-set ceiling PER
  MUSCLE GROUP, not a full-body total. This is a test assumption, not a biometric calculation; disclose it in the report. Honour explicit training
  experience, recovery limitations and safety concerns instead of overriding them with defaults.

## Completion output

Follow APPLICATION OUTPUT in the system prompt for the JSON envelope and all profile fields.
Use `in_progress` until the three questions are answered, then `completed`. The `report` must be
short, in Spanish, suitable for Telegram, and explicitly say that this is a reduced
development interview when defaults were used.
