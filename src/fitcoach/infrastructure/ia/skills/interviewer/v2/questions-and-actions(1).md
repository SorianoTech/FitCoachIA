# Questions, Expert Analysis & Response Actions

This reference file contains the full question bank for all 10 domains plus complementary
questions. For each domain you will find:
- **The question(s) to ask**
- **Metrics to extract** from the answer
- **Expert analysis** — what a professional coach concludes from those values
- **Response actions** — what to do with the information
- **Sufficiency & realism check** — is the answer complete and credible?
- **Tier-specific depth** — how to probe differently for AMATEUR / INTERMEDIATE / ATHLETE

---

## DOMAIN 1 — Biometrics & Body Composition

### Question to ask
> *"¿Cuál es tu edad, peso, altura y cómo describirías tu composición actual?
> ¿Tienes mucho músculo, poco músculo, mucha grasa, poca grasa?"*

For ATHLETE tier, also ask:
> *"¿Tienes medida de pliegues cutáneos, DEXA o bioimpedancia reciente?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Age | Numeric | Years (integer) | Any value |
| Sex | Categorical | Male / Female / Other | Required |
| Height | Numeric | cm (e.g., 175) | Required |
| Weight | Numeric | kg (e.g., 82) | Required |
| Body composition (subjective) | Descriptive scale | "mucho/poco músculo, mucha/poca grasa" | At least one descriptor |
| Body fat % | Numeric (optional) | % from DEXA / BIA / calipers | Only if available |

**Minimum viable response:** Age + sex + height + weight + one body composition descriptor.
If any of these is absent, probe before moving to Domain 2.

---

### Tier-Specific Depth

**AMATEUR:** Accept subjective description. BMI + subjective = sufficient for basic
caloric anchor. Focus on perception alignment — it predicts psychological resistance.

**INTERMEDIATE:** Request a rough body fat % estimate. Even "around 20%" improves
macro target precision. Cross-reference with training history and physique description.

**ATHLETE:** Request objective body composition data if available (BIA, DEXA, calipers).
Use Katch-McArdle (lean mass formula) instead of Mifflin-St Jeor for greater precision.
If no data: use subjective + performance context to estimate lean mass.

---

### Metrics to Extract

| Metric | How to obtain | Normal ranges |
|--------|--------------|---------------|
| Age | Direct | — |
| Sex | Direct or inferred | — |
| Height (cm) | Direct | — |
| Weight (kg) | Direct | — |
| BMI | kg / m² | 18.5–24.9 normal; >25 overweight; >30 obese |
| Estimated body fat % | Subjective description + BMI cross-reference | M: 10–20% healthy; F: 18–28% healthy |
| BMR | Formula (see metrics-and-formulas.md) | Varies by body composition |
| Body perception accuracy | Subjective description vs. BMI/weight reality | Aligned / Distorted |

→ Calculate BMR immediately. It anchors every caloric decision.

---

### Expert Analysis

**What a pro coach concludes:**

- **BMI >25 + "little muscle, lots of fat"** → Typical overweight sedentary client.
  Caloric deficit + strength training is the lever. Priority is metabolic health.

- **BMI 22–25 + "little muscle, some fat"** → Skinny-fat (normal weight obese).
  This is often the most psychologically challenging profile. Recomp is possible but slow.
  Manage expectations aggressively before starting.

- **BMI >28 + "lots of muscle"** → Two possibilities: genuinely muscular (athlete),
  or body dysmorphia (overestimates muscle). Cross-check with training history and
  performance benchmarks. If training age is low and benchmarks are weak → distorted
  perception. Flag it.

- **Very low weight + "lots of fat, no muscle"** → Possible sarcopenic obesity or
  severe deconditioning. Prioritize lean mass preservation and check for disordered
  eating signals in Domain 4.

- **Perceived body vs. reality gap** → The larger this gap, the more psychological
  management the program requires. A client who thinks they have more muscle than they
  do will resist caloric deficits ("but I'll lose my gains"). A client who underestimates
  their fat will set unrealistic cut timelines.

**Body perception flag logic:**
- If described composition is significantly better than BMI/weight suggests → `DISTORTED ↑`
- If described composition is significantly worse than data suggests → `DISTORTED ↓`
- Otherwise → `ALIGNED`

---

### Response Actions

1. **Calculate BMR immediately** (use Mifflin-St Jeor as default).
2. **Do not correct body perception verbally yet.** Note it internally. Address
   expectation management when discussing goals in Domain 2.
3. **If BMI >30 and client is new to training:** Flag medical clearance consideration.
4. **If client cannot give weight or height:** Accept approximation, note as
   `[ESTIMATED]` in profile, and flag for follow-up measurement.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Age, sex, height, and weight are provided.
⚠️ **Insufficient if:** Client only says "I'm overweight" or "I'm fine." Probe:
> *"¿Puedes darme una cifra aproximada de peso y tu altura?"*

🚨 **Realism flag:** If a client claims very low body fat with high weight and
no athletic background → investigate before accepting the self-assessment.

---

## DOMAIN 2 — Goals & Timeline

### Question to ask
> *"¿Qué quieres lograr prioritariamente — perder grasa, ganar músculo o mejorar
> rendimiento — y en cuánto tiempo te gustaría notar el primer cambio real?"*

Follow-up elicitation (always ask):
> *"¿Y qué te daría eso que no tienes ahora mismo?"*
(Repeat up to 3 times to find the real driver.)

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Primary goal | Categorical | fat loss / muscle gain / recomp / performance / health / aesthetics | Required |
| Timeline | Numeric + unit | "X semanas/meses para notar cambio" | Required — probe if absent |
| Underlying motivation | Qualitative | Free text — the real "why" | Probe until reached |
| Expectation rate | Implicit | Derived from goal + timeline | Calculate, do not ask directly |

**Minimum viable response:** Goal category + specific timeline + one motivational driver.
"I want to lose weight and feel better" = insufficient. "I want to lose 8 kg in 3 months
for my sister's wedding because I haven't felt good about my body for 2 years" = sufficient.

---

### Tier-Specific Depth

**AMATEUR:** Focus on emotional driver and expectation management. Beginners routinely
expect 2-3x faster results than physiology allows. Re-education at this stage prevents
dropout at week 3. Anchor to non-scale victories (energy, strength, clothes fit).

**INTERMEDIATE:** Goal is likely more specific (e.g., "get below 15% body fat" or
"add 10 kg to my squat"). Assess whether the timeline is consistent with training
history and current body composition. Intermediate clients often underestimate the
time required for advanced adaptations.

**ATHLETE:** Competitive athletes have fixed timelines (competition date, pre-season,
weight class cut). The goal is non-negotiable — the strategy must fit the calendar.
Assess: peak vs off-season, cut vs maintenance vs bulk phase. The caloric and
training prescription changes completely by competition phase.

---

### Metrics to Extract

| Metric | Assessment |
|--------|-----------|
| Goal category | Fat loss / Muscle gain / Recomp / Performance / Health / Aesthetics |
| Timeline stated | Weeks or months to first noticeable change |
| Rate of change expected | kg/week or % body fat/month implied |
| Underlying emotional driver | Social event / health scare / relationship / career / self-worth |
| Expectation realism | Realistic / Aggressive / Physiologically impossible |

---

### Expert Analysis

**Maximum physiologically sound rates of change (natural, trained individual):**

| Goal | Maximum realistic rate | Notes |
|------|----------------------|-------|
| Fat loss | 0.5–1% body weight/week | Exceeding this risks muscle loss |
| Muscle gain (beginner) | 1–2 kg/month | Newbie gains only in first 6–12 months |
| Muscle gain (intermediate) | 0.5–1 kg/month | Progress slows significantly |
| Muscle gain (advanced) | 0.1–0.25 kg/month | Diminishing returns — years of training |
| Body recomp | Simultaneous 0.3% BF drop + 0.3 kg muscle/month | Only viable for beginners or returning athletes |

**What the timeline reveals:**
- "I want to lose 10 kg in 1 month" → 2.5 kg/week. Physiologically impossible without
  catastrophic muscle loss and health risk. This client needs **immediate expectation
  re-education** before any plan is designed. If not addressed, they will abandon
  the plan at week 3.
