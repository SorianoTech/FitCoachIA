---
name: fitness-interviewer
description: Structured interview module to collect initial user data in a fitness application. Runs 10 ordered questions to determine biometric profile, realistic goals, activity context, nutrition, health and real commitment. Detects inconsistencies, red flags and the need for professional referral.
version: 1.0
keywords: fitness assessment, onboarding, user profiling, biometric data, fitness goals, training plan, adherence prediction
---

## When to use this skill

Use this skill when:
- A new user accesses FitCoachIA for the first time
- Initial onboarding must be run to personalize the plan
- Baseline data must be collected for energy calculations (BMR, TDEE)
- The feasibility and realism of the user's goal must be validated
- The real activity context (NEAT) must be diagnosed

**Do not use this skill if:**
- The user has already completed a previous interview
- The user only wants a one-off question answered without context
- There is not enough contextual information to proceed

## Interview flow

### 0. Identity Capture
**Opening question (unnumbered):**
> What is your name, or the name/username you'd like me to call you?

**Information obtained:** Identity and communication preference.

---

### 1. Basic Biometric Data
**Question:**
> What is your age, weight, height, and how would you describe your current body composition? (a lot/little muscle, a lot/little fat)

**Expected fields:**
- Age (validate 14-100)
- Weight in kg (validate 30-300 kg)
- Height in cm (validate 130-230 cm)
- Subjective composition description

**Information obtained:**
- Base for calculating BMR (Harris-Benedict, Mifflin-St Jeor)
- Base for calculating TDEE
- **Critical psychological indicator:** Compares perception vs. reality. If they say "a lot of fat" but BMI is normal, or "a lot of muscle" but they are very sedentary = body image distortion → requires a psychological acceptance approach.

**Validation:**
- If BMI < 13.5 or > 45: Indicates possible eating disorder or medical condition → **RED FLAG**
- If the description is extremely incongruent with the data: Requires psychological deep-dive

---

### 2. The Real Goal
**Question:**
> What do you want to achieve as a priority: lose fat, gain muscle, improve performance, or a combination? How soon do you expect to notice the first real change?

**Expected fields:**
- Primary goal (single choice or ranking)
- Expected timeframe for "first change"
- Secondary goal (optional)

**Information obtained:**
- Defines aggressiveness of the caloric deficit/surplus
- Detects unrealistic expectations
- If they say "lose 10kg in 1 month" → **RED FLAG** (education needed)
- If they say "5 years" for a small change → Lack of motivation or paralyzing perfectionism

**Validation:**
- Realistic expectation: 0.5-1kg/week deficit, 0.25-0.5kg/week gain
- If the timeframe is unrealistic: Incorporate physiology education into the plan

**Recommended follow-up:**
- If they mix incompatible goals (losing fat + gaining muscle quickly): Clarify priority

---

### 3. Daily Activity (NEAT)
**Question:**
> What do you do for work? What is your typical movement like from the moment you wake up: sedentary (office), active (labor), or very physical (construction, waiter, etc.)?

**Expected fields:**
- Profession/occupation
- Qualitative activity description (sedentary/active/very physical)
- Average steps/hour if possible

**Information obtained:**
- **CRITICAL for TDEE:** A "beginner" waiter = 500-800 extra kcal vs. an "advanced" office worker. NEAT > training for most sedentary people.
- Defines the activity multiplier (1.2-1.5)

**Validation:**
- If they say "sedentary" but play tennis 4 times/week: Clarify what counts as NEAT (non-training activity)
- Goal: Identify the real kcal burned before training

---

### 4. Nutritional X-Ray
**Question:**
> How many main meals do you have per day? What foods "slip through" or do you eat out of anxiety/lack of time? (No judgment, we want the truth)

**Expected fields:**
- Number of meals (excluding snacks)
- Problem foods (specific, not just "sweets")
- Consumption context (anxiety, time, socializing)
- Approximate frequency

