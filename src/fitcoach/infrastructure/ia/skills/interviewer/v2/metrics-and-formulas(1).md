# Metrics & Formulas Reference

This file contains all calculation formulas, scoring rubrics, and reference ranges
used in the Client Profile. Load this file when populating biometric, metabolic,
or scoring fields.

---

## 1. Basal Metabolic Rate (BMR)

### Mifflin-St Jeor (preferred — most accurate for general population)

```
Male:   BMR = (10 × weight_kg) + (6.25 × height_cm) − (5 × age) + 5
Female: BMR = (10 × weight_kg) + (6.25 × height_cm) − (5 × age) − 161
```

**Example — Male, 30 years, 80 kg, 178 cm:**
BMR = (10×80) + (6.25×178) − (5×30) + 5 = 800 + 1112.5 − 150 + 5 = **1,767.5 kcal**

---

### Revised Harris-Benedict (use when client has reliable lean mass estimate)

```
Male:   BMR = 88.362 + (13.397 × weight_kg) + (4.799 × height_cm) − (5.677 × age)
Female: BMR = 447.593 + (9.247 × weight_kg) + (3.098 × height_cm) − (4.330 × age)
```

---

### Katch-McArdle (use only if body fat % is reliably known — best for athletes)

```
BMR = 370 + (21.6 × lean_body_mass_kg)
Lean body mass = weight_kg × (1 − body_fat_decimal)
```

**Example — 80 kg, 15% body fat:**
LBM = 80 × 0.85 = 68 kg → BMR = 370 + (21.6 × 68) = 370 + 1,469 = **1,839 kcal**

> **Formula selection rule:**
> - General population (no BF% data): Mifflin-St Jeor
> - If body fat % is known and reliable (DEXA, calipers): Katch-McArdle
> - Obese clients (BMI >35): Harris-Benedict may overestimate; use Mifflin-St Jeor

---

## 2. Total Daily Energy Expenditure (TDEE)

```
TDEE = BMR × NEAT Activity Factor
```

### NEAT Activity Factors

| Level | Activity Description | Multiplier |
|-------|---------------------|-----------|
| Sedentary | Desk job, minimal movement, drives everywhere | 1.20 |
| Lightly Active | Desk job + light walking, on feet 2–3h/day | 1.375 |
| Moderately Active | On feet 4–6h/day, active commute, active hobbies | 1.55 |
| Very Active | Physical job (nurse, waiter, PT), or daily intense activity | 1.725 |
| Extra Active | Manual labor, military, elite athlete in-season | 1.90 |

> **Important:** The activity factor accounts for NEAT only. Training is added
> separately if using the Harris or Mifflin approach without training integrated.
> For simplicity, use the factor that best represents the client's full daily activity
> including training days, and accept 5–10% margin of error.

---

## 3. Caloric Targets by Goal

```
Fat Loss:    TDEE − 300 to −500 kcal/day (moderate deficit, preserves muscle)
             TDEE − 500 to −750 kcal/day (aggressive, monitor lean mass)
             Never below BMR for extended periods

Muscle Gain: TDEE + 200 to +300 kcal/day (lean bulk — beginners and intermediates)
             TDEE + 300 to +500 kcal/day (standard bulk — intermediates)

Body Recomp: TDEE ±0 to −100 kcal (maintenance-adjacent, high protein)
             Only viable for beginners or detrained individuals

Performance: Match TDEE or slight surplus; carbohydrate periodization by training load
```

### Maximum physiologically sound rates of change

| Goal | Rate | Notes |
|------|------|-------|
| Fat loss (conservative) | 0.5% BW/week | Minimizes muscle loss |
| Fat loss (aggressive) | 1.0% BW/week | Requires high protein + strength training |
| Fat loss (very aggressive) | >1.0% BW/week | Significant muscle loss risk — not recommended |
| Muscle gain (beginner 0–2 yr) | 1–2 kg/month | Newbie gains window |
| Muscle gain (intermediate 2–5 yr) | 0.5–1 kg/month | Consistent progressive overload required |
| Muscle gain (advanced 5+ yr) | 0.1–0.25 kg/month | Diminishing returns |

---

## 4. Macronutrient Targets

### Protein targets (priority — set first, always)

| Goal | Protein target |
|------|---------------|
| Fat loss | 2.0–2.4 g/kg BW (higher end preserves lean mass in deficit) |
| Muscle gain | 1.8–2.2 g/kg BW |
| Recomp | 2.0–2.4 g/kg BW |
| General health / beginner | 1.6–2.0 g/kg BW |
| Athlete in-season | 1.8–2.2 g/kg BW |
| Elderly client (>60) | 1.6–2.2 g/kg BW (higher = sarcopenia prevention) |