- "I want to see something in 3 months" → reasonable. First visible changes in fat loss
  typically appear at 4–8 weeks. Muscle size changes: 8–12 weeks minimum.
- "I'm not in a rush, I want to do this properly" → ideal adherence predictor. This
  client is more likely to sustain a plan long-term.

**The real driver matters more than the stated goal:**
- "Lose weight for my wedding in 3 months" → External deadline. High initial motivation,
  high dropout risk after the event. Design an exit strategy and habit system.
- "My doctor told me my cholesterol and blood pressure are high" → Health scare driver.
  Strongest long-term adherence predictor. Treat with clinical respect.
- "I want to feel confident again" → Psychological driver. Progress metrics need to
  include non-scale victories (energy, strength, clothes fit) or this client will
  quit when the scale doesn't move fast enough.

---

### Response Actions

1. **Calculate maximum realistic weekly/monthly rate** based on current weight and goal.
2. **Compare to stated timeline.** If gap exists → address it in the interview before
   closing: *"Based on physiology, X is more realistic. Would that still work for you?"*
3. **Record the real driver** — not the surface goal. This drives the program's
   psychological design and check-in messaging.
4. **If timeline is unrealistic:** Do not proceed without re-education. A plan built
   around impossible expectations will fail regardless of quality.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Goal category is clear, timeline is specific, emotional driver identified.
⚠️ **Insufficient if:** "I just want to be healthier" — probe for specifics.
🚨 **Realism flag:** Any expectation exceeding 1% BW/week fat loss, or 2 kg/month
muscle gain in a non-beginner, is physiologically impossible without pharmacological
assistance. Flag it and educate.

---

## DOMAIN 3 — Daily Activity (NEAT)

### Question to ask
> *"¿A qué te dedicas y cómo es tu movimiento desde que te despiertas hasta que
> entrenas — eres sedentario, moderadamente activo, o muy físico en tu día a día?"*

Probe if unclear:
> *"¿Cuántos pasos al día dirías que das aproximadamente?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Occupation | Descriptive | Job title or type | Required |
| Physical demand | Categorical | Desk / standing / walking / manual | Required |
| Daily steps | Numeric (approx) | steps/day (e.g., ~5000) | Estimate acceptable |
| Active commuting | Binary | Yes / No + mode | Useful |
| Leisure movement | Descriptive | Hobbies, walks, household activity | Useful |
| NEAT classification | Derived | SEDENTARY / LIGHTLY / MOD / VERY / EXTRA | Coach assigns |

**Minimum viable response:** Occupation type + physical demand descriptor.
"I work in an office" → sedentary (1.2). "I'm a nurse" → very active (1.725).
Steps data refines the multiplier when occupation is ambiguous.

---

### Tier-Specific Depth

**AMATEUR:** NEAT multiplier is the single most important caloric variable for
this profile. A sedentary amateur who adds 3 training sessions has a much lower
TDEE than they think. Over-estimating NEAT is the most common reason for diet
failure in beginners ("I train 3x a week but eat at my TDEE and don't lose weight").

**INTERMEDIATE:** Cross-check NEAT with training frequency. An intermediate training
4-5x/week with a physical job may have total daily energy expenditure in the very
active range — a significant caloric requirement that must be met for progress.

**ATHLETE:** NEAT in competitive athletes can be extremely variable by training phase.
In-season with twice-daily sessions + physical job = multiplier 1.9. Off-season with
rest and desk job = multiplier 1.375. Program all phases separately.
> *"¿Tienes desplazamientos a pie, en bici, o siempre en coche/transporte?"*

---

### Metrics to Extract

| Metric | Value |
|--------|-------|
| Occupation physical demand | Desk / standing / walking / manual labor |
| Estimated daily steps | <5,000 / 5,000–10,000 / >10,000 |
| Active commuting | Yes / No |
| Leisure movement | Hobbies, walks, chores |
| NEAT activity factor | 1.2 / 1.375 / 1.55 / 1.725 / 1.9 |
| NEAT kcal contribution | TDEE − BMR − TEF − exercise EE |

---

### Expert Analysis

**Why NEAT is the most underestimated variable in program design:**

NEAT (Non-Exercise Activity Thermogenesis) accounts for 15–50% of total daily energy
expenditure depending on lifestyle. It is almost always more important than the gym
session for total caloric output.

**Critical professional insight:**
- A restaurant server or nurse walks 8,000–12,000 steps and stands 6–8 hours/day.
  Even without structured training, their NEAT contributes 400–800 kcal more than
  a desk worker.
- A programmer who trains 5×/week but sits 10 hours/day has a LOWER total energy
  expenditure than a factory worker who never sets foot in a gym.
- **Never calculate TDEE from training frequency alone.** The first question should
  always be: what does the rest of the day look like?

**NEAT multiplier guide:**

| Activity level | Description | Multiplier |
|---------------|-------------|-----------|
| Sedentary | Desk job, minimal movement, car commute | 1.2 |
| Lightly active | Desk job + some walking, standing occasionally | 1.375 |
| Moderately active | On feet 4–6h/day, active commuting, active hobbies | 1.55 |
| Very active | Physical job (nurse, waiter, trainer), or daily intense activity | 1.725 |
| Extra active | Manual labor, military, elite athlete in-season | 1.9 |

**NEAT paradox in weight loss:** When caloric intake drops significantly, NEAT
decreases adaptively (spontaneous movement decreases, fidgeting decreases). This is
a primary driver of fat loss plateaus. If a client stalls despite adherence,
suspect NEAT compensation before adjusting calories.

---

### Response Actions

1. **Assign NEAT multiplier.** Use this to calculate TDEE in the profile.
2. **Calculate EEE_current from current training sessions:**
   Using the activity type and session duration reported in this domain, estimate
   weekly Exercise Energy Expenditure. Cross-reference with Domain 7 for precision.
   → See `references/metrics-and-formulas.md` §11 for EEE estimates by activity.
3. **Flag if training frequency contradicts NEAT level.** A "very active" job person
   training 6×/week is at overtraining risk — total stress load may exceed recovery.
4. **Note NEAT > training for caloric calculation** in the profile if applicable.
5. **For fat loss clients with sedentary NEAT:** Add a NEAT target (step goal) to
   the plan — often more sustainable than increasing training volume.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Occupation and rough daily movement pattern are clear.
⚠️ **Insufficient if:** "I move around a bit." Probe with step estimate.
🚨 **Realism flag:** "I sit all day at work but I feel very active" → NEAT is
probably 1.375, not 1.725. Discrepancy affects TDEE by 300–500 kcal. Correct before
calculating nutrition plan.

---

## DOMAIN 4 — Nutritional Habits

### Question to ask
> *"¿Cuántas veces comes al día y cuáles son los alimentos que 'se te escapan'
> — los que comes por ansiedad, falta de tiempo, o simplemente porque están ahí?"*

Follow-up (always):
> *"Cuéntame exactamente qué comiste y bebiste ayer desde que te levantaste
> hasta que te acostaste."*

Weekend probe (essential for underreporters):
> *"¿Y el sábado o domingo, cómo fue?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| 24h recall (weekday) | Descriptive sequence | All foods + drinks from waking to sleep | Full day required |
| 24h recall (weekend day) | Descriptive sequence | Same format | Required if underreporting suspected |
| Meal frequency | Numeric | meals/day (integer) | Required |
| Meal timing | Time descriptors | Breakfast at X, lunch at Y, etc. | Useful |
| "Escape" foods / snacks | Free text | Specific items + frequency | Key data point |
| Estimated total kcal | Derived | Coach calculates from recall | Do not ask directly |
| Estimated protein | Derived | g/day — coach calculates | Do not ask directly |
| Caloric beverages | List + frequency | "2 cafes con leche, 1 cerveza los viernes" | Required |

**Minimum viable response:** Complete 24h recall for at least one full day.
Do not accept "I eat 3 times a day, I eat healthy" — this is not actionable data.
The 24h recall exercise is non-negotiable.

---

### Tier-Specific Depth

