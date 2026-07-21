# Data Dictionary — DizzyCTA Agentic Pipeline v13.5.2

## Overview

The pipeline extracts 22 structured clinical variables from stroke-workup neuroimaging reports across four modalities (CT Head, CTA Head/Neck, CT Perfusion, MRI Brain). Variables are classified into two tiers:

- **Tier 1 (8 fields):** Publication-critical endpoints with pre-specified power targets
- **Tier 2 (14 fields):** Secondary/exploratory endpoints

---

## Tier 1 Fields

### 1. CTH_Acute_Finding
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** Any acute abnormality on CT head (hemorrhage, acute infarct, mass effect, or edema)
- **Source:** CT head report text

### 2. CTH_Acute_Type
- **Type:** Categorical (conditional on CTH_Acute_Finding = "Yes")
- **Allowed values:** `"Hemorrhage"` | `"Ischemic Infarct"` | `"Mass/Edema"` | `"Other"` | `"NA"`
- **Definition:** Specific type of acute finding
- **Note:** NA when no acute finding is present

### 3. CTH_Microvascular
- **Type:** Binary
- **Allowed values:** `"Present"` | `"Not Present"`
- **Definition:** Chronic microvascular ischemic changes (white matter disease, leukoaraiosis)
- **Note:** This is a chronic finding, NOT an acute abnormality

### 4. CTA_R_Vert (Right Vertebral Artery)
- **Type:** Ordinal (0-4)
- **Allowed values:** `0` | `1` | `2` | `3` | `4`
- **Definition:** Luminal stenosis grade of the right vertebral artery

### 5. CTA_L_Vert (Left Vertebral Artery)
- **Type:** Ordinal (0-4)
- **Allowed values:** `0` | `1` | `2` | `3` | `4`
- **Definition:** Luminal stenosis grade of the left vertebral artery

### 6. CTA_Basilar (Basilar Artery)
- **Type:** Ordinal (0-4)
- **Allowed values:** `0` | `1` | `2` | `3` | `4`
- **Definition:** Luminal stenosis grade of the basilar artery

### 7. MRI_Acute_Infarct
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** Acute or subacute infarct on MRI brain (DWI positive or restricted diffusion)
- **Note:** Triggers downstream territory/bilaterality extraction

### 8. MRI_Chronic_Infarct
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** Chronic infarct (encephalomalacia, gliosis, or chronic lacunar infarct)
- **Note:** Triggers downstream chronic territory/bilaterality extraction

---

## CTA Vessel Grading Scale

| Grade | Definition | Luminal Stenosis |
|-------|-----------|-----------------|
| 0 | No stenosis | 0% (regardless of plaque or calcification without luminal narrowing) |
| 1 | Mild stenosis | 1-49% |
| 2 | Moderate stenosis | 50-69% |
| 3 | Severe stenosis | 70-99% |
| 4 | Occlusion | 100% |
| 9 | CTA not performed (sentinel value) | N/A — see below |

**Key rule:** Grade 0 is assigned if any vessel has plaque or calcification but NO measurable luminal stenosis. Grading is based strictly on luminal stenosis, NOT plaque burden.

**Grade 9 — "not performed" sentinel:** Grade 9 is reserved exclusively for cases where the CTA was never performed at all (all 7 vessel fields are deterministically set to 9 by the pipeline, not inferred by the LLM, with evidence text `"CTA not performed"`). It does **not** mean "vessel not mentioned in an otherwise-performed CTA report" — within a performed CTA, any vessel the LLM doesn't explicitly find stenosis for defaults to grade 0 (normal), per the "unmentioned = normal" policy adopted in v13.5.x. If the LLM ever returns a stray 9 for a vessel within a performed CTA (i.e., `cta_performed = True`), a deterministic QC layer force-corrects it to 0 and raises a `model returned grade 9 on a performed CTA; forced to 0` flag — this is what the "Grade-9 leakage" QC check in `prompt_templates_reference.md` detects. Grade 9 should therefore be treated as effectively a fourth, CTA-level "not applicable" category, not a stenosis severity value, and excluded from ordinal severity statistics.