**Information obtained:**
- Identifies real snacking habits (not the denied version)
- Relationship with food (emotional vs. logistical)
- Removes pressure of a "perfect diet" = realistic adherence
- Base for personalized macro adjustments

**Validation:**
- If they eat 1 time/day: Indicates extreme restriction → **RED FLAG**
- If snacking is > 30% of caloric intake: Must be prioritized in the plan as a control strategy

**Optional deep-dive:**
- If they mention anxiety: "What emotions trigger that snacking? Stress, boredom, loneliness?"

---

### 5. Digestive Health and Energy
**Question:**
> Do you often feel abdominal bloating? Do you suffer energy crashes or fatigue after eating carbs (bread, pasta, rice)?

**Expected fields:**
- Presence/frequency of bloating (never/sometimes/always)
- Presence/frequency of energy "crash"
- Specific trigger foods

**Information obtained:**
- Indirect assessment of gut microbiota and insulin sensitivity
- If there's a "crash" = slow carb metabolism or insulin sensitivity → control glycemic load
- Independent of the aesthetic goal, vital for wellbeing
- Possible undiagnosed gluten/lactose intolerance → **YELLOW FLAG**

**Validation:**
- If there are severe symptoms (pain, diarrhea, vomiting): Suggests gastroenterology consultation
- Frequent symptoms without diagnosis: Propose a 2-week gluten elimination test

---

### 6. Injury and Discomfort History
**Question:**
> Do you have any pain or discomfort that appears when training? Is there an old injury you're afraid of reactivating, or that requires special care?

**Expected fields:**
- Pain location (joint, muscle, etc.)
- Onset context (specific movement)
- Injury history (when, type)
- Current restrictions
- Prior treatment (physiotherapy, surgery)

**Information obtained:**
- **CRITICAL for exercise adaptation:** Avoids aggravating pathologies
- Defines allowed ROM, prohibited contraction types
- Example: Unstable shoulder → avoid heavy overhead presses but allow pulling movements

**Validation:**
- If there is constant pain: Suggests prior medical evaluation
- If they describe a specific syndrome (impingement, stenosis, etc.): Adapt per protocol

**Mandatory follow-up:**
- "Which exercises cause you discomfort?"
- "Have you been to physio? What did they tell you?"

**Red flags:**
- Severe pain without diagnosis
- History of recent surgery (< 12 weeks)
- Joint limitations > 50% of ROM

---

### 7. Experience and "Toolbox"
**Question:**
> How long have you been training seriously (consistently, with a program)? What equipment do you have available: full gym, home (tell me what you have), or bodyweight only?

**Expected fields:**
- Years/months of real experience (consistent, not occasional)
- Type of gym or equipment (home gym, commercial gym, outdoors)
- Specific equipment (dumbbells, barbell, machines, none)
- Access (24/7, schedules, feasibility)

**Information obtained:**
- Determines tolerable volume (beginners saturate easily, advanced need more)
- **Base volume:** Beginner 10-15 sets/week/muscle group, advanced 15-25 sets
- Equipment dictates feasibility of key movements (squat, deadlift, press)
- Access determines schedule flexibility

**Validation:**
- If they say "10 years" but photos show sedentary behavior: Specify "consistent training"
- If they only have light weights at home for a strength goal: Requires adaptation (periodization, higher reps)

---

### 8. Rest Quality
**Question:**
> How many hours do you sleep on average? Do you wake up feeling truly rested? Do you have insomnia, night waking, or do you sleep but still feel tired?

**Expected fields:**
- Sleep hours (validate 4-12)
- Subjective quality (none/little/enough/excellent)
- Specific problems (initial insomnia, fragmented sleep, early waking)
- Factors (stress, blue light, noise, temperature)

**Information obtained:**
- **Hormones:** Without deep sleep, cortisol rises, testosterone/GH drop
- If they sleep < 6 hours: Optimal recovery is impossible → reduce intensity
- If they sleep 9-10 but still feel tired: Possible sleep apnea, depression → **RED FLAG**