> **Minimum threshold:** 1.2 g/kg BW. Below this level, muscle preservation
> during any caloric manipulation is compromised.

### Carbohydrate and fat allocation (after protein is fixed)

1. Calculate protein calories: protein_g × 4
2. Remaining calories = Total kcal − protein calories
3. Distribute remaining between carbs and fats based on insulin sensitivity score:

| Insulin Sensitivity Score | Carb % of remaining | Fat % of remaining |
|--------------------------|--------------------|--------------------|
| 0 (normal) | 55–60% | 40–45% |
| 1 (mildly reduced) | 45–55% | 45–55% |
| 2 (likely reduced) | 35–45% | 55–65% |
| 3 (high-risk) | 25–35% | 65–75% |

> **Note for athletes:** Carbohydrate periodization overrides these fixed percentages.
> High-volume training days = higher carbs. Rest days = lower carbs, higher fats.

---

## 5. Training Age Scoring Rubric (1–10)

Assign training age score based on quality and consistency of training history,
not chronological years.

| Score | Profile |
|-------|---------|
| 1 | Never trained, completely sedentary, or only recreational walking/cycling |
| 2 | Some gym experience (<1 year, sporadic), no structured program |
| 3 | 1–2 years of gym training with basic structure (machines, some free weights) |
| 4 | 2–3 years, consistent attendance, understands progressive overload basics |
| 5 | 3–4 years, structured program followed, can perform main compound lifts with form |
| 6 | 4–5 years, self-programs or follows advanced programs, understands RPE/periodization |
| 7 | 5–7 years, competitive experience or high-level amateur, injury management experience |
| 8 | 7–10 years, periodizes training annually, high technical proficiency, performance benchmarks |
| 9 | 10+ years, athlete or competitive bodybuilder/powerlifter/endurance, coaches others |
| 10 | Elite/professional athlete with national or international competitive history |

### Volume tolerance by training age score

| Training Age Score | Sets per muscle group per week (MEV–MRV range) |
|-------------------|-----------------------------------------------|
| 1–2 (Beginner) | 6–10 sets |
| 3–4 (Early intermediate) | 10–14 sets |
| 5–6 (Intermediate) | 12–16 sets |
| 7–8 (Advanced) | 16–20 sets |
| 9–10 (Elite) | 18–25+ sets (sport and phase dependent) |

> **MEV** = Minimum Effective Volume (below this = no adaptation signal)
> **MRV** = Maximum Recoverable Volume (above this = accumulated fatigue > adaptation)

---

## 6. Recovery Index

```
Recovery Index = Sleep Hours × Sleep Quality Score (1–10)
```

| Recovery Index | Status | Program response |
|---------------|--------|-----------------|
| 63–90 | Optimal (e.g., 9h × 9) | Full training load as planned |
| 49–62 | Good (e.g., 7h × 8) | Standard training load |
| 35–48 | Adequate (e.g., 7h × 6) | Monitor fatigue. Reduce volume if needed |
| 21–34 | Compromised (e.g., 6h × 5) | Reduce intensity. Add recovery sessions |
| <21 | Critical (e.g., <5h × <5) | Low-intensity only. Address sleep before load |

> **Clinical note:** A Recovery Index <30 means the hormonal environment
> (GH, testosterone, cortisol) is significantly compromised. Prescribing high-
> intensity training will accelerate catabolism and increase injury risk.

---

## 7. Insulin Sensitivity Proxy Score

Assess from Domain 5 answers:

| Score | Criteria |
|-------|----------|
| 0 | No post-carb energy crash, no regular bloating, stable energy all day |
| 1 | Mild fatigue after large carb-heavy meals (rare, manageable) |
| 2 | Marked post-carb crash and/or brain fog consistently after carb-heavy meals |
| 3 | Score 2 + frequent bloating + multiple food triggers + possible weight history of insulin resistance |

**Score 0–1:** Standard carbohydrate distribution. 40–55% of kcal from CHO.
**Score 2:** Lower glycemic load. Concentrate CHO around training windows.
**Score 3:** Refer to registered dietitian. Consider 2–4 week elimination protocol.

---

## 8. Adherence Probability Score

Assess from Domain 10 and overall interview:

| Rating | Indicators |
|--------|-----------|
| HIGH (>75%) | Realistic commitment, specific schedule, intrinsic motivation, no history of early dropout |
| MEDIUM (50–75%) | Some constraints, external motivation, history of 1–2 plan abandonments |
| LOW (<50%) | Overcommitted schedule, primarily extrinsic motivation, history of repeated abandonment, unresolved plan failure reasons |