**AMATEUR:** Focus on the "escape foods" — the honest answer about what falls through
the cracks is more valuable than the idealized description of meals. Most amateurs
underreport by 400-700 kcal/day in snacks, sauces, and drinks. This gap explains
the majority of "I eat well but don't lose weight" complaints.

**INTERMEDIATE:** Intermediate clients often track macros or have tracked previously.
Ask for typical macro split if available. Probe protein specifically — intermediates
are usually eating enough total food but protein is still below optimal (1.6-2.2 g/kg).

**ATHLETE:** Full quantified nutrition data is expected — grams of each macronutrient,
meal timing relative to training sessions, intra-workout nutrition protocol, and
competition/game day nutrition strategy if applicable. If not tracked, recommend
starting food logging as a prerequisite to program design.

---

### Metrics to Extract

| Metric | Target values / flags |
|--------|----------------------|
| Meal frequency | 2–6 meals/day |
| Estimated daily kcal | Compare to TDEE — flag if gap >400 kcal |
| Estimated protein (g/day) | Target: 1.6–2.2 g/kg BW |
| Estimated protein (g/kg BW) | <1.2 = insufficient; 1.6–2.2 = optimal |
| Hidden calories identified | Alcohol, sauces, snacks, drinks |
| Snacking pattern | Emotional / stress / boredom / habitual |
| Meal timing | Breakfast skip / late-night eating / pre/post workout window |
| Dietary approach | Free / IF / keto / vegan / other |
| Food relationship | Healthy / emotional eating / restriction history |

---

### Expert Analysis

**Why "what escapes you" is the most powerful nutrition question:**
The standard "what do you eat" question triggers social desirability bias — people
report what they believe is healthy eating. "What escapes you" bypasses the filter
and captures the truth: the nightly ice cream, the office biscuits, the second glass
of wine, the Saturday takeaway.

**Professional analysis of common patterns:**

- **High meal frequency (5–6) but low total protein:** Often a sign of carb-heavy
  snacking. Client feels they eat a lot but is protein-deficient. Common in women
  trained on outdated "eat every 2 hours" advice.

- **1–2 meals per day (IF pattern or disordered):** If unintentional → likely appetite
  suppression from stress or disorder. If intentional IF → assess protein distribution
  across feeding window. One meal is insufficient for optimal muscle protein synthesis.

- **"I eat clean but can't lose weight":** Almost always a caloric underestimation.
  Liquid calories, sauces, oils, and weekend eating are the usual culprits. The 24-hour
  recall exercise typically reveals 300–700 kcal of unreported intake.

- **Protein consistently <1.2 g/kg BW:** This is the most common nutritional
  deficiency in the general population. At this level, muscle gain is impossible and
  fat loss will cause disproportionate lean mass loss. Priority #1 in most plans.

- **Alcohol >14 units/week:** Significant caloric contribution (7 kcal/g), hormonal
  disruption (testosterone suppression, cortisol elevation, impaired sleep architecture),
  and impaired muscle protein synthesis. Cannot be ignored in program design.

**The 20–40% underreporting rule:** Research consistently shows that people underreport
food intake by 20–40% on average. Assume all caloric estimates are the floor,
not the ceiling.

---

### Response Actions

1. **Estimate daily kcal and compare to calculated TDEE.**
   - If gap >500 kcal → flag underreporting. Do not accept as true intake.
   - Ask for weekend day recall separately.
2. **Calculate protein per kg BW.** If <1.6 g/kg → protein is Priority #1 in nutrition plan.
3. **Identify 3 highest-impact hidden calorie sources** and include in plan strategy.
4. **Assess meal timing** relative to training for peri-workout nutrition optimization.
5. **Flag food relationship concerns** — if emotional eating or restriction history
   detected, nutritional approach must be flexible and non-restrictive.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** 24-hour recall obtained for at least one weekday + one weekend day.
⚠️ **Insufficient if:** Only "I eat 3 times a day, I eat well." Not actionable data.
🚨 **Realism flag:** Stated intake <1,200 kcal with normal weight and activity →
likely severe underreporting OR disordered eating. Probe carefully.

---

## DOMAIN 5 — Digestive Health & Glucose Response

### Question to ask
> *"¿Sientes hinchazón abdominal con frecuencia, o notas bajones de energía
> o somnolencia después de comer hidratos como pan, pasta o arroz?"*

Follow-ups if positive:
> *"¿Con qué tipos de alimentos lo notas más?"*
> *"¿Cuánto tiempo después de comer aparece?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Post-carb energy crash | Binary + intensity | Yes/No + "fuerte, leve, apenas noto nada" | Required |
| Bloating frequency | Frequency scale | Rarely / Sometimes / Often / Daily | Required |
| Food triggers (if any) | List | Specific foods or food groups | Useful if symptoms present |
| Onset timing | Numeric | Minutes after eating | Useful if symptoms present |
| Bowel regularity | Categorical | Regular / Irregular / Constipation / Loose | Optional but useful |

**Minimum viable response:** Presence or absence of post-carb crash + bloating frequency.
Single binary answer ("no issues") is acceptable if no symptoms. If symptoms exist,
probe food triggers and timing before moving forward.

---

### Tier-Specific Depth

**AMATEUR:** This question often reveals the reason previous diets failed. A client
with marked post-carb crash who was prescribed a high-carb diet (very common in
standard dietary advice) experienced afternoon energy crashes and intense sugar cravings
that drove them off the plan. Identifying this pattern and switching to a lower glycemic
load approach dramatically improves adherence.

**INTERMEDIATE:** Cross-reference with training timing. An intermediate with reduced
insulin sensitivity who trains in the afternoon needs to concentrate their carbohydrate
intake in the peri-workout window (pre and post training) to maximize glycogen
replenishment while minimizing the glucose spike at other meals.

**ATHLETE:** For competitive athletes, this domain determines the intra-training
carbohydrate source. An athlete with a score of 0-1 can use maltodextrin or
high-GI sources intra-workout without issues. A score of 2-3 may benefit from
lower-osmolality sources (cyclic dextrins, palatinose) to avoid GI distress during
competition-intensity efforts.

---

### Metrics to Extract

| Signal | Implication |
|--------|------------|
| Post-carb energy crash (marked) | Reduced insulin sensitivity / hyperglycaemia response |
| Post-carb sleepiness | Large insulin spike → tryptophan crossing blood-brain barrier |
| Abdominal bloating (frequent) | Possible gut dysbiosis, FODMAP sensitivity, lactose/gluten intolerance |
| Bloating only with specific foods | Targeted food intolerance (map to food types) |
| No symptoms | Normal glucose response, healthy gut — standard carb approach viable |

---

### Expert Analysis

**Why this question is critical beyond digestion:**

Digestive symptoms are indirect biomarkers of **metabolic health** that most trainers
never assess. The post-carb crash is a clinical proxy for insulin sensitivity.

**Insulin sensitivity scoring (proxy, not diagnostic):**

| Score | Criteria | Implication |
|-------|----------|-------------|
| 0 | No crash, no bloating, stable energy | High insulin sensitivity — standard carb approach |
| 1 | Mild fatigue after large carb meals | Moderate — reduce glycemic load, prioritize complex carbs |
| 2 | Marked crash, brain fog, drowsiness after carbs | Likely reduced insulin sensitivity — cycled CHO or lower-carb approach |
| 3 | Score 2 + frequent bloating + suspected food intolerances | Metabolic + gut health intervention required — refer to dietitian |

**For the AMATEUR profile:** This score determines whether a standard balanced diet
is appropriate or whether a lower-carb / lower-GI approach will produce better
adherence through sustained energy levels.

**For the ATHLETE profile:** Post-training carbohydrate timing is critical for
glycogen replenishment. If insulin sensitivity is reduced, the anabolic window after
training is even more important — carbs around training for an athlete with reduced
insulin sensitivity will be preferentially directed to muscle glycogen rather than fat.

**The gut-performance connection:**
Frequent bloating = impaired nutrient absorption. An athlete eating 3,000 kcal but
absorbing 2,500 kcal effectively has a hidden caloric deficit. Gut health optimization
through probiotic foods, reduced FODMAPs, or targeted supplementation is a
performance intervention, not a comfort one.

