---
name: fitness-interviewer-dev
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
3. **Goal and commitment:** Choose a primary goal (`lose_fat`, `gain_muscle` or `performance`) and
   say how many days per week and minutes per session you can train.

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
- initial calculations: positive conservative test values derived from the supplied biometrics

## Completion output

Follow the application JSON contract exactly:

```json
{"status":"in_progress","reply":"..."}
```

Use this shape until the three questions are answered. Then return:

```json
{"status":"completed","reply":"...","report":"...","profile":{...}}
```

The `profile` must contain every field required by the `InterviewerProfile` schema, including
`user`, `biometrics`, `goal`, `activity`, `nutrition`, `digestive_energy`, `injuries`, `training`,
`sleep`, `supplementation`, `commitment`, `flags` and `initial_calculations`. The `report` must be
short, in the user's language, suitable for Telegram, and explicitly say that this is a reduced
development interview when defaults were used.