**If LOW:** Simplify the plan to minimum effective dose. Do not optimize for maximum
results — optimize for consistency. Reassess at 4-week check-in.

---

## 9. Supplement Stack Evidence Rating

Rate the client's current stack on program entry:

| Rating | Criteria |
|--------|----------|
| EVIDENCE-BASED | All supplements are Tier 1 or Tier 2, correctly dosed and timed |
| PARTIALLY EFFECTIVE | Mix of evidence-based and ineffective supplements; some dosing errors |
| MOSTLY INEFFECTIVE | Primarily Tier 3 products (fat burners, BCAAs as protein replacement, proprietary blends) |
| POTENTIALLY HARMFUL | Stimulant excess, contraindicated with medical conditions, or unsafe stacking |

---

## 10. Daily Caffeine Load Reference

| Daily caffeine | Status |
|---------------|--------|
| 0–100 mg | Low. No tolerance issues. |
| 100–200 mg | Moderate. Effective pre-workout at 3–6 mg/kg BW. |
| 200–400 mg | High. Likely tolerance buildup. May impair sleep even 6–8h before bed. |
| >400 mg | Excessive. Anxiogenic risk. Cortisol elevation. Impaired sleep architecture. |

> **Pre-workout timing rule:** Last caffeine dose should be 8–10 hours before
> target sleep time to avoid sleep architecture disruption (half-life 5–6 hours).

---

## 11. Exercise Energy Expenditure (EEE) by Activity Type

EEE estimates are per session. Values assume a 70–80 kg person at moderate intensity.
Adjust ±15% for lighter (<60 kg) or heavier (>90 kg) individuals.
Adjust ±20% for low vs high intensity.

| Activity | Duration | EEE estimate (kcal/session) |
|----------|----------|-----------------------------|
| Strength training (hypertrophy, moderate load) | 45–60 min | 220–320 kcal |
| Strength training (heavy, compound — powerlifting style) | 60–75 min | 280–400 kcal |
| HIIT / metabolic conditioning | 20–30 min | 280–420 kcal |
| Functional training / CrossFit | 45–60 min | 350–500 kcal |
| Moderate cardio (cycling, elliptical, rowing) | 45–60 min | 300–450 kcal |
| Running (8–10 min/km pace) | 45–60 min | 380–520 kcal |
| Running (5–7 min/km pace) | 45–60 min | 480–650 kcal |
| Swimming (moderate) | 45–60 min | 350–500 kcal |
| Light cardio / brisk walking | 45–60 min | 150–240 kcal |
| Yoga / mobility / stretching | 45–60 min | 80–150 kcal |
| Team sports (football, basketball) | 60–90 min | 450–700 kcal |
| Martial arts / combat sports | 60 min | 400–600 kcal |

**EEE_current (weekly):**
```
EEE_current = sessions_per_week × avg_kcal_per_session
```

**EEE_new (weekly — from planned program):**
```
EEE_new = planned_sessions_per_week × avg_kcal_per_session_new_program
```

> **Professional note:** These are estimates. For ATHLETE tier, use heart-rate
> monitor data or metabolic equivalents (METs) if available. For AMATEUR tier,
> use mid-range estimates and adjust after 2 weeks based on weight trend.

---

## 12. ΔkCal Protocol — Transitioning from Current to New Program

This is the critical bridge between the current training state and the new program.

```
ΔkCal/week = EEE_new − EEE_current
ΔkCal/day  = ΔkCal/week ÷ 7
```

**Rule — how much of ΔkCal to add to the caloric target:**

| Goal | ΔkCal compensation |
|------|--------------------|
| Fat loss | Add 50–60% of ΔkCal to prevent extreme deficit and muscle loss |
| Muscle gain | Add 90–100% of ΔkCal to maintain surplus for growth |
| Body recomp | Add 70–80% of ΔkCal to stay near maintenance |
| Performance | Add 100% of ΔkCal + small surplus for adaptation |

**Practical example:**
- Client currently sedentary: EEE_current = 0 kcal/week
- New plan: 4 strength sessions × 280 kcal = EEE_new = 1,120 kcal/week → 160 kcal/day
- Goal: fat loss → add 50% of 160 = +80 kcal/day to the TDEE-based deficit
- Without this adjustment, effective deficit = planned deficit + 160 kcal/day extra
  = likely >800 kcal/day deficit → muscle catabolism and energy crash

**Final daily caloric target formula:**
```
TARGET = TDEE_base + (ΔkCal/day × compensation_%) ± goal_adjustment
```