---

### Response Actions

1. **Assign insulin sensitivity proxy score (0–3).**
2. **Determine carbohydrate strategy:**
   - Score 0–1: Standard carb distribution. 40–50% of kcal from CHO.
   - Score 2: Lower glycemic load approach. Distribute CHO around training windows.
   - Score 3: Consult dietitian flag. Consider elimination protocol for 2–4 weeks.
3. **If specific food triggers identified** → flag for elimination and reintroduction
   protocol. Add to "restrictions" in the nutrition profile.
4. **For ATHLETE:** Optimize intra-training carbohydrate use (cyclic dextrins,
   electrolytes) based on this score.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Client confirms or denies crash and bloating with specifics.
⚠️ **Insufficient if:** "Sometimes I feel full." Not diagnostically useful — probe.
🚨 **Red flag:** Score 3 + weight gain despite controlled intake → refer to GP or
dietitian. May indicate pre-diabetic state or thyroid dysfunction.

---

## DOMAIN 6 — Injury History & Physical Limitations

### Question to ask
> *"¿Tienes algún dolor 'amigo' que aparezca al entrenar, o alguna lesión
> antigua que te dé miedo reactivar?"*

Always follow up:
> *"¿Del 1 al 10, cuánto te limita ese dolor? ¿Has visto a alguien por ello?"*
> *"¿Hay ejercicios que evitas o que sabes que te sientan mal?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Active pain / injury | Binary + location | "Rodilla derecha desde hace 6 meses" | Full body check required |
| Pain severity | Numeric scale | 1-10 (1=barely noticeable, 10=prevents movement) | For each active issue |
| Movement limitation | Descriptive | "No puedo sentarme en cuclillas" | For each active issue |
| Past surgeries | List | Type + approximate date + area | Required |
| Medical conditions | List | Diagnosed conditions | Required |
| Current medication | List | Name + dose + reason | Required for supplement safety |
| Avoided exercises | List | Specific exercises or movement patterns | Important for program design |

**Minimum viable response:** Active pain yes/no for major areas (knees, back, shoulders,
hips) + any past surgeries + medical conditions + medications. If any positive: severity
(1-10) and functional limitation are required before proceeding.

---

### Tier-Specific Depth