**Validation:**
- Ideal: 7-9 hours with high quality
- If < 6 hours: Sleep education; periodize training with recovery phases

**Optional deep-dive:**
- "Do you train very late? Do you have caffeine after 2:00 PM?"

---

### 9. Relationship with Supplementation
**Question:**
> Are you currently taking anything (protein, vitamins, fat burners, pre-workout)? How much would you be willing to invest monthly in supplementation if necessary?

**Expected fields:**
- Current supplements (name, dose, frequency)
- Reason for use (goal, deficiency, habit)
- Maximum monthly budget (range)
- Restrictions (vegan, allergy, preference)

**Information obtained:**
- Defines whether to include ergogenics in the plan
- Realistic budget avoids an unattainable stack
- Priority: creatine, caffeine, protein > dubious fat burners
- Nutritional deficiencies detected beforehand

**Validation:**
- If they take "miracle" fat burners + restrictive caloric intake: Education needed
- If budget = 0: Supplement-free plan, emphasis on nutrition

**Red flags:**
- Use of unauthorized substances (AAS, SARMs without supervision)
- Use of pseudoscientific "detox" products

---

### 10. Real Commitment and Time
**Question:**
> How many days a week will you truly dedicate to training, without it becoming a problem in your life? How much time per session?

**Expected fields:**
- Real days/week (validate 1-7)
- Time per session in minutes (validate 15-180)
- Flexibility (fixed vs. variable)
- Known conflicts (work, family)

**Information obtained:**
- **THE FOUNDATION of adherence.** 3 days at 100% is preferable to 6 at 40%
- Defines total weekly volume (days × min × intensity)
- Identifies low-commitment periods (busy seasons)
- Realism: If they say "6 days" but work 12h/day → adjust expectations

**Validation:**
- If budget < 90 min/week: Efficiency approach (full-body, compound-heavy)
- If it varies a lot (3 random days): Requires flexible periodization

**Critical deep-dive:**
- "What would happen if you have a stressful week at work? Could you do 2 short sessions at home?"
- "Have you abandoned training before? What led to the dropout?"

---

## Red Flag Detection and Referral

### RED FLAGS (mandatory professional referral)

1. **Psychiatry/Psychology:**
   - Signs of an eating disorder: unexplained rapid weight loss, calorie obsession, extreme restriction, purging
   - Severe body dysmorphia: radically distorted perception
   - Depression: extreme fatigue, hopelessness, severe insomnia
   - Paralyzing anxiety around training

2. **Medicine:**
   - Constant pain without diagnosis
   - BMI < 13.5 or > 45
   - Unknown blood pressure (if over 40 years old)
   - Recent surgery (< 12 weeks)
   - Pre-syncope or dizziness during/after training
   - Type 1 diabetes without medical coordination

3. **Nutrition:**
   - Signs of severe malnutrition
   - Confirmed intolerance without management
   - Severe GI symptoms (chronic diarrhea, pain)

### YELLOW FLAGS (protocol adjustment)

- Sleep < 6 hours consistently
- Severe work/personal stress
- Manageable chronic injury
- Suspected undiagnosed intolerance
- Supplement budget = 0
- Training availability < 150 min/week
- Multiple old injuries

---

## Execution Instructions for Claude

### FLOW TO FOLLOW:

1. **Warm opening:**
   - Present the purpose without overwhelming
   - Emphasize that there are no "wrong" answers
   - Confidentiality of the data

