# Prompt Templates Reference — DizzyCTA v13.5.2

This document provides a structural overview of the clinical prompt templates
used in the four-agent cascade. The full prompt text is embedded in the pipeline
source code (`agentic_radiology_pipeline_v13_5_2.py`).

## System Context (all agents)

```
You are a precise clinical radiology abstraction engine.
When instructed to return JSON, return only valid raw JSON with no markdown,
no prose, and no code fences. Escape all internal quotes and line breaks
inside JSON string values.
```

## Agent 1: CT Head Abstraction

**Input:** CT head report text + clinical context
**Output Schema:** JSON with fields:
- `CTH_Acute_Finding`: "Yes" | "No"
- `CTH_Acute_Indeterminate`: "Yes" | "No"
- `CTH_Acute_Type`: "Hemorrhage" | "Ischemic Infarct" | "Mass/Edema" | "Other" | "NA"
- `CTH_Microvascular`: "Present" | "Not Present"

**Key Decision Rules:**
- Acute finding = any acute abnormality (hemorrhage, infarct, mass effect, edema)
- Microvascular disease = chronic white matter changes, NOT acute
- Indeterminate = report explicitly states findings are equivocal

## Agent 2: CTA Head/Neck Vascular Grading

**Input:** CTA report text + clinical context
**Output Schema:** JSON with 7 vessel fields (0-4 scale):
- `CTA_R_Vert`, `CTA_L_Vert`, `CTA_Basilar` (posterior circulation — Tier 1)
- `CTA_R_ICA`, `CTA_L_ICA` (anterior circulation — Tier 1)
- `CTA_R_MCA`, `CTA_L_MCA` (middle cerebral — Tier 2)

**CTA Grading Scale:**
| Grade | Definition |
|-------|-----------|
| 0 | No stenosis (regardless of plaque or calcification without luminal narrowing) |
| 1 | Mild stenosis (1-49% luminal narrowing) |
| 2 | Moderate stenosis (50-69%) |
| 3 | Severe stenosis (70-99%) |
| 4 | Occlusion (100%) |

**Key Decision Rules:**
- Grade 0 if ANY vessel has plaque/calcification but NO measurable stenosis
- Grade based strictly on luminal stenosis, NOT plaque burden
- If stenosis percentage is not explicitly stated, infer from descriptors:
  "mild" → 1, "moderate" → 2, "severe" → 3, "occluded" → 4

Also outputs:
- `CTP_Performed`: "Yes" | "No"
- `CTP_Deficit`: "Yes" | "No" | "N/A"

## Agent 3: MRI Brain Abstraction

**Input:** MRI brain report text + clinical context
**Output Schema:** JSON with fields:
- `MRI_Acute_Infarct`: "Yes" | "No"
- `MRI_Acute_Territory`: "Anterior" | "Posterior" | "Both" | "N/A"
- `MRI_Acute_Bilateral`: "Yes" | "No" | "N/A"
- `MRI_Chronic_Infarct`: "Yes" | "No"
- `MRI_Chronic_Territory`: "Anterior" | "Posterior" | "Both" | "N/A"
- `MRI_Chronic_Bilateral`: "Yes" | "No" | "N/A"
- `MRI_Other_Abnormality`: "Yes" | "No"
- `MRI_Other_Abnormality_Type`: free text (if Yes)

**Stepwise Logic (decision-tree cascade):**
1. If MRI_Acute_Infarct = "Yes" → extract Territory and Bilaterality
2. If MRI_Acute_Infarct = "No" → check for Chronic Infarct
3. If MRI_Chronic_Infarct = "Yes" → extract Chronic Territory and Bilaterality
4. Downstream variables gated behind upstream binary confirmations

## Agent 4: Synthesis

**Input:** JSON outputs from Agents 1-3 + imaging time intervals
**Output:** Clinical summary, audit quote, confidence score (0-100)

**Key Rules:**
- Cannot modify modality-specific fields from upstream agents
- Performs cross-modality consistency checks
- Flags inconsistencies via QC flags

## Heuristic QC Overlay

Independent of LLM outputs, a deterministic layer scans for:
- Unnegated abnormality language inconsistent with model classification
- Schema violations (out-of-range values, legacy hemorrhage subtypes)
- Grade-9 leakage (sentinel value appearing in final output)
- Cross-modality contamination (CTA language in MRI report, etc.)

In the final 719-case run, 65/719 cases (9.0%) triggered ≥1 QC flag.

## Four-Phase Development History

| Phase | Versions | Focus | Refinement Criterion |
|-------|----------|-------|---------------------|
| 1 | v1.0–v8 | Single-model, 30-case calibration, architectural simplification | Highest-error fields, case-by-case review |
| 2 | v8–v11 | Multi-model agreement (Gemini 2.5 Flash/Pro, GPT-5-mini) | Inter-model κ > 0.90 for Tier 1 |
| 3 | v11–v13.5.2 | Frontier model refinement (Claude 4.6, GPT-5.4, Gemini 3.5 Flash) | Schema integrity + all-field agreement |
| 4 | — | Prevalence-informed enrichment design | Wilson CI power targets met |