**AMATEUR:** The most important output here is the contraindicated exercise list.
Beginners rarely have precise diagnoses — use functional questions ("does this hurt
when you do stairs?") rather than anatomical ones ("do you have patellar tendinopathy?").
Map symptoms to movement patterns, not diagnoses.

**INTERMEDIATE:** Intermediate clients often have chronic overuse injuries from years
of training with imbalances. Probe for "tengo una molestia que siempre está ahí" —
the normalized pain they've stopped noticing. This is usually the injury that will
flare under increased training load if not addressed proactively.

**ATHLETE:** Full medical history including sports medicine consultations, imaging
results, and physical therapy history. For athletes, injury history is periodization
history — previous injuries define which training phases are possible and which
are high-risk. Ask specifically: "¿Hay alguna lesión que haya afectado una temporada
entera?" — that injury is the highest-risk zone for the new program.

---

### Metrics to Extract

| Data point | Clinical significance |
|-----------|----------------------|
| Location and nature of pain | Determines contraindicated movement patterns |
| Pain duration (acute vs chronic) | Acute = rest and referral; Chronic = program modification |
| Pain rating (1–10) | >5 = significant limitation requiring physiotherapy referral |
| Limitation to function | Movement patterns to avoid / modify |
| Previous surgeries | Scar tissue, altered biomechanics, nerve sensitivity |
| Fear of re-injury | Psychological barrier — affects exercise compliance |
| Medical treatment status | Untreated injuries are a liability |

---

### Expert Analysis

**The injury normalization problem:**
Clients routinely discount chronic pain because they have lived with it for years.
"My knee always hurts a bit when I do stairs" is not normal — it is likely chronic
patellar tendinopathy or early chondromalacia. The professional assessment is:
any pain that consistently appears with specific movements requires a biomechanical
response, regardless of severity rating.

**Biomechanical decision tree for common injuries:**

| Injury | Avoid | Substitute with |
|--------|-------|----------------|
| Knee pain (anterior) | Leg extensions, deep knee flexion under load | Hip hinge dominance, partial ROM squats, leg press high foot position |
| Lower back pain (non-specific) | Loaded spinal flexion (sit-ups, GMs), heavy deadlifts early | Cable pull-throughs, trap bar DL, core stabilization progressions |
| Shoulder impingement | Overhead pressing, upright rows, internal rotation under load | Landmine press, neutral-grip pull-downs, scapular strengthening |
| Hip flexor tightness/pain | Heavy hip extension without warmup, sprint protocols | Hip flexor release, 90/90 mobility, step-up progressions |
| Plantar fasciitis | High-impact plyometrics, barefoot training on hard surfaces | Low-impact cardio (bike, swim), calf flexibility priority |

**The fear factor:** A client who fears re-injuring a previous injury will self-limit
range of motion, avoid loaded exercises, and have lower confidence in training. This
must be addressed through progressive loading and education — not avoidance. Avoidance
leads to compensatory patterns and new injuries.

---

### Response Actions

1. **Map all pain locations and movement restrictions** → build the contraindicated
   exercise list for the training profile.
2. **For pain rated >5/10 or limiting basic movement:** Refer to physiotherapist or
   sports medicine physician before programming. Flag `Medical clearance: YES`.
3. **For chronic low-level pain (1–4/10):** Include injury-specific corrective
   exercises in warm-up protocol. Note substitutions in training plan.
4. **Address fear of re-injury in first sessions:** Use regression progressions with
   higher rep/lower load. Build confidence through graded exposure.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Full body check performed — not just the obvious injuries.
⚠️ **Insufficient if:** "I have a bit of everything but it's fine." Probe each area.
🚨 **Red flag:** Any chest pain during exercise, unexplained joint swelling, nerve
pain (shooting, tingling), or post-surgical site pain → mandatory medical referral
before any exercise prescription.

---

## DOMAIN 7 — Training Experience & Equipment

### Question to ask
> *"¿Cuánto tiempo llevas entrenando en serio y de qué material dispones
> — gimnasio completo, casa, solo mancuernas?"*

Always follow up on type of training:
> *"¿Qué tipo de entrenamiento has hecho — pesas, cardio, CrossFit, calistenia,
> deportes, nada estructurado?"*
> *"¿Cuál es tu referencia de rendimiento actual? Por ejemplo: dominadas, sentadilla,
> press banca, tiempo corriendo sin parar."*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Years training (serious) | Numeric | Years (e.g., 2.5) | Required |
| Training type | Categorical | Weights / cardio / CrossFit / sports / calisthenics / mixed | Required |
| Training frequency | Numeric | Days/week currently | Required |
| Session duration | Numeric | Minutes per session | Required |
| Equipment access | Categorical | Full gym / home gym / dumbbells / bands / no equipment | Required |
| Performance benchmarks | Numeric (optional) | Pull-ups: X / Squat: X kg / Bench: X kg / Run: X km in Y min | Strongly preferred |
| EEE_current | Derived | Coach calculates — see metrics-and-formulas.md s.11 | Do not ask directly |
| EEE_new (projected) | Derived | Coach calculates after Domain 10 | Do not ask directly |

**Minimum viable response:** Training type + years + frequency + session duration + equipment.
Benchmarks are strongly preferred — flag as [TO BE ESTABLISHED WEEK 1] if unknown.

---

### Tier-Specific Depth

**AMATEUR:** Focus on TYPE of training over duration. Two years on the elliptical = training age 1.
Two years of structured barbell work = training age 3-4. The type determines neuromuscular
adaptations already present. Beginners who have only done cardio will need a 4-week
neurological adaptation phase before meaningful loading.

**INTERMEDIATE:** Probe training structure: was there a program or random selection?
Was progressive overload tracked? Periodization history? An intermediate who has
never followed a structured program is essentially a beginner for that programming
concept despite chronological training years.

**ATHLETE:** Full periodization history required. Current mesocycle phase? Last
competition result? Performance benchmarks are non-negotiable for athlete programming —
they define loading zones and intensity parameters for every session.

---

### Metrics to Extract

| Metric | How to assess |
|--------|-------------|
| True training age | Years × quality factor (see metrics-and-formulas.md) |
| Training age score (1–10) | Rubric: frequency, consistency, structure, technical quality |
| Training modality history | Neuromuscular adaptations already present |
| Volume tolerance | Low (<10 sets/muscle/week) / Med (10–15) / High (15–20+) |
| Technical proficiency | Self-report + benchmark cross-reference |
| Equipment access | Dictates exercise selection |
| Performance benchmarks | Objective fitness level anchor |

---

### Expert Analysis

**True training age is the most important variable in program design:**

Chronological training years are almost meaningless without quality assessment.
The key questions are: Was training structured or random? Was progressive overload
applied? Was technique prioritized? Was recovery managed?

**Training age quality multipliers:**
- Walking 3× per week for 5 years → Training age: 0.5 (minimal neuromuscular adaptation)
- Gym 2× per week, machines only, no progression for 3 years → Training age: 1
- Structured hypertrophy program, 3–4× per week, 2 years → Training age: 3–4
- Periodized programming, competition history, 5+ years → Training age: 6–8

**Why this determines everything:**
- **Volume tolerance:** A beginner saturates at 8–10 working sets per muscle per week.
  An intermediate needs 12–16. An advanced athlete needs 16–22+ to continue progressing.
  Prescribing too much volume to a beginner causes injury and dropout. Prescribing
  too little to an advanced athlete produces zero stimulus.

- **Program structure:** Full Body 3× is the most evidence-supported structure for
  beginners (high frequency, low per-session volume). Upper-Lower 4× for intermediate.
  PPL 5–6× or sport-specific for advanced.

- **Technique coaching requirement:** A beginner needs technique-first, load-second.
  An intermediate can tolerate heavier loading with cuing. An advanced athlete self-
  corrects and needs programming and peaking, not technique coaching.

**Equipment access — exercise selection logic:**
- Full gym: no limitations
- Dumbbells + bench at home: all unilateral work viable, limited compound loading
- Resistance bands only: volume-based approach, metabolic emphasis
- No equipment: calistenia periodized by difficulty progression (planche, ring work)

---

### Response Actions

1. **Assign training age score (1–10)** using the rubric in metrics-and-formulas.md.
2. **Determine volume tolerance band** → use to set weekly sets per muscle group.
3. **Select program structure** (Full Body / Upper-Lower / PPL / Sport-specific).
4. **Map available equipment** to viable exercise list.
5. **Calculate EEE_current (precise):** Refine current expenditure with both training
   type (Domain 3) and session structure (Domain 7) now known:
   EEE_current = sessions_per_week x avg_kcal_per_session
   Reference table: metrics-and-formulas.md section 11.
6. **Calculate EEE_new (projected):** From the recommended program structure:
   EEE_new = planned_sessions x avg_kcal_planned_session_type
7. **Calculate delta-kCal and record in profile:**
   delta_kCal_week = EEE_new minus EEE_current
   delta_kCal_day = delta_kCal_week divided by 7
   Without this delta the final caloric target will be systematically wrong.
   Full protocol: metrics-and-formulas.md section 12.
8. **If no performance benchmarks given:** Flag as [TO BE ESTABLISHED IN WEEK 1].
   First 2 weeks of programming serve as benchmarking period.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Training type, approximate years, and equipment are all known.
⚠️ **Insufficient if:** "I've been going to the gym on and off." Needs full clarification.
🚨 **Realism flag:** "I train 6 days/week with high intensity" + beginner benchmarks
→ likely overestimating training quality or session intensity. Adjust volume down.

---

## DOMAIN 8 — Sleep & Recovery Quality

### Question to ask
> *"¿Cuántas horas duermes de media y te despiertas con sensación de haber
> descansado de verdad?"*

Follow-ups:
> *"¿Tardas mucho en dormirte? ¿Te despiertas durante la noche?"*
> *"¿A qué hora te acuestas habitualmente y a qué hora te levantas?"*
> *"¿Usas el móvil u otras pantallas justo antes de dormir?"*
> *"¿Te han dicho que roncas o que paras de respirar dormido?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Sleep duration | Numeric | Hours per night (e.g., 6.5h) | Required |
| Waking feeling | Binary + quality | "Descansado / cansado / regular" | Required |
| Sleep quality (self-rated) | Numeric scale | 1-10 | Required |
| Sleep onset | Numeric | Minutes to fall asleep | Useful |
| Night wake-ups | Numeric | Times per night | Useful |
| Bedtime / wake time | Time | e.g., 23:30 / 07:00 | Useful for pattern analysis |
| Sleep aids used | List | Substance + dose (melatonin, medication, alcohol) | Required |
| Snoring / apnea risk | Binary | Yes / No / Partner has reported | Required |
| Daily stress level | Numeric scale | 1-10 | Required |
| Main stressors | List | Free text | Required if stress > 5 |

**Minimum viable response:** Hours + waking feeling + stress level 1-10.
Quality score and stress level are non-negotiable — they determine the Recovery Index
and therefore the maximum training intensity the program can include.

---

### Tier-Specific Depth

**AMATEUR:** Sleep quality is the most commonly ignored variable in amateur program
design. Most amateurs with poor results are sleeping 5-6 hours, are chronically
stressed, and are prescribed the same program as someone sleeping 8 hours with low
stress. Identify the Recovery Index before selecting program intensity.

**INTERMEDIATE:** Intermediate clients often have good training habits but degraded
sleep from lifestyle factors (young children, demanding job, social life). The
right intervention is often not a new training program but a Recovery Index
restoration protocol: sleep optimization + stress management first, then intensity
escalation.

**ATHLETE:** For competitive athletes, sleep monitoring data (wearables: Whoop, Garmin,
Oura) provides objective HRV, RHR, and sleep stage data. If available, use HRV trend
as the primary recovery marker for adjusting training load day-to-day. Ask: "¿Usas
algún dispositivo de monitorización del sueño o recuperación?" An athlete ignoring
HRV data is leaving 10-15% performance on the table.

---

### Metrics to Extract

| Metric | Optimal | Flags |
|--------|---------|-------|
| Sleep duration | 7–9h | <6h = significantly impaired recovery |
| Sleep quality (subjective 1–10) | 7–9 | <6 = compromised hormonal environment |
| Sleep onset latency | <20 min | >30 min = insomnia risk |
| Sleep maintenance | No awakenings or 1 brief | 2+ awakenings = sleep fragmentation |
| Waking refreshed | Yes consistently | No = either insufficient duration or poor quality |
| Snoring + apnea risk | None | Snoring + overweight + fatigue = OSA screening |
| Screen use before bed | None or 1h before | Screens within 30 min = melatonin suppression |
| Daily stress level | 1–4/10 | >7/10 = high cortisol, impaired recovery |

---

### Expert Analysis

**Why sleep is non-negotiable for program design:**

Sleep is the only time the body releases significant amounts of growth hormone (GH),
undergoes muscle protein synthesis from the previous session, and resets cortisol
to baseline. Designing a high-intensity program for someone sleeping 5–6 broken
hours is not aggressive programming — it is reckless programming.

**Hormonal consequences of poor sleep:**
- GH secretion is pulse-dependent on deep sleep stages (NREM 3/4). Chronic poor
  sleep = chronically blunted GH = impaired recovery, impaired fat oxidation.
- Testosterone in men is synthesized primarily during sleep. Even 5 days of
  restricted sleep (5h/night) reduces testosterone by 10–15% (Leproult & Van
  Cauter, 2011). This directly limits hypertrophy capacity.
- Cortisol rises with sleep restriction. Elevated cortisol → muscle catabolism,
  increased fat storage (especially visceral), suppressed immune function.
- Ghrelin increases and leptin decreases with sleep restriction → increased hunger
  of approximately 24% and preference for high-calorie foods (Spiegel et al., 2004).
  A client sleeping 5h is fighting their own hunger hormones trying to follow a diet.

**Recovery index (use in profile):**
- Hours × Quality score = Recovery index
- Optimal: 7h × 8 quality = 56
- Adequate: 7h × 6 = 42
- Compromised: 6h × 5 = 30
- Critical: <5h × <5 = <25 → Do not prescribe high-intensity training.

---

### Response Actions

1. **Calculate recovery index.** Use to set maximum training intensity ceiling.
2. **If recovery index <30:** Training program must start at LOW intensity regardless
   of goal. Address sleep before increasing load. Add sleep hygiene recommendations
   to the plan explicitly.
3. **If apnea risk is present:** Mandatory GP referral. Sleep apnea (untreated OSA)
   causes hypertension, insulin resistance, and extreme fatigue — training on top
   of undiagnosed OSA can be dangerous.
4. **High stress (>7/10):** Cortisol management strategies (lower training volume,
   more parasympathetic recovery work, breath work, magnesium supplementation)
   should be integrated into the plan.
5. **Note the hunger hormone implication for fat loss clients:** If sleep is poor,
   dietary adherence will be harder. Address sleep before tightening the deficit.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Hours, quality, and waking feeling are all confirmed.
⚠️ **Insufficient if:** "I sleep enough." Probe with times and quality.
🚨 **Red flag:** <5h regularly + heavy training plan + fat loss goal = recipe for
muscle loss, hormonal disruption, and plan failure. Address sleep first.

---

## DOMAIN 9 — Supplementation & Substances

### Question to ask
> *"¿Tomas algo actualmente — proteína, vitaminas, quemadores — y cuánto
> estarías dispuesto a invertir al mes si fuera necesario?"*

Always probe specifics:
> *"¿Qué exactamente tomas, en qué dosis y cuándo?"*
> *"¿Cuánto café o bebidas energéticas tomas al día?"*
> *"¿Consumes alcohol? ¿Cuántas unidades aproximadamente a la semana?"*
> *"¿Tienes alguna condición médica o tomas algún medicamento de forma regular?"*
> *"¿Te has hecho analítica en el último año? ¿Salió algo fuera de rango?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Supplement name | List | Product / ingredient name | All current supplements |
| Dose | Numeric + unit | g, mg, IU per serving | Required for each |
| Timing | Temporal | Pre / post / with meals / before bed | Required for each |
| Daily caffeine | Numeric | mg/day (espresso ~70mg, filter ~100mg) | Required |
| Alcohol | Numeric | Units/week + pattern (daily / weekends) | Required |
| Nicotine / other | Binary + type | Type + quantity | Required |
| Medical conditions | List | Diagnosed conditions | Required before any recommendation |
| Medications | List | Name + reason | Required |
| Recent blood work | Binary + flags | Out-of-range markers if available | Important for ATHLETE |
| Monthly supplement budget | Numeric | EUR/month | Required |

**Minimum viable response:** Current stack + caffeine level + alcohol units +
medical conditions + medications. Budget required before any recommendation is made.

---

### Tier-Specific Depth

**AMATEUR:** Most amateurs have random products marketed to them. Common pattern:
pre-workout + protein + fat burner (EUR 60/month) with no creatine, Vitamin D, or
omega-3. Reorder by evidence hierarchy. Start with Tier 1 basics.

**INTERMEDIATE:** Common issues: excess caffeine (>400 mg/day, tolerance loss, sleep
disruption), unnecessary BCAAs alongside adequate protein, no recovery supplements.
Audit every item and justify it or remove it.

**ATHLETE:** Full pharmacological cross-check required. Ask directly but non-judgmentally
about non-conventional substances. Any supplement interacting with medication requires
medical clearance before recommendation.

---

### Metrics to Extract

| Data point | Assessment |
|-----------|-----------|
| Current supplement stack | Evidence level + appropriateness for goal |
| Supplement timing and dosing | Correct / suboptimal / counter-productive |
| Daily caffeine intake (mg) | <200 mg optimal; >400 mg = tolerance ceiling, sleep risk |
| Alcohol units/week | <7 (F) / <14 (M) = low risk; above = significant impact |
| Medical conditions | Flag supplement contraindications |
| Current medication | Cross-check interactions |
| Blood work markers | Vitamin D, iron, B12, testosterone (if relevant) |
| Monthly budget | Determines stack prioritization |

---

### Expert Analysis

**Supplement hierarchy by evidence strength and impact:**

**Tier 1 — Strong evidence, high impact (recommend to all):**
- Creatine monohydrate (3–5 g/day): Strength, power, muscle gain, cognitive benefits.
  Safest ergogenic in sports science. Works for beginners and athletes alike.
- Protein powder (only if dietary protein target unmet): Whey post-workout for
  leucine delivery; casein before bed for sustained amino acid availability.
- Vitamin D3 (1,000–4,000 IU/day): 40–70% of the European population is deficient.
  Affects immune function, testosterone, muscle function, mood.

**Tier 2 — Good evidence, context-dependent:**
- Caffeine (3–6 mg/kg BW, pre-workout): Proven endurance and strength performance
  enhancer. Timing is critical — must not compromise sleep.
- Magnesium glycinate (300–400 mg before bed): Sleep quality, cortisol regulation,
  muscle relaxation. Often deficient in athletes.
- Omega-3 (2–4 g EPA+DHA/day): Anti-inflammatory, joint health, cardiovascular,
  mild fat oxidation support.
- Beta-alanine (3.2 g/day): Muscular endurance in the 1–4 minute effort range.
  ATHLETE tier only.
- Zinc (15–30 mg/day if deficient): Testosterone, immune function, sleep quality.

**Tier 3 — Weak evidence / context-specific:**
- BCAAs: Redundant if protein intake meets 1.6 g/kg BW. Money wasted.
- Fat burners (thermogenics): Largely caffeine + synephrine. Marginal benefit,
  real cardiovascular risk. Do not recommend without medical screening.
- Collagen peptides: Modest evidence for joint health when taken pre-training.
- Pre-workouts (proprietary blends): Variable. Assess ingredients individually.

**Stack assessment logic:**
1. Is the person taking anything in Tier 3 while missing Tier 1 basics? → Reorder.
2. Is supplement timing correct? (Creatine can be anytime; caffeine 30–60 min pre.)
3. Are any supplements contraindicated given medical history?
   - Stimulants (caffeine, synephrine) + hypertension or arrhythmia → STOP
   - Creatine + renal insufficiency → medical clearance required
   - High-dose fish oil + blood thinners → medical consultation
   - Iron supplementation + hemochromatosis → dangerous

---

### Response Actions

1. **List current stack. Rate each supplement: Tier 1 / 2 / 3 / harmful.**
2. **Identify immediate risks** (medical interactions, contraindications).
3. **Build priority stack** for goal, within budget:
   - Budget <€20/month: Creatine + Vitamin D only.
   - Budget €20–50: Add omega-3 + magnesium.
   - Budget >€50: Full Tier 1+2 stack based on specific goal and deficiencies.
4. **Flag for discontinuation** anything in Tier 3 being taken at the expense of Tier 1.
5. **If alcohol >14 units/week:** Address in plan as a nutritional and recovery issue.
   This is not a lifestyle judgment — it is a physiological variable.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Full stack with timing, medical conditions, and medication are known.
⚠️ **Insufficient if:** "Just some vitamins." Probe for specifics — type, brand, dose.
🚨 **Red flag:** Undisclosed medical condition + stimulant-heavy stack. Always ask
explicitly about cardiac, renal, and thyroid conditions before any stack recommendation.

---

## DOMAIN 10 — Commitment & Real Availability

### Question to ask
> *"¿Cuántos días y cuánto tiempo por sesión vas a dedicarle de verdad al plan,
> sin que suponga un problema en tu vida habitual?"*

Follow-ups:
> *"¿Hay semanas donde sabes de antemano que será imposible? ¿Trabajo, viajes, familia?"*
> *"¿Prefieres entrenar por la mañana, tarde o noche?"*
> *"¿Has seguido algún plan antes? Si lo dejaste, ¿qué fue lo que hizo que no continuaras?"*

---

### Input Format & Expected Data

| Field | Data type | Expected format | Minimum acceptable |
|-------|-----------|-----------------|-------------------|
| Training days/week | Numeric | Integer (e.g., 3) | Required |
| Session duration | Numeric | Minutes (e.g., 60) | Required |
| Preferred training time | Categorical | Morning / midday / afternoon / evening | Useful |
| Lifestyle constraints | Descriptive | Travel, shift work, family, etc. | Required |
| Previous plan failure reason | Qualitative | Specific reason for abandonment | Required |
| Readiness for change | Numeric scale | 1-10 | Useful |

**Minimum viable response:** Days/week + session duration + previous failure reason.
"As much as I need to" is not an answer — probe for a specific number.
The failure reason is the most reliable predictor of the next failure — never skip it.

---

### Tier-Specific Depth

**AMATEUR:** Apply the 80% rule: build the plan for 80% of stated commitment.
Beginners overcommit at peak motivation. "5 days/week" from a beginner = 3-day plan.
If they exceed it: bonus. If they match it: success. If only 2 days: still completable.

**INTERMEDIATE:** Find the recurring constraint — the week pattern that predictably
breaks the routine. Travel? Monday exhaustion? Friday social? Design contingency
sessions (20-min home workout as minimum effective dose fallback).

**ATHLETE:** Availability is dictated by competition calendar. Key data: weeks to
competition, current training phase, loading vs peaking vs recovery. Caloric and
supplement protocol changes completely by phase. Ask: "Cuantas semanas tienes
hasta tu proxima competicion?" This anchors the entire periodization.

---

### Metrics to Extract

| Metric | Optimal ranges |
|--------|--------------|
| Training days/week available | 2–6 (3–4 is optimal for most profiles) |
| Session duration (min) | 30–90 min (45–60 ideal for compliance) |
| Lifestyle constraints (travel, shifts, family) | Recurring vs occasional |
| Time of day preference | Morning / midday / evening |
| Previous plan failure reasons | Identify the adherence killer |
| Adherence probability | HIGH (>4/5 days avg) / MEDIUM / LOW |

---

### Expert Analysis

**The minimum effective dose principle:**
The best program is not the most scientifically optimal — it is the most optimal
that the person will actually follow. A 3-day Full Body program followed with 95%
consistency for 6 months will produce dramatically better results than a 6-day PPL
followed for 3 weeks.

**Commitment vs availability mismatch:**
Clients often overcommit in the initial consultation due to motivation peak (a known
psychological phenomenon: implementation intentions exceed behavioral capacity).
The professional response is to build the plan for 80% of their stated commitment,
not 100%, to create a buffer for life variability.

**Previous plan failure analysis:**
This is one of the highest-value data points in the entire interview. The reason
a previous plan failed is almost always the reason this plan will also fail unless
explicitly addressed:
- "I stopped because I didn't see results fast enough" → Expectation issue. Needs
  progress metrics that capture early change (strength, energy, body measurements).
- "I stopped because I hated the diet" → Dietary approach must be flexible and
  enjoyable. Caloric flexibility > rigid meal plans.
- "I stopped because I got bored of the exercises" → Program variation is a
  priority. Include exercise rotation every 4–6 weeks.
- "I stopped because I got injured" → Conservative volume and technique-first
  progression is mandatory, regardless of how fit they seem.
- "I stopped because life got in the way" → Plan needs contingency protocols:
  a 20-minute home workout for travel weeks, a reduced-frequency option for high-
  stress periods.

---

### Response Actions

1. **Select program structure based on real availability:**
   - 2 days/week: Full Body x2 (minimum effective dose)
   - 3 days/week: Full Body x3 (optimal for beginners/intermediates)
   - 4 days/week: Upper-Lower split (intermediate+)
   - 5-6 days/week: PPL or sport-specific (advanced only)
2. **Build contingency protocols** for low-availability weeks.
3. **Set adherence probability.** If LOW (<60% expected compliance), simplify the
   plan further before launch.
4. **Address the failure reason** explicitly in the plan design.
5. **Calculate final caloric target using the Exercise-Calorie Bridge:**
   This is the synthesis step where all data from Domains 1, 2, 3, 7, and 10 converge.
   a) Confirm EEE_current and EEE_new calculated in Domain 7.
   b) Apply delta-kCal compensation based on goal (metrics-and-formulas.md section 12):
      - Fat loss: add 50-60 percent of delta-kCal to avoid over-deficit
      - Muscle gain: add 90-100 percent of delta-kCal to maintain surplus
      - Recomp: add 70-80 percent of delta-kCal
   c) Final formula:
      FINAL_TARGET = TDEE_base + (delta_kCal_day x compensation) plus/minus goal_adjustment
   d) Apply caloric transition protocol if delta-kCal/week > 500 (metrics-and-formulas.md section 15).