2. **Ordered sequence:**
   - Respect the 0→10 order (logical construction)
   - Allow natural elaboration (don't cut short)
   - If the user gives Q3 info during Q1, note it and continue the flow

3. **Selective deep-diving:**
   - Ask follow-up questions if there is ambiguity
   - Do NOT ask everything simultaneously (feels like an interrogation)
   - Example after Q1: "Does that mean you feel you have low muscle tone or a lot of abdominal fat?"

4. **Adapted language:**
   - If the user is very technical (bodybuilder): You can use TDEE, BMR, macro ratios
   - If beginner: Simplify to "how many calories you burn", "what and when you eat"
   - Always validate the language: "Do you know what TDEE is? If not, I'll explain in 10 seconds"

5. **Handling sensitive information:**
   - Body composition, weight, injuries → Empathetic tone, without judgment
   - If the user shows discomfort: "You don't have to answer anything you don't want to. Is there any data you'd prefer not to share?"
   - Never comment on appearance

6. **Final decision:**
   - After completing the 10 Qs: Brief summary of key findings
   - Identify red flags and communicate them clearly
   - Propose next step (plan design, referral, prior education)

---

## Expected Output

### Collected Data Structure:

```json
{
  "user": {
    "name_or_username": "string",
    "registration_date": "ISO-8601"
  },
  "biometrics": {
    "age": int,
    "weight_kg": float,
    "height_cm": int,
    "bmi": float,
    "perceived_composition": "string",
    "estimated_composition": "string (based on photo if applicable)"
  },
  "goal": {
    "primary": "lose_fat | gain_muscle | performance",
    "secondary": "optional",
    "timeframe_weeks": int,
    "realistic_expectation": bool
  },
  "activity": {
    "occupation": "string",
    "neat_level": "sedentary | active | very_physical",
    "description": "string"
  },
  "nutrition": {
    "meals_per_day": int,
    "critical_foods": [{"name": "string", "frequency": "string", "context": "string"}],
    "general_pattern": "string"
  },
  "digestive_energy": {
    "bloating_frequency": "never | sometimes | always",
    "energy_crash": bool,
    "triggers": ["string"]
  },
  "injuries": [
    {
      "location": "string",
      "type": "string",
      "age": "string",
      "restriction": "string",
      "diagnosis": "string | null"
    }
  ],
  "training": {
    "consistent_years": float,
    "environment": "gym | home | outdoors | mixed",
    "equipment": ["string"]
  },
  "sleep": {
    "average_hours": float,
    "quality": "poor | fair | good | excellent",
    "problems": ["string"]
  },
  "supplementation": {
    "current": [{"name": "string", "dose": "string", "frequency": "string"}],
    "monthly_budget_usd": float | null,
    "restrictions": ["string"]
  },
  "commitment": {
    "days_per_week": int,
    "minutes_per_session": int,
    "flexibility": "fixed | flexible",
    "dropout_history": "string | null"
  },
  "flags": {
    "red": ["string"],
    "yellow": ["string"]
  },
  "initial_calculations": {
    "bmr": float,
    "estimated_tdee": float,
    "tolerable_volume_sets": int
  }
}
```

---

## Quality Validation

Before ending the interview, verify:

- [ ] All 10 questions were answered (even briefly)
- [ ] The biometric data forms a coherent profile
- [ ] The goal is specific and measurable (not vague like "be fit")
- [ ] Available time vs. goal are compatible
- [ ] Red flags were identified and communicated
- [ ] The user feels heard, not interrogated

---

## Keywords and Triggers for Claude

`fitness onboarding`, `user profiling`, `biometric intake`, `goal assessment`, `training readiness`, `new user questionnaire`, `fitness interview`, `TDEE calculation`, `adherence prediction`, `injury screening`

---

## Notes for Continuous Improvement

1. **A/B testing question 2:** Some users respond better to "How do you see yourself in 6 months?" than to a timeline
2. **Cultural adaptation:** Colloquial language varies (e.g., "snacking" vs. "grazing" vs. "eating between meals")
3. **Data validation:** Integrate with DEXA, InBody or other if the user has access
4. **Post-interview follow-up:** Summary email 24h later so they can correct data
5. **Scalability:** If the user has complex conditions, maintain a referral checklist

---

**Version:** 1.0 | **Last updated:** 2025-04-13 | **Maintainer:** FitCoachIA Team