---

## Tier 2 Fields

### CTA_R_ICA / CTA_L_ICA (Carotid Arteries)
- **Type:** Ordinal (0-4), same scale as vertebral/basilar
- **Definition:** Luminal stenosis of right/left internal carotid artery

### CTA_R_MCA / CTA_L_MCA (Middle Cerebral Arteries)
- **Type:** Ordinal (0-4), same scale
- **Definition:** Luminal stenosis of right/left MCA

### CTH_Acute_Indeterminate
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** Report explicitly states CT head findings are equivocal or indeterminate

### CTP_Performed
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** CT perfusion was performed and reported

### CTP_Deficit
- **Type:** Categorical
- **Allowed values:** `"Yes"` | `"No"` | `"N/A"`
- **Definition:** Perfusion deficit identified on CTP
- **Note:** N/A when CTP not performed

### MRI_Acute_Territory
- **Type:** Categorical (conditional on MRI_Acute_Infarct = "Yes")
- **Allowed values:** `"Anterior"` | `"Posterior"` | `"Both"` | `"N/A"`
- **Definition:** Vascular territory of acute infarct

### MRI_Acute_Bilateral
- **Type:** Categorical (conditional on MRI_Acute_Infarct = "Yes")
- **Allowed values:** `"Yes"` | `"No"` | `"N/A"`
- **Definition:** Acute infarct is bilateral

### MRI_Chronic_Territory
- **Type:** Categorical (conditional on MRI_Chronic_Infarct = "Yes")
- **Allowed values:** `"Anterior"` | `"Posterior"` | `"Both"` | `"N/A"`
- **Definition:** Vascular territory of chronic infarct

### MRI_Chronic_Bilateral
- **Type:** Categorical (conditional on MRI_Chronic_Infarct = "Yes")
- **Allowed values:** `"Yes"` | `"No"` | `"N/A"`
- **Definition:** Chronic infarct is bilateral

### MRI_Other_Abnormality
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** Any other abnormality not captured by infarct fields (e.g., tumor, demyelination)

### MRI_Other_Abnormality_Type
- **Type:** Free text
- **Definition:** Description of the other abnormality

### MRI_MRA_Included
- **Type:** Binary
- **Allowed values:** `"Yes"` | `"No"`
- **Definition:** MRA sequence included in the MRI study

---

## System Fields (auto-generated)

| Field | Description |
|-------|------------|
| `ID` | Case identifier (Source ID from cohort) |
| `ED_Arrival` | Emergency department arrival datetime |
| `Time_to_CTH_hrs` | Hours from ED arrival to CT head |
| `Time_to_CTA_hrs` | Hours from ED arrival to CTA |
| `Time_to_MRI_hrs` | Hours from ED arrival to MRI |
| `Confidence_Score` | Pipeline confidence (0-100, rule-based) |
| `Confidence_Reason` | Explanation for confidence score |
| `AI_QC_Flags` | Quality-control flag(s) triggered |
| `LLM_Calls_Made` | Number of LLM API calls for this case |
| `AI_Processed` | Whether pipeline completed successfully |
| `AI_Timestamp` | Processing timestamp |

---

## Study Cohort

| Metric | Value |
|--------|-------|
| Parent cohort | 1,669 consecutive ED dizziness/vertigo patients |
| Full imaging triad (CTH + CTA + MRI) | 719 cases |
| Validation cohort (human review) | 150 unique cases |
| Enrichment cases (rare findings) | 40 curated |
| Random cases | 110 random |
| Duplicate case excluded (both reviews) | 1 (Source ID 225) |

## Statistical Plan

- **Primary metrics (6):** CTH Acute, CTH Microvascular, MRI Acute Infarct, R/L Vertebral, Basilar
- **Bonferroni alpha:** 0.05/6 = 0.0083
- **Power target:** ≥14 positive cases per endpoint
- **Null hypothesis:** H₀ = κ 0.40 (moderate agreement)
- **CI method:** Wilson score interval