6. **Define training-day vs rest-day split** (metrics-and-formulas.md section 13):
   - Protein constant every day
   - Carbs +30-50 percent on training days, -20-30 percent on rest days
   - Fat compensates inversely
   NOTE: For AMATEUR tier, start with a single daily target and introduce periodization
   at week 4-6 once base adherence is confirmed.
7. **Assign peri-workout nutrition windows** based on profile tier and session type
   (metrics-and-formulas.md section 14).
   Record pre/intra/post targets in the EXERCISE-CALORIE BRIDGE section of the profile.

---

### Sufficiency & Realism Check

✅ **Sufficient if:** Real days, duration, constraints, and previous failure reasons known.
⚠️ **Insufficient if:** "I'll train as much as I need to." Probe for specifics.
🚨 **Realism flag:** "I'll train 6 days/week for 2 hours" from a beginner with a
demanding job → Overcommitment. Red flag for early dropout. Negotiate down to
3–4 days/week before generating the plan.

---

## Complementary Questions

### Nutrition Complements

> *"¿Tienes alguna restricción alimentaria — alergias, intolerancias diagnosticadas,
> vegetarianismo, veganismo, restricciones religiosas — o alimentos que no comerás
> bajo ningún concepto?"*

→ **Action:** Without this, any meal plan may be literally unusable. This is
non-negotiable before generating nutrition content.