Where:
- TDEE_base = BMR × NEAT_factor (without exercise EEE)
- goal_adjustment = −300 to −500 for fat loss / +200 to +300 for muscle gain

---

## 13. Training Day vs Rest Day Caloric Split

**Protein stays constant every day.** Carbohydrates and fats shift by day type.

**Step 1 — Calculate average daily target** (from §12 above)

**Step 2 — Apply training day / rest day split:**

| Macronutrient | Training day | Rest day |
|---------------|-------------|---------|
| Protein | Same as average target | Same as average target |
| Carbohydrates | Average + 30–50% | Average − 20–30% |
| Fat | Average − 15–20% | Average + 15–20% |
| Total calories | +10–15% above average | −10–15% below average |

**Practical example (70 kg client, fat loss goal, 2,000 kcal average target):**
- Protein: 150 g/day every day (2.1 g/kg BW)
- Training day: 2,200 kcal | CHO 240 g | Fat 55 g | Pro 150 g
- Rest day: 1,800 kcal | CHO 140 g | Fat 80 g | Pro 150 g
- Weekly average: 2,000 kcal ✓

> **Professional note:** For AMATEUR clients, start with a single daily target for
> simplicity. Introduce training/rest day periodization at week 4–6 once basic
> adherence is established. Complexity before compliance is a dropout trigger.

---

## 14. Peri-Workout Nutrition Windows

### Pre-workout meal (60–90 min before training)

| Profile | CHO | Protein | Fat | Notes |
|---------|-----|---------|-----|-------|
| AMATEUR | 30–50 g | 15–20 g | Low (<10 g) | Easy digestion priority |
| INTERMEDIATE | 40–60 g | 20–25 g | Low (<10 g) | Include leucine-rich source |
| ATHLETE | 60–80 g | 25–35 g | Very low | High-GI CHO if <60 min to session |

### Intra-workout (only if session >60–75 min of continuous effort)

| Profile | CHO/hour | Format |
|---------|----------|--------|
| AMATEUR | Not needed for <60 min | — |
| INTERMEDIATE | 30–45 g/hour | Sports drink, banana, energy gel |
| ATHLETE | 45–90 g/hour | Cyclic dextrins, maltodextrin, electrolytes |

> Intra-workout CHO is irrelevant for sessions under 60 min at normal intensity.
> Recommending it to a beginner doing 45-min weight sessions is nutritional noise.

### Post-workout meal (within 30–60 min after training)

| Profile | CHO | Protein | Fat | Notes |
|---------|-----|---------|-----|-------|
| AMATEUR | 40–60 g | 25–35 g | Low (<15 g) | Whey + fruit is sufficient |
| INTERMEDIATE | 60–80 g | 30–40 g | Low (<15 g) | Prioritize leucine ≥3 g |
| ATHLETE | 80–120 g | 35–45 g | Very low | Rapid glycogen replenishment window |

> Fat delays gastric emptying — keep it low in the 2-hour peri-workout window.
> The post-workout anabolic window is most critical for clients with reduced
> insulin sensitivity (score 2–3) — prioritize CHO+PRO immediately post-session.

---

## 15. Caloric Transition Protocol

When a client moves from their current training state to a new program, calories
should not be changed overnight. The metabolic and hormonal system needs time to adapt.

**Protocol by magnitude of change:**

| ΔkCal/week (new vs current) | Transition approach |
|-----------------------------|---------------------|
| <500 kcal | Immediate adjustment. Apply new target from day 1. |
| 500–1,500 kcal | 2-week ramp. Add 50% of ΔkCal in week 1, full adjustment in week 2. |
| >1,500 kcal | 4-week ramp. +25% of ΔkCal per week over 4 weeks. |

**Example — sedentary client starting 5×/week program (EEE_new = 1,800 kcal/week):**
- Week 1: Add +225 kcal/day (25% of 1,800/7)
- Week 2: Add +450 kcal/day (50%)
- Week 3: Add +675 kcal/day (75%)
- Week 4: Full target (+900 kcal/day contribution from EEE_new, minus goal adjustment)

**Why this matters:** Jumping immediately to full caloric adjustment when starting
a new high-volume program causes gastrointestinal discomfort, energy spikes, and
often psychological resistance ("I'm eating so much and still training"). The ramp
allows the body's appetite hormones (leptin, ghrelin, insulin) to recalibrate
naturally with the new energy demand.

> **For fat loss clients increasing training:** The ramp is especially critical.
> An aggressive immediate deficit + new high-volume program = cortisol spike,
> testosterone suppression, and muscle catabolism within 2–3 weeks. This is one of
> the most common reasons "I started training and eating less but lost muscle."