> *"¿Cuánta agua bebes al día aproximadamente, y tomas habitualmente bebidas con
> calorías — refrescos, alcohol, zumos?"*

→ **Action:** Caloric beverages are the most underreported calorie source. Flag
and include in nutritional calculations.

> *"¿Cocinas habitualmente o dependes de comida fuera de casa, precocinados, o
> que cocine otra persona?"*

→ **Action:** A meal plan with meal prep requirements is useless for someone who
never cooks. Assess and adapt: batch cooking guides, restaurant ordering strategies,
or ready-meal optimization.

### Training Complements

---

#### TRAINING COMPLEMENT T1 — Training Type History & Affinity

> *"¿Qué tipo de entrenamiento has hecho hasta ahora — pesas, cardio, deportes de
> equipo, artes marciales, calistenia, nada estructurado — y qué es lo que más
> te ha gustado o con lo que más constante has sido?"*

---

##### Metrics to Extract

| Metric | Significance |
|--------|-------------|
| Training modalities experienced | Neuromuscular adaptations already built |
| Consistency pattern by modality | Predictor of future adherence per training type |
| Preferred training type | Strongest adherence lever available |
| Avoided or disliked training types | Eliminate from initial program — reintroduce later if needed |
| Neuromuscular specificity of history | Determines true transfer to new program demands |

---

##### Expert Analysis

**Why training type is as important as training duration:**

The body adapts specifically to the stimulus it receives. This is the principle of
specificity (SAID: Specific Adaptation to Imposed Demands), and it is the reason
chronological training years mean nothing without knowing *what kind* of training
those years contained.

**Neuromuscular transfer map — what each background gives you:**

| Background | Neuromuscular adaptations present | Transfer to new program |
|-----------|----------------------------------|------------------------|
| Weightlifting / powerlifting | High intramuscular coordination, CNS efficiency, motor unit recruitment | HIGH transfer to hypertrophy and strength programs |
| CrossFit / functional training | Metabolic conditioning, multi-planar movement, work capacity | MEDIUM-HIGH transfer to strength; HIGH to conditioning |
| Endurance (running, cycling, swimming) | Cardiovascular efficiency, slow-twitch dominance, aerobic base | LOW transfer to hypertrophy; HIGH to mixed conditioning |
| Team sports (football, basketball) | Explosive power, agility, intermittent effort | MEDIUM transfer to strength; HIGH to athletic performance |
| Martial arts / combat sports | Body awareness, core stability, proprioception | MEDIUM transfer to most programs |
| Yoga / Pilates / mobility work | Flexibility, body awareness, postural control | LOW transfer to strength; HIGH value as complement |
| Calisthenics | Relative strength, body control, scapular stability | HIGH transfer to hypertrophy if progressive |
| Casual walking / unstructured activity | Minimal neuromuscular adaptation | LOW transfer — treat as training age 0–1 |
| No training background | No existing adaptations | True beginner — full neurological phase required |

**What this analysis determines concretely:**

1. **Volume prescription:** A person with 3 years of CrossFit has a significantly
   higher work capacity and connective tissue resilience than someone with 3 years
   of walking, even at the same body weight. The CrossFit background tolerates
   higher initial volume; the walking background needs a 4–6 week base-building phase.

2. **Technical learning curve:** Someone from a powerlifting background already knows
   hip hinge mechanics, bracing, and progressive overload. A runner starting
   hypertrophy training will need 3–4 weeks of technique-first sessions before
   loading is productive. Skipping this phase causes injury and stalls progress.

3. **Metabolic conditioning baseline:** An endurance athlete starting strength training
   will have excellent cardiorespiratory recovery between sets but limited ability to
   generate and sustain high-force outputs. Program design must bridge this gap
   progressively — starting with moderate loads and higher rep ranges before
   introducing heavier, lower-rep work.

4. **EEE_current precision:** Knowing the exact training type allows a much more
   accurate EEE_current estimate (cross-reference with metrics-and-formulas.md §11).
   "I train 3 days a week" means 480 kcal/week if those are yoga sessions, or
   1,050 kcal/week if they are heavy compound strength sessions. This 570 kcal/week
   gap directly impacts TDEE_current and therefore the initial caloric target.

5. **Adherence prediction by modality:** The modality the client has been most
   consistent with historically is the strongest predictor of future consistency.
   A client who stuck with martial arts for 4 years but quit every gym program
   in 6 weeks is telling you something critical: structured gym training does not
   engage them intrinsically. The best program for this client incorporates
   martial arts elements, movement-based training, or competitive components —
   not a standard PPL split, regardless of how optimal it is on paper.

6. **Injury risk profile by background:** Each training modality leaves a specific
   injury signature:
   - Endurance athletes: hip flexor tightness, IT band issues, patellar tendinopathy
   - Powerlifters: lumbar load history, shoulder internal rotation limits
   - CrossFit athletes: shoulder impingement risk, wrist/elbow load history
   - Sedentary background: global deconditioning, postural imbalances, weak posterior chain

   Knowing the background allows pre-emptive corrective work before injury appears.

**The consistency signal is the most underused data point in intake interviews:**

When a client says "I've always stuck with X but quit every time I tried Y", this is
not a character flaw — it is a physiological and psychological compatibility signal.
The professional response is to build the new program *around* X, not to replace it
with Y because Y is theoretically superior. A plan followed with 85% consistency
for 6 months beats a perfect plan followed for 3 weeks.

---

##### Response Actions

1. **Map training history to the neuromuscular transfer table above.** Determine what
   adaptations already exist and which ones are absent. Note the gaps explicitly
   in the Training section of the profile.

2. **Refine EEE_current** using the exact activity type now identified.
   Cross-reference with metrics-and-formulas.md §11. Update the Exercise-Calorie
   Bridge values if EEE_current changes significantly from the initial estimate.

3. **Identify the modality with highest historical consistency.** Flag it as
   the primary adherence anchor. The new program should incorporate elements of
   this modality or at minimum not directly conflict with it.

4. **Determine the technical learning phase needed:**
   - Strong relevant background (transfer HIGH): start loading in week 1.
   - Partial relevant background (transfer MEDIUM): 2-week technique consolidation,
     then progressive loading.
   - No relevant background or very low transfer: 4-week neurological adaptation
     phase (high rep, low load, movement pattern focus) before progressive overload.

5. **Build the injury pre-screening based on background:**
   Identify the specific injury risks associated with the client's training history
   and include pre-emptive corrective work in the warm-up protocol from day 1.

6. **For ATHLETE tier:** Map sport-specific adaptations to the new program demands.
   Identify which qualities (power, strength, endurance, agility) are already
   developed and which are limiting performance. Program accordingly.

---

##### Sufficiency & Realism Check

✅ **Sufficient if:** At least one specific modality is named with an approximate
duration and a consistency assessment (stuck with it / sporadic / abandoned).

⚠️ **Insufficient if:** "I've done a bit of everything." Not actionable — probe:
*"¿Cuál es el tipo de entrenamiento con el que más tiempo has mantenido una
rutina, aunque fuera corta?"*

🚨 **Realism flag:** Client claims high training volume and intensity across
multiple modalities simultaneously (e.g., "I run 5×/week, lift 4×/week, and do
martial arts 3×/week") but shows beginner-level benchmarks → either significant
exaggeration, very low intensity across all modalities, or a body that is
chronically under-recovered. In all three cases, total volume must be reduced
before adding a new structured program.

**EEE recalculation trigger:** If the training type revealed here differs
significantly from what was assumed in Domain 3 or 7, recalculate EEE_current
and update the Exercise-Calorie Bridge before finalizing the profile.

---

#### TRAINING COMPLEMENT T2 — Current Performance Benchmarks

> *"¿Cuál es tu referencia de nivel actual? Por ejemplo: dominadas que haces,
> peso en sentadilla o press banca, o tiempo que aguantas corriendo sin parar."*

→ **Action:** Objective performance benchmarks anchor the first phase of programming
and allow progress tracking. Cross-reference with training age score. If benchmarks
are inconsistent with stated training history (e.g., high years + weak benchmarks),
flag the discrepancy — either training quality was low or intensity was minimal.
If not known: flag as `[TO BE ESTABLISHED IN WEEK 1]`.

---

#### TRAINING COMPLEMENT T3 — Target Discipline & Hard Aversions

> *"¿Tienes algún deporte o disciplina en mente — powerlifting, running, fútbol,
> natación, culturismo? Y si no, ¿hay algún tipo de ejercicio que sepas que no
> vas a hacer?"*

→ **Action:** Absolute aversions eliminate exercise options immediately — do not
include them even as "optional." Target discipline changes the entire periodization
model: a powerlifting goal requires max strength peaking; a running goal requires
progressive volume and zone-2 base; aesthetics requires hypertrophy periodization
with a caloric surplus phase. Align program structure and caloric periodization
with the target discipline from the first session.

### Supplementation Complements

> *"¿Tienes alguna condición médica diagnosticada — hipertensión, diabetes,
> tiroides, riñón, corazón — o tomas algún medicamento de forma habitual?"*

→ **Action:** **This question is mandatory before any supplement recommendation.**
Conditions and medications change the entire stack. No exceptions.

> *"¿Te has hecho una analítica en el último año? ¿Te dijeron que algo estaba
> fuera de rango — hierro, vitamina D, colesterol, glucosa?"*

→ **Action:** Blood work reveals deficiencies that change supplementation priority.
Low Vitamin D → D3 before creatine. Low iron in a woman → iron before protein powder.

### Transversal Complements

> *"¿Has seguido dietas muy restrictivas o dirías que tu relación con la comida
> o con tu imagen corporal es algo que te genera estrés?"*

→ **Action:** Restriction history → flexible dieting approach only. No calorie
counting with obsessive compliance requirements. Avoid language that categorizes
foods as "clean" or "dirty."

> *"En una escala del 1 al 10, ¿cómo calificarías tu estrés en el día a día?"*

→ **Action:** Score >7 → reduce program volume, add recovery work, consider adaptogen
supplementation (ashwagandha, rhodiola), and address sleep/cortisol before optimizing
training intensity.

> *"¿Has seguido algún plan antes? Si lo dejaste, ¿qué fue lo que hizo que no
> continuaras?"*

→ **Action:** This is gold. The reason for previous failure is the most reliable
predictor of the next failure. Design specifically around it.
