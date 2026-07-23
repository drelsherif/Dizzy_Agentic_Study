#!/usr/bin/env python3
"""
DizzyCTA Agentic Pipeline v14.0.3 — Cleaned for Public Release
=============================================================

Study: A Multi-Agent Large Language Model Pipeline for Structured Abstraction
       of Stroke-Workup Neuroimaging Reports

Author: Yasir El-Sherif, MD, PhD
        Department of Neurology, Staten Island University Hospital (Northwell Health)

License: MIT (see LICENSE file)

NOTE: This code has been cleaned of all institutional credentials, API keys,
      and endpoint URLs. Replace all placeholder values (your-llm-api-endpoint,
      your-key, etc.) with your own LLM API configuration before use.

CHANGELOG — v14.0.0 (bugs found and fixed via the 15-case synthetic test set in
Dizzy_Sample_Input_SYNTHETIC.xlsx / Dizzy_Sample_Expected_Scores.xlsx; run the
synthetic set again after upgrading to confirm all three are resolved):

  1. MRI_MRA_Included negation bug (reproduced 8/8 on affected synthetic cases).
     detect_mra() matched any sentence containing the word "MRA" and returned
     Yes with that sentence as "evidence" -- including sentences that explicitly
     NEGATE it, e.g. "MRA not performed with this study." Fixed by adding
     _MRA_NEGATION_PATTERN: a matched sentence is now checked for a negation
     word/phrase near the MRA mention before being accepted as positive
     evidence. See detect_mra() and _MRA_NEGATION_PATTERN.

  2. [v14.0.0, REVERTED in v14.0.2] An earlier version of this fix made
     CTH_Acute_Indeterminate itself resolve to 'No' once a diagnostic follow-up
     MRI came back clean. This was WRONG and has been reverted:
     CTH_Acute_Indeterminate is a permanent record of what the radiologist
     actually wrote on the CT head report and must never change, in either
     direction, regardless of what MRI later shows -- only CTH_Acute_Finding
     (and CTH_Acute_Type) are resolved by follow-up MRI. Confirmed against the
     150-case human validation set: the "resolve to No" behavior regressed
     this field's accuracy from 0.890 to 0.822 across 26 real disagreements,
     because reviewers coded this field from the CTH report's own language,
     not a post-MRI-resolved status. qc_check_cth_indeterminate_resolved_by_mri()
     now only ever writes CTH_Acute_Finding/CTH_Acute_Type, never
     CTH_Acute_Indeterminate.

  3. CTH_GATE_PROMPT was over-triggering Indeterminate=Yes on generic
     technical-limitation language (e.g. "posterior fossa evaluation is
     limited by beam-hardening artifact") even when the report's own stated
     conclusion was a committed, non-hedged negative ("no definite acute
     infarct"). This let an unrelated technical caveat get backfilled into a
     false-positive CTH finding once MRI confirmed a real but separately
     located infarct. The prompt now explicitly distinguishes a generic
     image-quality caveat from genuine hedging on the acute-finding question
     itself, and only the latter should trigger Indeterminate=Yes.

  4. Reinforced (already-correct, now made more explicit) behavior: CTA/CTP
     vessel grading defaults to 0 for any vessel not individually and
     explicitly addressed by the report -- including when the CTA/CTP section
     contains real report text but that text is generic or non-specific.
     Grade 9 remains reserved exclusively for the pipeline-level case of the
     study never having been performed at all (both CTAH and CTAN cells
     genuinely blank); confirmed correct on a dedicated partial-CTA test case.

CHANGELOG — v14.0.2:

  5. Comma-boundary bug in _MRA_NEGATION_PATTERN: a report header like
     "MRI BRAIN WITHOUT CONTRAST, WITH MRA" was misread as negating MRA,
     because the 40-character negation-search window could reach across a
     comma from an unrelated "WITHOUT CONTRAST" clause. Fixed by stopping the
     window at commas. Found via synthetic re-test (SAMPLE005); confirmed
     zero occurrences of this pattern in the real 719-case cohort.

CHANGELOG — v14.0.3:

  6. MRI_Other_Abnormality was over-triggering Yes on MRA collateral-flow/
     reconstitution language tied to an already-known chronic vessel occlusion
     (e.g. "reconstitution of the right ICA/MCA via collateral pathways,
     consistent with known right ICA occlusion"). That is expected downstream
     physiology of a known occlusion, not a new brain parenchymal finding --
     vessel status belongs to the CTA/MRA fields, not Other_Abnormality. The
     prompt now explicitly excludes MRA/vessel-flow-only language from
     Other_Abnormality and requires an actual parenchymal/structural finding.
     Found via synthetic re-test (SAMPLE006); confirmed zero occurrences of
     this specific collateral-flow phrasing in the real 719-case cohort.

Pipeline development was conducted by the investigator with AI-assisted coding
tools under direct clinical supervision. All clinical decision rules, output
schemas, quality-control logic, and refinement criteria were specified by
the investigator.

Requirements: Python 3.10+, pandas, openpyxl, requests, numpy
"""

# ============================================================
#
#  AGENTIC MULTI-MODAL RADIOLOGY REPORT ABSTRACTION PIPELINE
#  Version: 13.5.1 (CTH hedge-language hard override widened: "stable"/
#  "favor chronic" chronicity words now checked against the evidence
#  phrase, and a hyperdense/thrombosed-vessel sign on CTH is now a hard
#  override to Indeterminate instead of a soft flag)
#
#  CHANGES vs v13.5.0:
#    - qc_check_cth_hedge_language: added _CTH_EVIDENCE_ONLY_CHRONICITY_WORDS
#      ("stable", "unchanged", "favor(s) chronic", "chronic in nature"),
#      checked only against the model's own extracted evidence phrase (not
#      the full report, since these are common boilerplate that could
#      describe an unrelated finding elsewhere in the same report). Added
#      _VESSEL_SIGN_WORDS (hyperdense vessel/thrombosed vessel/dense vessel
#      sign) as a hard override — this is a CTA-domain finding described
#      incidentally on CTH, not a parenchymal hemorrhage/infarct, and a
#      prior run showed a backend calling it Acute anyway despite the
#      prompt's existing guidance. Fixed 2 of 5 hemorrhage/acute-finding
#      disagreement cases found during the 74-case human-review audit
#      (SourceID 559, 564); the other 3 in that audit were the cross-modal
#      MRI-resolution logic working as designed, not a bug.
#
#  CHANGES vs v13.4.4:
#    - CTH_GATE_PROMPT / apply_cth_rules: CTH_Acute_Type no longer
#      distinguishes ICH/SAH/IVH compartment — all three collapse to a
#      single "Hemorrhage" value, matching the "keep it simple" approach
#      already used on the MRI side. This reverses the brief v13.4.x-era
#      compartment split.
#    - SDH IS NO LONGER A QUALIFYING CTH ACUTE FINDING AT ALL: subdural
#      hemorrhage is clinically an incidental/traumatic finding, not a
#      stroke-type hemorrhage. If SDH is the only acute abnormality on
#      CTH, CTH_Acute_Finding reverts to No Acute (hard Python override
#      in apply_cth_rules, not just a prompt instruction). SDH is instead
#      captured downstream via MRI_Other_Abnormality_Type, in its own
#      dedicated bucket ("SDH/Extra-axial Hemorrhage") that is explicitly
#      NOT the same category as true (parenchymal/subarachnoid/
#      intraventricular) stroke-type hemorrhage.
#    - MRI_CORE_PROMPT / MRI_OTHER_TYPES: added "SDH/Extra-axial
#      Hemorrhage" (split out of the old consolidated "Hemorrhage"
#      bucket) and "Vascular Malformation" (new category; an actively
#      bleeding malformation is still coded under its hemorrhage type,
#      not as Vascular Malformation) as new controlled values. Priority
#      order updated: Hemorrhage > SDH/Extra-axial Hemorrhage > Vascular
#      Malformation > Chronic Microvascular/White Matter Disease > ...
#    - compute_confidence, map_cth_acute (REDCap export), and the MRI-
#      resolves-CTH-indeterminate QC step all updated for the
#      compartment-agnostic Hemorrhage value.
#
#  CHANGES vs v13.4.3 (bundled into this same release):
#    - CTA_GRADING_PROMPT and normalize_cta_grades: grade 9 ("not
#      reliably assessed") is retired for any CTA that WAS performed.
#      A vessel the report never individually names, or one affected
#      by motion/artifact language without an explicit stenosis/
#      occlusion call, now defaults to grade 0 (unmentioned = normal)
#      instead of 9. Grade 9 is reserved exclusively for the case where
#      the CTA study itself was never performed at all — a genuinely
#      different situation from an individual vessel going unaddressed
#      within a report that was performed.
#    - compute_confidence: removed the per-vessel "not reliably
#      assessed (grade 9)" penalty, since that scenario no longer
#      occurs within performed studies. cta_performed is now passed in
#      explicitly by the caller rather than inferred from grade != 9
#      (that inference broke once unmentioned vessels stopped being 9).
#    - Retroactive data fix: all prior full-cohort model outputs had any
#      grade-9 vessel value (within performed CTAs) converted to 0.
#
#  CHANGES vs v13.4.2 (based on 3-model, human-reviewed disagreement
#  analysis across Claude Sonnet 4.6 / GPT-5.4 / Gemini 3.5 Flash):
#    - qc_check_cth_indeterminate_resolved_by_mri: an equivocal CTH
#      finding (Indeterminate=Yes) is now retroactively resolved to
#      Acute if the follow-up MRI confirms a real acute infarct or
#      hemorrhage, closing a loop that previously required manual
#      reviewer reconciliation.
#    - qc_check_cth_hedge_language: hedge/differential phrasing in the
#      CTH evidence phrase (e.g. "may represent," "cannot exclude,"
#      "nonspecific") is now a HARD Python override to No Acute +
#      Indeterminate=Yes, not just a prompt instruction — this closes
#      an observed backend-compliance drift (Claude called these
#      "Acute" more often than GPT-5.4/Gemini on the same prompt).
#    - CTA_GRADING_PROMPT: clarified that a general posterior-
#      circulation statement (e.g. "vertebrobasilar system patent")
#      is a valid basilar assessment (grade 0), not grounds for
#      grade 9 — fixes an observed GPT-5.4-specific over-flagging
#      pattern on CTA_Basilar.
#    - Fixed a bug in the new MRI-resolution QC: CTH_Acute_Type no
#      longer has a plain "Hemorrhage" value post-ICH/SDH/SAH/IVH
#      split; resolved-by-MRI hemorrhage cases now default to ICH
#      (most common compartment) with an explicit "verify compartment"
#      QC flag rather than writing a non-conforming schema value.
#
#  Description:
#    Structured extraction of CT Head, CTA Head/Neck, CT Perfusion,
#    and MRI Brain reports through enterprise LLM API gateway.
#
#  V13.3 ARCHITECTURE:
#    - Agent 1: CTH abstraction (definite acute, indeterminate acute,
#      acute type, microvascular disease).
#    - Agent 2: CTA grading for seven vessels, with evidence only for
#      grades 1-4 or technically unassessed grade 9.
#    - Agent 3: CTP interpretation only when perfusion terminology is
#      detected. Final radiologist interpretation overrides isolated
#      automated perfusion values.
#    - Agent 4: MRI core abstraction (quality, acute infarct, chronic
#      infarct, and other intracranial abnormality). Acute and chronic
#      infarcts are assessed independently.
#    - Agent 5: Acute MRI localization only when acute infarct is Yes.
#    - Agent 6: Chronic MRI localization only when chronic infarct is Yes.
#
#  DETERMINISTIC FEATURES:
#    - MRI MRA presence is derived from explicit MRA/TOF terminology.
#    - CTA grade-1 QC is negation-aware and does not require adjacent
#      severity/stenosis wording.
#    - MRI abnormality QC is sentence-level and negation-aware.
#    - CTH, CTP, CTA, and MRI outputs are normalized to the allowed
#      schema before export.
#    - No routine critic/resolver agent is used; difficult outputs are
#      flagged for review rather than repeatedly re-queried.
#
#  Typical case: 3-4 LLM calls. Positive acute/chronic MRI branches
#  add one localization call each. Maximum: 6 calls.
#
#  Requirements:
#    - Google Colab (recommended) or Python 3.10+ environment
#    - Google Drive (for persistent storage and checkpointing)
#    - LLM API key (see SETUP INSTRUCTIONS below)
#    - Input file: Excel or CSV with radiology report columns
#
#  License:
#    [Your license here, e.g. MIT, CC BY 4.0]
#
# ============================================================
#
#  ██████████████████████████████████████████████████████████
#  ██                                                      ██
#  ██   SETUP INSTRUCTIONS — READ BEFORE RUNNING          ██
#  ██                                                      ██
#  ██████████████████████████████████████████████████████████
#
#  STEP 1 — Install dependencies
#    In Google Colab, run this in its own cell first:
#      !pip install -q openpyxl tqdm
#
#  STEP 2 — API Key
#    This pipeline uses Google Gemini via REST API.
#    Obtain a free API key at: https://aistudio.google.com/app/apikey
#
#    Option A (recommended for Colab):
#      Store your key in environment variables (left sidebar → key icon)
#      Name the secret: YOUR_SECRET_NAME  ← update line 94
#
#    Option B (fallback):
#      The pipeline will prompt you to paste the key at runtime.
#      Do NOT hard-code your key in this file.
#
#  STEP 3 — Prepare your input file
#    Your input file (Excel or CSV) must contain these columns:
#      - ID                    : Unique patient/encounter identifier
#      - ED Arrival            : ED arrival datetime
#      - First CTH Performed   : CT Head acquisition datetime
#      - First CTH Result      : CT Head report text
#      - First CTAH Performed  : CTA Head acquisition datetime
#      - First CTAH Result     : CTA Head report text
#      - First CTAN Result     : CTA Neck report text
#      - First MRB Performed   : MRI Brain acquisition datetime
#      - First MRB Result      : MRI Brain report text
#
#    Column names must match exactly (case-sensitive).
#    Rename your columns before running if needed.
#
#    IMPORTANT — if a study was NOT performed for a given case:
#      Leave the corresponding "Result" cell(s) truly BLANK/empty (or NaN).
#      Do NOT write descriptive text like "Not performed", "Deferred", or
#      "N/A" into the cell. The pipeline determines whether a modality was
#      performed at all by checking whether the cell is empty — it does NOT
#      parse free-text "not performed" narratives. If CTA Head/Neck was not
#      done, leave BOTH "First CTAH Result" and "First CTAN Result" blank;
#      this is what triggers the deterministic grade-9 ("not performed")
#      sentinel on all 7 vessel fields rather than the LLM being asked to
#      grade a report that doesn't exist. A free-text "not performed" note
#      left in the cell will instead be sent to the LLM as if it were a
#      real (if unusual) report, and will typically come back graded 0
#      (normal) rather than 9 — silently misclassifying the case.
#
#  STEP 4 — Update CONFIGURATION section (Cell 3 below)
#    Fill in all placeholders marked with  ← UPDATE THIS
#
#  STEP 5 — Choose run mode
#    TEST_MODE = True   → processes first 10 rows only (recommended first)
#    TEST_MODE = False  → processes entire dataset
#
#  STEP 6 — Run all cells in order
#    After a clean test run, set TEST_MODE = False and re-run.
#    If interrupted, simply re-run — completed rows are skipped.
#
# ============================================================


# ── CELL 1: Install dependencies ─────────────────────────────
# Run this cell alone before running anything else.
# Paste into its own Colab cell and execute:
#
#   !pip install -q openpyxl tqdm
#


# ── CELL 2: Imports ──────────────────────────────────────────
import pandas as pd
import requests
from getpass import getpass
import time, json, os, traceback, sys, base64
from datetime import datetime
from tqdm.auto import tqdm

# v14.0.0: load a .env file from the current working directory if one exists, so
# LLM_API_KEY / LLM_AUTH_ID / LLM_API_URL / LLM_MODEL / DIZZY_INPUT_FILE / etc. can be
# set once in a .env file instead of re-exported every terminal session. This only fills
# in variables that are NOT already set in the environment (override=False), so an
# explicit `export` still takes precedence over the .env file if both are present.
# Requires `pip install python-dotenv` (see requirements.txt). If python-dotenv is not
# installed, this is silently skipped and the pipeline falls back to plain os.environ /
# --api-key CLI args / interactive getpass prompt exactly as before -- nothing breaks.
try:
    from dotenv import load_dotenv
    _env_loaded = load_dotenv(override=False)
    if _env_loaded:
        print("✅ Loaded .env file from current directory.")
except ImportError:
    pass

# Terminal-safe replacement for IPython display
def display(x=None, *args, **kwargs):
    if x is not None:
        print(x.to_string(index=False) if hasattr(x, 'to_string') else x)

print("✅ Libraries loaded.")


# ██████████████████████████████████████████████████████████
# ██                                                      ██
# ██   CELL 3: CONFIGURATION — UPDATE ALL PLACEHOLDERS   ██
# ██                                                      ██
# ██████████████████████████████████████████████████████████

# ── Input file ───────────────────────────────────────────────
# Path to your source data file on Google Drive.
# Supports .xlsx or .csv (update read_excel/read_csv below accordingly)
INPUT_FILE_PATH = os.environ.get('DIZZY_INPUT_FILE', 'Dizzy_Deidentified_all.xlsx')
#                                          ↑ UPDATE THIS    ↑ UPDATE THIS

# ── Output files (created automatically) ─────────────────────
OUTPUT_EXCEL_PATH = os.environ.get('DIZZY_OUTPUT_EXCEL', 'Dizzy_agentic_output_v13_3.xlsx')
#                                             ↑ UPDATE THIS  ↑ UPDATE THIS
REDCAP_EXPORT_PATH = os.environ.get('DIZZY_REDCAP_CSV', 'Dizzy_redcap_import_v13_3.csv')
#                                              ↑ UPDATE THIS ↑ UPDATE THIS
ERROR_LOG_PATH = os.environ.get('DIZZY_ERROR_LOG', 'Dizzy_error_log_v13_3.csv')
#                                          ↑ UPDATE THIS

# ── LLM Model Configuration ──────────────────────────────────
# This pipeline uses Google Gemini 2.5 Flash.
# To use a different Gemini model, update the model name below.
# Available models: https://ai.google.dev/gemini-api/docs/models
LLM_MODEL_NAME = 'gemini-2.5-flash'
#                 ↑ UPDATE THIS if using a different model

# environment variable name where your API key is stored.
# In Colab: export LLM_API_KEY="your-key".
API_SECRET_NAME = os.environ.get('GEMINI_API_SECRET_NAME', 'GEMINI_API_KEY')
#                  ↑ UPDATE THIS — must match your environment variable name exactly

# ── Run settings ─────────────────────────────────────────────
TEST_MODE    = True   # ← Set True for first 10 rows, False for full dataset
CHECKPOINT_N = 10     # Save progress every N rows (increase for large datasets)
MAX_RETRIES  = 3      # API call retry attempts before marking row as error
SLEEP_SEC    = 0.8    # Seconds between sub-calls within one patient record
START_IDX    = 0      # Row index to start from (change to resume, e.g. 450)

# ── Column name mapping ───────────────────────────────────────
# If your input file uses different column names, update these.
# Keys are used internally; values must match your file's column headers exactly.
COL_ID            = 'ID'
COL_ARRIVAL       = 'ED Arrival'
COL_CTH_TIME      = 'First CTH Performed'
COL_CTH_REPORT    = 'First CTH Result'
COL_CTAH_TIME     = 'First CTAH Performed'
COL_CTAH_REPORT   = 'First CTAH Result'
COL_CTAN_REPORT   = 'First CTAN Result'
COL_MRI_TIME      = 'First MRB Performed'
COL_MRI_REPORT    = 'First MRB Result'


# ── CELL 4: Local terminal + AI Hub API setup ─────────────────────────
# Terminal-ready version: no Google Colab or Google Drive dependency.
# Supports a enterprise AI Hub endpoint through environment variables:
#   export LLM_API_KEY="..."
#   export LLM_AUTH_ID="..."
#   export LLM_API_URL="https://your-llm-api-endpoint.example.com/generative"  # AI Hub generic LLM route
# Optional:
#   #   export LLM_MODEL="gemini-2.5-flash"  # or another model listed by AI Hub

LLM_API_URL = os.environ.get('LLM_API_URL', 'https://your-llm-api-endpoint.example.com/generative')
LLM_API_KEY = None
LLM_AUTH_ID = None
LLM_MODEL_NAME = os.environ.get('LLM_MODEL', os.environ.get('LLM_MODEL_NAME', 'gemini-2.5-flash'))


def _first_present_json_path(obj, paths):
    """Returns the first value found from a list of nested-key paths."""
    for path in paths:
        cur = obj
        ok = True
        for key in path:
            if isinstance(cur, list) and isinstance(key, int) and len(cur) > key:
                cur = cur[key]
            elif isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return None


def get_api_credentials(cli_key: str | None = None, cli_ad_object_id: str | None = None):
    """Loads AI Hub API key and AD object ID from CLI args or environment variables."""
    key = (cli_key or os.environ.get('LLM_API_KEY') or '').strip()
    ad_object_id = (cli_ad_object_id or os.environ.get('LLM_AUTH_ID') or '').strip()

    if not key:
        key = getpass("Paste your LLM API key (input hidden): ").strip()
    if not ad_object_id:
        ad_object_id = getpass("Paste your auth ID (input hidden): ").strip()
    return key, ad_object_id


def configure_llm(api_key: str | None = None, ad_object_id: str | None = None,
                  api_url: str | None = None, model: str | None = None):
    """Configures the enterprise AI Hub endpoint."""
    global LLM_API_KEY, LLM_AUTH_ID, LLM_API_URL, LLM_MODEL_NAME
    LLM_API_KEY, LLM_AUTH_ID = get_api_credentials(api_key, ad_object_id)
    if api_url:
        LLM_API_URL = api_url.rstrip('/')
    if model:
        LLM_MODEL_NAME = model
    print(f"✅ LLM configured through AI Hub: {LLM_API_URL}")
    print(f"✅ Model/deployment: {LLM_MODEL_NAME}")


def _b64(text: str) -> str:
    """AI Hub /generative expects base64-encoded prompt/context strings."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _aih_headers():
    """Headers per AI Hub OpenAPI spec: X-API-Key in the request header."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Key": LLM_API_KEY,
    }


def call_llm(prompt: str) -> str:
    """
    Sends a prompt to enterprise LLM API gateway using the documented generic LLM route:
      POST https://your-llm-api-endpoint.example.com/generative

    The OpenAPI schema requires:
      - ad_object_id
      - models: [model_name]
      - prompt: base64-encoded input text

    It also supports optional base64-encoded context and advanced settings.
    """
    if LLM_API_KEY is None or LLM_AUTH_ID is None:
        configure_llm()

    system_context = (
        "You are a precise clinical radiology abstraction engine. "
        "When instructed to return JSON, return only valid raw JSON with no markdown, no prose, and no code fences. Escape all internal quotes and line breaks inside JSON string values."
    )

    advanced_settings = {
        "temperature": 0,
        "max_tokens": 2000,
    }
    # Claude models (via this gateway's Vertex passthrough) reject requests that set both
    # temperature and top_p at once ("cannot both be specified for this model"). Gemini/GPT
    # accept both, so only add top_p for non-Claude models.
    if not LLM_MODEL_NAME.lower().startswith('claude'):
        advanced_settings["top_p"] = 0.95

    payload = {
        "ad_object_id": LLM_AUTH_ID,
        "models": [LLM_MODEL_NAME],
        "context": _b64(system_context),
        "prompt": _b64(prompt),
        "advanced": advanced_settings,
    }

    response = requests.post(LLM_API_URL, headers=_aih_headers(), json=payload, timeout=180)
    if not response.ok:
        raise RuntimeError(
            f"AI Hub request failed: HTTP {response.status_code}\n"
            f"URL: {LLM_API_URL}\n"
            f"Response: {response.text[:1500]}"
        )
    data = response.json()

    # Documented AI Hub /generative shape: data.generative_responses[0].response
    text = _first_present_json_path(data, [
        ["data", "generative_responses", 0, "response"],
        ["generative_responses", 0, "response"],
        ["data", "response"],
        ["response"],
        ["result"],
        ["content"],
        # Fallbacks for OpenAI-like wrappers, if AI Hub later adds them
        ["choices", 0, "message", "content"],
        ["choices", 0, "text"],
    ])

    if text is None:
        raise RuntimeError(
            f"Could not find model text in AI Hub response. Top-level keys: {list(data.keys())}. "
            f"Response preview: {str(data)[:1000]}"
        )

    # If the selected model returned an error inside the normal 200 payload, surface it.
    inner_error = _first_present_json_path(data, [["data", "generative_responses", 0, "has_error"]])
    if inner_error is True:
        raise RuntimeError(f"AI Hub model returned has_error=True. Response: {str(data)[:1500]}")

    return text

# ── CELL 5: JSON parser ───────────────────────────────────────
def _extract_json_text(text: str) -> str:
    """Extract the most likely JSON object from model output."""
    text = str(text).strip()
    if '```' in text:
        for part in text.split('```'):
            part = part.strip()
            if part.lower().startswith('json'):
                part = part[4:].strip()
            if part.startswith('{'):
                text = part
                break
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text.strip()


def parse_json(text: str) -> dict:
    """
    Robustly extracts JSON from LLM output.
    Handles markdown fences and minor formatting drift.
    If this still fails, call_model() will ask the model to repair the JSON.
    """
    text = _extract_json_text(text)
    attempts = [text]
    # Minor fallback for rare single-quoted object output.
    attempts.append(text.replace("'", '"'))
    last_error = None
    for candidate in attempts:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
    raise last_error


def repair_json_with_llm(raw_text: str, label: str) -> dict:
    """
    Uses the same AI Hub model to repair malformed JSON produced by the model.
    This specifically addresses occasional unescaped quotes/newlines in string fields.
    """
    repair_prompt = f"""
Repair the following malformed JSON-like output into STRICT VALID JSON.
Return ONLY one raw JSON object. No markdown. No prose.
Preserve all keys and values as closely as possible.
Escape internal quotation marks and replace line breaks inside strings with spaces.

MALFORMED OUTPUT:
{raw_text}
"""
    repaired = call_llm(repair_prompt)
    return parse_json(repaired)


def save_raw_llm_failure(label: str, raw_text: str):
    """Save raw malformed model output for auditing/debugging without PHI redaction changes."""
    try:
        os.makedirs("llm_raw_failures", exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        path = os.path.join("llm_raw_failures", f"{ts}_{label}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(raw_text))
        tqdm.write(f"    🧾 Raw malformed output saved: {path}")
    except Exception:
        pass


# ── CELL 6: Utility functions ─────────────────────────────────
def safe_get(row: pd.Series, col: str) -> str:
    """Returns report text or 'N/A' if missing or blank."""
    val = row.get(col, None)
    if pd.isna(val) or str(val).strip() in ['', 'nan']:
        return 'N/A'
    return str(val).strip()

def calc_hours(arrival, scan_time) -> float | None:
    """
    Returns hours between ED arrival and imaging acquisition.
    Returns None if either timestamp is missing or unparseable.
    """
    try:
        arr = pd.to_datetime(arrival)
        scn = pd.to_datetime(scan_time)
        return round((scn - arr).total_seconds() / 3600, 2)
    except Exception:
        return None

def call_model(prompt: str, label: str) -> dict:
    """
    Calls the LLM with retry and exponential backoff.
    If the API succeeds but JSON parsing fails, performs one JSON-repair call before retrying.
    label: short descriptor shown in progress output (e.g. 'CTH').
    """
    for attempt in range(1, MAX_RETRIES + 1):
        raw = None
        try:
            raw = call_llm(prompt)
            try:
                return parse_json(raw)
            except json.JSONDecodeError as je:
                tqdm.write(f"    🛠️  [{label}] JSON repair after parse error: {je}")
                try:
                    return repair_json_with_llm(raw, label)
                except Exception as repair_error:
                    save_raw_llm_failure(label, raw)
                    raise repair_error
        except Exception as e:
            tqdm.write(f"    ⚠️  [{label}] attempt {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s


# ── CELL 6B: Deterministic heuristic QC checks ────────────────
#
# These run in plain Python AFTER the relevant agent(s) complete. Per
# the v12 outline, most of the accuracy work has already moved INTO
# the prompts (the CTA 6-step tree, the chronic-infarct location gate,
# the CTH IMPRESSION-override instruction) — the Python layer here is
# a second, independent check that enforces the same rules even if
# the model doesn't follow its own instructions, and never trusts a
# positive/abnormal finding that isn't backed by a verbatim evidence
# quote.

import re

_TECH_LIMITATION_WORDS = re.compile(
    r'\b(limited by|degrad\w+|suboptimal|nondiagnostic|non-diagnostic|artifact limits|'
    r'motion artifact|streak artifact|technically limited|study is limited)\b', re.IGNORECASE)

_CTP_PERFORMED_WORDS = re.compile(
    r'\b(perfusion|penumbra|core infarct|\bcbf\b|\bcbv\b|\bmtt\b|\btmax\b|time[- ]to[- ]max)\b',
    re.IGNORECASE)

_CTH_NO_ACUTE_IMPRESSION_WORDS = re.compile(
    r'\bno (?:acute |evidence of acute )?(?:intracranial )?(?:pathology|hemorrhage|infarct|abnormality)\b',
    re.IGNORECASE)

_STENOSIS_WORDS = re.compile(
    r'(?:\b(?:mild|moderate|severe|critical|high[- ]grade|near[- ]occlusion)\s*'
    r'(?:atherosclerotic\s*)?(?:stenos(?:is|es)|narrow(?:ing|ed)?)\b|'
    r'\b(?:stenos(?:is|es)|narrow(?:ing|ed)?|flow[- ]?limiting)\b)',
    re.IGNORECASE)
_STENOSIS_PERCENT = re.compile(
    r'\b\d{1,3}\s*%|\b\d{1,3}\s*-\s*\d{1,3}\s*%', re.IGNORECASE)
_NEGATED_STENOSIS = re.compile(
    r'\b(no|without|absen(?:t|ce)(?:\s+of)?|not|negative for|excludes?)\b'
    r'[^.]{0,30}(?:\b(?:stenos(?:is|es)|narrow(?:ing|ed)?)\b|'
    r'\b(?:mild|moderate|severe|critical)\s*(?:stenos(?:is|es)|narrow(?:ing|ed)?)\b)',
    re.IGNORECASE)
_PLAQUE_WITHOUT_STENOSIS_WORDS = re.compile(
    r'\b(plaque|calcificat\w+|atherosclero\w+|irregularity|ectasia|tortuos\w+)\b',
    re.IGNORECASE)

_MRI_ABNORMAL_WORDS = re.compile(
    r'\b(infarct\w*|encephalomalacia|microvascular|white matter|hemorrhage|blood products?|mass effect|'
    r'mass|edema|hydrocephalus|atrophy|volume loss|subdural|demyelinat\w*|abnormal enhancement)\b',
    re.IGNORECASE)
_MRI_NEGATION_CUE = re.compile(
    r'\b(no|without|negative for|no evidence of|absence of|not|excludes?)\b', re.IGNORECASE)

def _has_unnegated_abnormality(text: str) -> bool:
    """Detect explicit intracranial abnormality language with sentence-level negation handling."""
    if not text or text == 'N/A':
        return False
    collapsed = re.sub(r'\s+', ' ', str(text))
    for sentence in re.split(r'(?<=[.!?])\s+', collapsed):
        for match in _MRI_ABNORMAL_WORDS.finditer(sentence):
            preceding = sentence[:match.start()]
            if not _MRI_NEGATION_CUE.search(preceding):
                return True
    return False


def is_ctp_likely_performed(ctah_text: str, ctan_text: str) -> bool:
    """
    Zero-cost Python pre-gate for Agent 3 (CTP). This dataset has no
    dedicated CTP-performed chart field (CTP is embedded in the CTA
    Head report, same as v10/v11) — so instead of always calling
    Agent 3, a cheap keyword scan decides whether it's even worth an
    LLM call. Extends the cascade's "no call when inapplicable"
    principle to this agent too.
    """
    text = f"{ctah_text or ''} {ctan_text or ''}"
    return bool(_CTP_PERFORMED_WORDS.search(text))


def qc_check_cta_grade1(cta: dict, flags: list) -> dict:
    """
    Priority 1 safety net. Agent 2's prompt already carries the 6-step
    decision tree, but this re-derives Grade 1 independently from each
    vessel's own evidence phrase: if the phrase only shows plaque/wall
    disease language with no stenosis-percent or stenosis-severity
    wording, the grade is downshifted to 0 and flagged.
    """
    vessels = {
        'CTA_R_Vert': 'CTA_R_Vert_Evidence', 'CTA_L_Vert': 'CTA_L_Vert_Evidence',
        'CTA_Basilar': 'CTA_Basilar_Evidence', 'CTA_R_ICA': 'CTA_R_ICA_Evidence',
        'CTA_L_ICA': 'CTA_L_ICA_Evidence', 'CTA_R_MCA': 'CTA_R_MCA_Evidence',
        'CTA_L_MCA': 'CTA_L_MCA_Evidence',
    }
    for grade_key, evidence_key in vessels.items():
        try:
            grade = int(cta.get(grade_key, 0))
        except (TypeError, ValueError):
            continue
        if grade != 1:
            continue
        phrase = str(cta.get(evidence_key, '')).strip()
        if not phrase or phrase.lower() == 'not mentioned':
            continue  # nothing to check the grade against — leave the model's answer alone
        has_stenosis_mention = bool(_STENOSIS_WORDS.search(phrase) or _STENOSIS_PERCENT.search(phrase))
        is_negated = bool(_NEGATED_STENOSIS.search(phrase))
        has_stenosis_language = has_stenosis_mention and not is_negated
        only_wall_disease = bool(_PLAQUE_WITHOUT_STENOSIS_WORDS.search(phrase)) and not has_stenosis_language
        if only_wall_disease:
            flags.append(f"{grade_key} downgraded 1->0: evidence phrase "
                          f"('{phrase}') describes wall disease without stenosis wording")
            cta[grade_key] = 0
    return cta


_OCCLUSION_WORDS = re.compile(
    r'\b(occlud\w*|occlusion|no flow|absen(?:t|ce) of flow|absent flow[- ]?void|'
    r'absent (?:proximal |distal )?(?:opacification|visualization|filling)|'
    r'reconstitut\w*|no antegrade flow|complete(?:ly)? occlu\w*)\b', re.IGNORECASE)


def qc_check_cta_grade4(cta: dict, flags: list) -> dict:
    """
    Safety net paired with qc_check_cta_grade1, in the other direction: if a
    vessel's own evidence phrase contains explicit occlusion language (no
    flow, absent visualization, reconstitution, etc.) but the model graded
    it below 4, upgrade to 4 and flag it. Occlusion language is frequently
    understated in reports (e.g. "absent proximal visualization" rather than
    the word "occlusion"), which is the failure mode this catches.
    """
    vessels = {
        'CTA_R_Vert': 'CTA_R_Vert_Evidence', 'CTA_L_Vert': 'CTA_L_Vert_Evidence',
        'CTA_Basilar': 'CTA_Basilar_Evidence', 'CTA_R_ICA': 'CTA_R_ICA_Evidence',
        'CTA_L_ICA': 'CTA_L_ICA_Evidence', 'CTA_R_MCA': 'CTA_R_MCA_Evidence',
        'CTA_L_MCA': 'CTA_L_MCA_Evidence',
    }
    for grade_key, evidence_key in vessels.items():
        try:
            grade = int(cta.get(grade_key, 0))
        except (TypeError, ValueError):
            continue
        if grade == 4 or grade == 9:
            continue
        phrase = str(cta.get(evidence_key, '')).strip()
        if not phrase or phrase.lower() == 'not mentioned':
            continue
        if _OCCLUSION_WORDS.search(phrase):
            flags.append(f"{grade_key} upgraded {grade}->4: evidence phrase "
                          f"('{phrase}') describes occlusion/no-flow/reconstitution language")
            cta[grade_key] = 4
    return cta


def qc_check_chronic_location_gate(mri: dict, flags: list) -> dict:
    """
    Priority 2, enforced in Python regardless of whether Agent 7 (the
    LLM) actually followed its own mandatory-location instruction.
    MRI_Chronic_Infarct="Yes" without a named MRI_Chronic_Location is
    not a valid Yes — force-override to "No" and flag it. This MUST
    run before the pipeline controller decides whether to call
    Agents 8/9, since an overridden "No" means those don't fire.
    """
    if str(mri.get('MRI_Chronic_Infarct', '')).strip() == 'Yes':
        location = str(mri.get('MRI_Chronic_Location', '')).strip()
        evidence = str(mri.get('MRI_Chronic_Evidence', '')).strip()
        if not location or location in ('N/A', 'None') or not evidence or evidence in ('N/A', 'None'):
            flags.append("MRI_Chronic_Infarct overridden Yes->No: no named anatomic location "
                          "and/or verbatim chronicity quote provided (mandatory location gate)")
            mri['MRI_Chronic_Infarct'] = 'No'
            mri['MRI_Chronic_Location'] = 'N/A'
    return mri


def qc_check_cth_microvascular_evidence(cth: dict, flags: list) -> dict:
    """CTH_Microvascular="Present" requires actual keyword evidence, not a blank/placeholder quote."""
    if str(cth.get('CTH_Microvascular', '')).strip() == 'Present':
        ev = str(cth.get('CTH_Microvascular_Evidence', '')).strip().lower()
        if not ev or ev in ('not mentioned', 'n/a', 'none'):
            flags.append("CTH_Microvascular overridden Present->Not Present: no keyword evidence quote provided")
            cth['CTH_Microvascular'] = 'Not Present'
    return cth


def qc_check_bilateral_territory_note(mri: dict, prefix: str, flags: list) -> dict:
    """
    Informational only (per outline Rule 5) — does NOT override.
    Bilateral=Yes with a single (non-Both) territory is clinically
    possible (e.g. bilateral cerebellar/PICA infarcts are still
    "Posterior" only), so this just flags it for a reviewer's eye.
    """
    bilateral_key = f"MRI_{prefix}_Bilateral"
    territory_key = f"MRI_{prefix}_Territory"
    if (str(mri.get(bilateral_key, '')).strip() == 'Yes' and
            str(mri.get(territory_key, '')).strip() in ('Anterior', 'Posterior')):
        flags.append(f"{bilateral_key}=Yes but {territory_key}="
                      f"{mri.get(territory_key)} (single circulation) — verify, not overridden")
    return mri


def qc_check_cth_impression_override_conflict(cth: dict, cth_text: str, flags: list) -> dict:
    """
    Soft, non-overriding heuristic supporting Priority 3. If "no acute
    [pathology/hemorrhage/infarct/abnormality]"-type language appears
    anywhere in the CTH text but the model still answered "Acute", it's
    flagged for a reviewer rather than auto-corrected — a genuine acute
    finding can coexist with normal-sounding boilerplate elsewhere in
    the same report (e.g. "no acute hemorrhage" + a separate acute
    infarct), so this is not safe to override automatically.
    """
    if str(cth.get('CTH_Acute_Finding', '')).strip() == 'Acute' and cth_text and cth_text != 'N/A':
        if _CTH_NO_ACUTE_IMPRESSION_WORDS.search(cth_text):
            flags.append("CTH_Acute_Finding=Acute but 'no acute ...' language also present in report text "
                          "— verify IMPRESSION vs FINDINGS, not overridden")
    return cth


# Hedge/differential phrasing the CTH prompt already instructs the model to treat as
# No Acute + Indeterminate=Yes. Model compliance drifts across backends (Claude in
# particular calls these "Acute" more often than GPT/Gemini on the same prompt), so this
# is a HARD override, not a soft flag — unlike qc_check_cth_impression_override_conflict.
_CTH_HEDGE_WORDS = re.compile(
    r'\b(may represent|possibly|cannot exclude|can\'?t exclude|not exclude|equivocal|'
    r'differential (?:includes?|consideration)|considerations? include|versus|vs\.?\s|'
    r'probably represent|likely represent|nonspecific|non-specific|indeterminate|'
    r'recommend(?:ed|s)? (?:further|additional) (?:evaluation|imaging|workup)|'
    r'age[- ]indeterminate|could represent|compatible with (?:either|artifact))\b',
    re.IGNORECASE)

# Chronicity words ("stable", "unchanged") are common boilerplate that often describes an
# UNRELATED finding elsewhere in the same report (e.g. "stable postoperative changes" next to a
# genuinely new hemorrhage) — too risky to scan against the whole report, so these are only
# checked against the model's own extracted evidence phrase, never the full report text.
_CTH_EVIDENCE_ONLY_CHRONICITY_WORDS = re.compile(
    r'\b(stable|unchanged|favor(?:s|ing)? chronic|chronic in nature)\b', re.IGNORECASE)

# A hyperdense-vessel/thrombosed-vessel sign on CTH is a CTA-domain finding being described
# incidentally on the noncontrast head CT, not a parenchymal hemorrhage or infarct — the prompt
# already instructs Indeterminate=Yes for this pattern, but a v13.5.0 case showed a backend
# calling it Acute anyway, so this is now also a hard Python override.
_VESSEL_SIGN_WORDS = re.compile(
    r'\b(hyperdense (?:vessel|artery|mca|basilar)|thrombosed vessel|dense (?:vessel|artery) sign|'
    r'vessel sign)\b', re.IGNORECASE)


def qc_check_cth_hedge_language(cth: dict, cth_text: str, flags: list) -> dict:
    """
    Hard override, tightening Priority 3. If CTH_Acute_Finding=Acute:
    - Hedge/differential language (may represent, cannot exclude, age-indeterminate, etc.) is
      checked against BOTH the model's own extracted evidence phrase AND the full CTH report
      text, since the model's evidence extraction sometimes drops the qualifying word (e.g.
      pulls "lacunar infarct in the right basal ganglia" but omits the "age indeterminate"
      qualifier the radiologist used for that same finding).
    - Chronicity words ("stable", "unchanged", "favor chronic") are checked ONLY against the
      evidence phrase, not the full report, since they're common boilerplate that could
      describe an unrelated finding elsewhere in the same report.
    - A hyperdense/thrombosed-vessel sign described on CTH (a CTA-domain finding, not a
      parenchymal hemorrhage/infarct) is checked against both evidence and full text.
    This dataset always has a follow-up MRI, so an equivocal CTH finding is meant to be
    deferred, not called Acute on the strength of a hedge.
    """
    if str(cth.get('CTH_Acute_Finding', '')).strip() != 'Acute':
        return cth
    evidence = str(cth.get('CTH_Acute_Evidence', '') or '')
    combined = evidence + ' ' + str(cth_text or '')
    hedge_hit = _CTH_HEDGE_WORDS.search(combined)
    chronicity_hit = _CTH_EVIDENCE_ONLY_CHRONICITY_WORDS.search(evidence) if not hedge_hit else None
    vessel_hit = _VESSEL_SIGN_WORDS.search(combined) if not (hedge_hit or chronicity_hit) else None
    hit = hedge_hit or chronicity_hit or vessel_hit
    if hit:
        if hedge_hit:
            reason = f"hedge/differential phrase '{hedge_hit.group(0)}'"
        elif chronicity_hit:
            reason = f"chronicity phrase '{chronicity_hit.group(0)}' in the model's own evidence phrase"
        else:
            reason = f"hyperdense/thrombosed-vessel sign '{vessel_hit.group(0)}' (CTA-domain finding, not parenchymal)"
        flags.append(f"CTH_Acute_Finding overridden Acute->No Acute (Indeterminate->Yes): {reason} "
                      f"(evidence phrase: '{evidence.strip()}')")
        cth['CTH_Acute_Finding'] = 'No Acute'
        cth['CTH_Acute_Indeterminate'] = 'Yes'
        cth['CTH_Acute_Type'] = 'N/A'
    return cth


def qc_check_cth_indeterminate_resolved_by_mri(cth: dict, mri: dict, flags: list) -> dict:
    """
    Closes the loop this dataset's design relies on: an equivocal CTH finding
    (Indeterminate=Yes) is deliberately left as CTH_Acute_Finding=No Acute on CTH itself,
    because the follow-up MRI is expected to settle whether there's a real acute finding.
    If the MRI subsequently confirms a real, definite finding (an acute infarct, or a
    hemorrhage), retroactively resolve CTH_Acute_Finding (and CTH_Acute_Type) to reflect
    that, instead of leaving it as a permanent "No Acute" that a reviewer has to manually
    reconcile against a positive MRI in the same case.

    v14.0.2 CORRECTION: an earlier v14.0.0 change made this resolve CTH_Acute_Indeterminate
    itself to 'No' (in both the positive- and a since-reverted negative-resolution branch).
    That was wrong. CTH_Acute_Indeterminate is a permanent, unchanged record of what the
    radiologist actually wrote on the CT head report -- it documents that the radiologist
    used equivocal/hedging language, and that fact doesn't stop being true just because a
    later, different study (MRI) answers the underlying clinical question. Only
    CTH_Acute_Finding and CTH_Acute_Type are resolved by this function; CTH_Acute_Indeterminate
    is never touched here, in either direction, confirmed against human-reviewer ground
    truth (the 150-case validation set was coded from the CTH report's own language, not a
    post-MRI-resolved status; touching this field regressed that field's accuracy from 0.890
    to 0.822 and has been reverted).
    """
    if str(cth.get('CTH_Acute_Indeterminate', '')).strip() != 'Yes':
        return cth
    mri_acute = str(mri.get('MRI_Acute_Infarct', '')).strip() == 'Yes'
    mri_hemorrhage = str(mri.get('MRI_Other_Abnormality_Type', '')).strip() == 'Hemorrhage'
    if mri_acute or mri_hemorrhage:
        # v13.4.4: CTH_Acute_Type schema is Hemorrhage/Ischemic Infarct/Mass/Edema/Other (compartment-
        # agnostic, and SDH is excluded entirely since it's incidental, not stroke). MRI's
        # MRI_Other_Abnormality_Type=='Hemorrhage' bucket already excludes SDH (which has its own
        # separate bucket), so resolving to 'Hemorrhage' here is safe — it cannot be an SDH-driven
        # false resolution.
        resolved_type = 'Hemorrhage' if mri_hemorrhage else 'Ischemic Infarct'
        flags.append(f"CTH_Acute_Finding resolved No Acute->Acute (Indeterminate stays Yes, "
                      f"documenting the original CTH hedge language): follow-up MRI confirmed "
                      f"{'hemorrhage' if mri_hemorrhage else 'acute infarct'}")
        cth['CTH_Acute_Finding'] = 'Acute'
        cth['CTH_Acute_Type'] = resolved_type
    return cth


def _to_grade(v) -> int:
    """Best-effort int cast for a CTA vessel grade; unparseable/missing -> 9 (not assessed)."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 9


def compute_confidence(cth: dict, cta: dict, ctp: dict, mri: dict, qc_flags: list,
                        cth_text: str, ctah_text: str, ctan_text: str, mri_text: str,
                        mri_performed: bool, cta_performed: bool = None):
    """
    Deterministic confidence score, zero added LLM calls (no separate
    synthesis agent in v12 — see header). Same rationale as v11: this
    is a rules-based formula, and formulas belong in Python, not in an
    LLM's single-pass mental arithmetic.

    Returns (score: int 0-100, reason: str listing every rule that fired).
    """
    reasons = []
    post_keys = ('CTA_R_Vert', 'CTA_L_Vert', 'CTA_Basilar')
    ant_keys  = ('CTA_R_ICA', 'CTA_L_ICA', 'CTA_R_MCA', 'CTA_L_MCA')
    post_grades = [_to_grade(cta.get(k, 9)) for k in post_keys]
    ant_grades  = [_to_grade(cta.get(k, 9)) for k in ant_keys]
    has_stenosis = lambda grades: any(2 <= g <= 4 for g in grades)

    cth_performed = str(cth.get('CTH_Source', '')) in ('CTH Report', 'Embedded in CTA')
    # cta_performed is passed explicitly by the caller now that grade 9 no longer distinguishes
    # "not performed" from "vessel not mentioned" (unmentioned vessels are 0, not 9) — fall back
    # to the old any(!=9) inference only if an older caller doesn't pass it.
    if cta_performed is None:
        cta_performed = any(g != 9 for g in post_grades + ant_grades)

    if cth_performed and cta_performed and mri_performed:
        score = 80
    elif cth_performed and cta_performed and not mri_performed:
        score = 60
    elif cta_performed and not cth_performed:
        score = 50
    elif cth_performed and not cta_performed:
        score = 45
    elif mri_performed and not cth_performed and not cta_performed:
        score = 55
        reasons.append("note: MRI-only availability pattern, base=55 (extrapolated)")
    else:
        score = 20
    reasons.append(f"base={score} (CTH={'Y' if cth_performed else 'N'}, "
                    f"CTA={'Y' if cta_performed else 'N'}, MRI={'Y' if mri_performed else 'N'})")

    mri_acute = str(mri.get('MRI_Acute_Infarct', '')).strip() == 'Yes'
    territory = str(mri.get('MRI_Acute_Territory', '')).strip()
    cta_explains_territory = mri_acute and (
        (territory == 'Posterior' and has_stenosis(post_grades)) or
        (territory == 'Anterior' and has_stenosis(ant_grades)) or
        (territory == 'Both' and (has_stenosis(post_grades) or has_stenosis(ant_grades)))
    )
    if cta_explains_territory:
        score += 15
        reasons.append("+15 MRI acute infarct territory explained by a concordant CTA stenosis/occlusion")

    ctp_concordant = (str(ctp.get('CTP_Deficit', '')) == 'Yes' and
                      (has_stenosis(post_grades) or has_stenosis(ant_grades)))
    if ctp_concordant:
        score += 10
        reasons.append("+10 CTP deficit concordant with a CTA vessel finding")

    hemorrhage_confirmed = (str(cth.get('CTH_Acute_Finding', '')) == 'Acute' and
                            str(cth.get('CTH_Acute_Type', '')) == 'Hemorrhage')
    if hemorrhage_confirmed:
        score += 10
        reasons.append("+10 acute hemorrhage confirmed on CTH")

    mri_unexplained = (mri_acute and cta_performed and
                       not has_stenosis(post_grades) and not has_stenosis(ant_grades) and
                       not str(cta.get('CTA_Notable_Finding', '')).strip())
    if mri_unexplained:
        score -= 15
        reasons.append("-15 MRI acute infarct positive but CTA fully normal (unexplained mechanism)")

    combined_text = ' '.join([cth_text or '', ctah_text or '', ctan_text or '', mri_text or ''])
    technical_limitation = bool(_TECH_LIMITATION_WORDS.search(combined_text))
    if technical_limitation:
        score -= 10
        reasons.append("-10 technical limitation explicitly documented in a report")

    ctp_no_mri = str(ctp.get('CTP_Deficit', '')) == 'Yes' and not mri_performed
    if ctp_no_mri:
        score -= 5
        reasons.append("-5 CTP deficit present but no MRI to confirm")

    cth_indeterminate = str(cth.get('CTH_Acute_Indeterminate', '')).strip() == 'Yes'
    if cth_indeterminate:
        score -= 8
        reasons.append("-8 CTH has an equivocal/possible acute finding pending MRI resolution")

    qc_penalty = min(len(qc_flags) * 5, 15)
    if qc_penalty:
        score -= qc_penalty
        reasons.append(f"-{qc_penalty} heuristic QC layer overrode {len(qc_flags)} field(s) on this case")

    if (cth_performed or cta_performed or mri_performed) and \
       not qc_flags and not mri_unexplained and not technical_limitation and \
       not cth_indeterminate:
        score += 10
        reasons.append("+10 all modalities fully concordant, no QC overrides or uncertainty flags")

    if not mri_performed:
        score = min(score, 72)
        reasons.append("cap: no MRI performed -> max 72")
    if not mri_performed and not cth_performed:
        score = min(score, 58)
        reasons.append("cap: no MRI and no CTH -> max 58")
    if not cth_performed and not cta_performed and not mri_performed:
        score = min(score, 25)
        reasons.append("cap: no imaging performed at all -> max 25")

    score = max(0, min(100, round(score)))
    return score, '; '.join(reasons)


# ── CELL 7: V13.4.1 concise prompts + deterministic derivations ─────────────
#
# Design:
#   - Ask the LLM only questions that require semantic interpretation.
#   - Use short schemas and one source snippet per positive branch.
#   - Detect explicit MRA language in Python.
#   - Use one localization call per positive acute/chronic branch.
#   - Do not use an LLM critic for contradictions that Python can resolve.

_JSON_ONLY = ("Return ONLY one valid raw JSON object. "
              "No markdown, no prose, and no reasoning field.")

CTH_GATE_PROMPT = """Review the CT head report. If no dedicated CT head report is present, check the
CTA head report for embedded noncontrast CT findings. Answer the questions directly from the report.
""" + _JSON_ONLY + """

Questions:
1. Was CT head information available?
2. Is there a definite acute intracranial finding?
3. Is there an age-indeterminate, possible, or cannot-exclude acute finding?
4. If definite acute, what is the main acute type?
5. Is chronic microvascular/white-matter disease present?

Rules:
- CTH_Acute_Finding=Acute ONLY for a definite, confirmed acute finding (a diagnosis the radiologist
  actually commits to — not a possibility they merely raise).
- CTH_Acute_Finding=No Acute (with CTH_Acute_Indeterminate=Yes) when the report describes a possible,
  equivocal, age-indeterminate, or cannot-exclude finding without committing to it — e.g. "nonspecific,
  may represent ischemic change, gliosis, demyelination, or edema," "cannot exclude," a hyperdense
  vessel sign alone with a recommendation for follow-up CTA/MRI to characterize it, or any language
  where the radiologist proposes a differential rather than a diagnosis. Do NOT answer Acute for these —
  this dataset always has a follow-up MRI brain, so an equivocal CTH finding will be resolved there;
  CTH's job is only to flag it as Indeterminate=Yes for the reviewer, not to call it Acute.
- CTH_Acute_Indeterminate=Yes marks that an equivocal/possible finding was raised in the report, even
  though CTH_Acute_Finding itself is coded No Acute for that same finding.
- IMPORTANT — a generic technical-limitation statement is NOT, by itself, equivocal acute-finding
  language. Do NOT set Indeterminate=Yes just because the report mentions the study (or one region of
  it) was "limited," "degraded," or "suboptimal" due to motion/artifact/beam-hardening, UNLESS the
  radiologist also hedges specifically on whether an acute finding is present in that region (e.g.
  "cannot exclude a small infarct given motion artifact," "acute findings cannot be reliably assessed
  in this region"). A report that plainly states "no definite acute infarct" or "no acute hemorrhage"
  and separately notes a technical caveat about image quality (without tying that caveat to doubt about
  the acute-finding conclusion itself) is a committed negative call: CTH_Acute_Finding=No Acute,
  CTH_Acute_Indeterminate=No. The distinguishing question is always "does the radiologist's own stated
  conclusion leave the presence/absence of an acute finding genuinely open," not "does the report
  mention any technical limitation anywhere."
- Use CTH_Acute_Indeterminate=No when there is no equivocal/possible acute language at all.
- Use No Acute + Indeterminate=No only when the report contains no definite, suspected, or possible
  acute intracranial finding whatsoever.
- If Acute_Finding=Acute (a genuinely definite, committed-to finding), assign the best-supported type.
- Hemorrhage is documented as a single "Hemorrhage" type — do NOT specify the compartment (no ICH vs
  SAH vs IVH distinction) here. Any definite, acute intraparenchymal, subarachnoid, or intraventricular
  hemorrhage is simply "Hemorrhage."
- SUBDURAL HEMORRHAGE (SDH) IS NOT A STROKE FINDING AND IS NEVER CTH_Acute_Type=Hemorrhage. A subdural
  hemorrhage/hematoma is an incidental extra-axial finding, not an acute stroke-workup diagnosis, even
  when it is acute/new on the CT head. If SDH is the ONLY acute abnormality described in the report,
  CTH_Acute_Finding=No Acute and CTH_Acute_Indeterminate=No — SDH does not get coded here at all; it
  will be captured separately as an MRI other-abnormality finding once the MRI is read. If a genuine
  stroke-type finding (parenchymal/subarachnoid/intraventricular hemorrhage, or acute ischemic infarct)
  is ALSO present alongside the SDH, code Acute_Finding=Acute for that other finding as usual and ignore
  the SDH entirely at the CTH stage.
- "No acute hemorrhage" does not cancel a separately reported, definite acute infarct.
- Microvascular disease requires diffuse white-matter/small-vessel language, not one old infarct.
- A hyperdensity or high-attenuation focus that is a known imaging artifact or mimic (e.g. calcification,
  a normal choroid plexus/pineal calcification, streak artifact, or beam-hardening) is not a hemorrhage —
  only code Hemorrhage for blood the radiologist actually diagnoses as such.
- Evidence must be one short source phrase; use an empty string when absent.

{{
  "CTH_Source": "CTH Report" | "Embedded in CTA" | "Not Performed",
  "CTH_Acute_Finding": "Acute" | "No Acute" | "N/A",
  "CTH_Acute_Indeterminate": "Yes" | "No" | "N/A",
  "CTH_Acute_Type": "Hemorrhage" | "Ischemic Infarct" | "Mass/Edema" | "Other" | "N/A",
  "CTH_Acute_Evidence": "",
  "CTH_Microvascular": "Present" | "Not Present" | "N/A",
  "CTH_Microvascular_Evidence": ""
}}

CT HEAD REPORT:
{cth_text}

CTA HEAD REPORT:
{ctah_text}"""

CTA_GRADING_PROMPT = """Grade the seven named arteries from the CTA head and neck reports. Answer only
from explicit vessel assessment in the report. """ + _JSON_ONLY + """

Grade scale:
0 = normal/patent/no stenosis, OR the vessel is not individually addressed by any statement in the
    report at all (silence about a named vessel is not evidence of disease — default to 0)
1 = mild or <50% stenosis
2 = moderate or 50-69% stenosis
3 = severe/critical/near-occlusion or 70-99% stenosis
4 = occluded/100% — no flow, absent flow-void/visualization, "occlusion"/"occluded", or distal
    reconstitution (distal segment refills via collaterals past a point of no antegrade flow) all
    mean grade 4; occlusion language is often understated, so read for these signs even when the
    word "occlusion" itself is not used

There is no "not assessed" grade. Every vessel gets 0-4. A vessel that is never individually named in
the report defaults to grade 0, and a vessel affected by motion/artifact language without an explicit
stenosis/occlusion call also defaults to grade 0 — do not withhold a grade or use a placeholder.
This applies even when the CTA/CTP section as a whole contains real report text (i.e. the study WAS
performed) but that text is generic, non-specific, or does not individually address a given vessel by
name — a performed-but-non-specific report is graded 0 for every vessel it doesn't name, exactly like
an explicitly normal report. (Grade 9 is reserved solely for the separate, pipeline-level case of the
CTA/CTP study never having been performed at all — see normalize_cta_grades() — and is never something
this prompt should ever be asked to produce; verified correct on a dedicated test case where the CTA
Head report was blank but the CTA Neck report had real, specific text — vessels named in the Neck
report were graded normally and the CTA was correctly treated as performed, not defaulted to 9.)

Rules:
- Grade ONLY these seven named vessels: right vertebral, left vertebral, basilar, right ICA, left ICA,
  right MCA, left MCA. Do NOT grade, and do NOT fold findings from, any other vessel — ACA, PCA, PICA,
  AICA, and any other named artery are out of scope for this task even if the report discusses them at
  length. Only attribute a finding to one of the seven named vessels when the report explicitly names
  that vessel or an unambiguous segment of it (e.g. "V4 segment" = vertebral).
- When the report gives a two-tier descriptor spanning a range (e.g. "mild to moderate", "moderate/
  severe", "moderate-severe stenosis"), always code the HIGHER of the two grades — never split the
  difference or default to the lower one.
- Absent proximal visualization, absent flow-void, "no flow", or distal reconstitution of a vessel is
  grade 4 (occlusion) even if the word "occlusion" is never used — do not downgrade this to grade 3.
- Plaque, calcification, atherosclerosis, tortuosity, hypoplasia, dominance, or fetal PCA without
  explicit stenosis/narrowing is grade 0.
- A patent proximal segment does not prove a technically limited distal segment is normal — but absent
  an explicit stenosis/occlusion statement for that segment, still grade 0 rather than leaving it blank.
- A statement covering the posterior circulation as a whole (e.g. "the vertebrobasilar system is patent
  without stenosis," "major intracranial flow-voids are preserved," "posterior circulation unremarkable")
  is a valid, explicit assessment of the basilar artery and should be graded 0.
- Evidence is required only for grades 1-4. Use an empty string for routine grade 0.
- Notable finding: one concise aneurysm, dissection, FMD, vasculopathy, or vascular-malformation phrase;
  otherwise empty.

{{
  "CTA_R_Vert": 0, "CTA_R_Vert_Evidence": "",
  "CTA_L_Vert": 0, "CTA_L_Vert_Evidence": "",
  "CTA_Basilar": 0, "CTA_Basilar_Evidence": "",
  "CTA_R_ICA": 0, "CTA_R_ICA_Evidence": "",
  "CTA_L_ICA": 0, "CTA_L_ICA_Evidence": "",
  "CTA_R_MCA": 0, "CTA_R_MCA_Evidence": "",
  "CTA_L_MCA": 0, "CTA_L_MCA_Evidence": "",
  "CTA_Notable_Finding": ""
}}

CTA HEAD REPORT:
{ctah_text}

CTA NECK REPORT:
{ctan_text}"""

CTP_GATE_PROMPT = """Review the CT-perfusion portion of the report and answer four direct questions.
Use the radiologist's final interpretation, not an isolated automated number that the radiologist calls
artifact. """ + _JSON_ONLY + """

Rules:
- Performed=Yes when perfusion imaging or maps were actually obtained.
- Quality=Limited when interpretation is possible but affected by artifact; Nondiagnostic when no
  reliable interpretation can be made.
- Deficit=Yes only for a diagnostic perfusion abnormality accepted in the final report.
- Artifact-only Tmax/CBF/CBV findings with a final impression of no diagnostic deficit = No.

{{
  "CTP_Performed": "Yes" | "No",
  "CTP_Technical_Quality": "Diagnostic" | "Limited" | "Nondiagnostic" | "N/A",
  "CTP_Deficit": "Yes" | "No" | "N/A",
  "CTP_Evidence": ""
}}

CTA HEAD REPORT:
{ctah_text}

CTA NECK REPORT:
{ctan_text}"""

MRI_CORE_PROMPT = """Review the MRI brain report and answer six direct questions. Acute infarct
means acute or subacute ISCHEMIC infarction only. Acute and chronic infarcts are independent and may
both be present. Do not classify territory or bilateral status in this call. """ + _JSON_ONLY + """

Questions:
1. What is the technical quality: Diagnostic, Limited, Nondiagnostic, or N/A?
2. Is an acute or subacute ischemic infarct present?
3. Is a localized chronic/old infarct present?
4. Is another intracranial abnormality present besides acute or chronic ischemic infarct?
5. If another abnormality is present, what is the best controlled abnormality type?
6. Provide one short source phrase for each positive finding.

Rules:
- MRI_Acute_Infarct refers only to acute/subacute ischemic infarction or explicit restricted diffusion.
- Do NOT classify MRI_Acute_Infarct=Yes when the report expresses genuine diagnostic uncertainty about
  whether the finding IS an infarct: an equivocal ADC/DWI correlation ("equivocal on the ADC map"),
  a differential diagnosis offered instead of a single diagnosis (e.g. "diagnostic considerations
  include demyelination and subacute infarct"), or the radiologist recommending further imaging
  (e.g. contrast-enhanced MRI) specifically to clarify what the finding represents. Language like
  "considerations include X or Y", "cannot exclude", "may represent", or "recommend further evaluation
  to characterize" attached to the infarct question means the answer is No, not Yes — do not resolve
  the radiologist's own stated uncertainty into a confident positive.
- This equivocal-language rule does not apply to unambiguous restricted diffusion clearly described as
  consistent with acute infarct (e.g. "restricted diffusion consistent with acute infarction") — only
  to findings the report itself frames as uncertain or differential.
- DWI hyperintensity alone is not restricted diffusion: true acute ischemia requires hyperintense DWI
  WITH a corresponding low/dark ADC signal (true restricted diffusion). DWI hyperintensity with a
  normal, unremarkable, or elevated/bright ADC ("T2 shine-through") reflects an old/chronic lesion, not
  an acute one — do not classify MRI_Acute_Infarct=Yes from DWI brightness alone if the report notes the
  ADC does not correlate (or is silent on ADC while explicitly calling the finding chronic/old elsewhere).
- A new acute infarct can coexist with an old chronic infarct in the same region ("acute-on-chronic");
  when the report distinguishes a new focus of true restricted diffusion from a background of chronic
  encephalomalacia/gliosis, code both MRI_Acute_Infarct=Yes and MRI_Chronic_Infarct=Yes rather than
  collapsing them into one.
- Do not classify primary hemorrhage as an acute infarct.
- Hemorrhagic transformation of an explicitly acute ischemic infarct may have
  MRI_Acute_Infarct=Yes and MRI_Other_Abnormality=Yes.
- Chronic infarct requires a localized old infarct, encephalomalacia, gliosis, or chronic lacune.
- Chronic microvascular disease alone is not a chronic infarct; classify it as Other_Abnormality=Yes.
- Other abnormality includes white-matter/microvascular disease, atrophy, hemorrhage/blood products,
  a vascular malformation, edema, mass/tumor, hydrocephalus, extra-axial collection, demyelinating/
  inflammatory disease, or another intracranial abnormality.
- Ignore minor extracranial findings such as a small sinus retention cyst.
- MRA/vascular flow descriptions are NOT a brain parenchymal "other abnormality": findings that
  describe blood flow or vessel status only — e.g. "reconstitution via collateral pathways,"
  "collateral flow," "slow flow," "patent/occluded vessel," or language explaining an MRA finding
  in the context of a KNOWN, previously established vessel occlusion/stenosis — belong to vessel
  status (captured separately, e.g. via CTA/MRA fields), not MRI_Other_Abnormality. Do not set
  MRI_Other_Abnormality=Yes based solely on collateral-flow or reconstitution language tied to an
  already-known chronic vascular occlusion; that is expected downstream physiology of the known
  occlusion, not a new brain parenchymal finding. Only set MRI_Other_Abnormality=Yes if the MRI text
  separately describes an actual parenchymal/structural abnormality (e.g. infarct, hemorrhage, mass,
  atrophy, white matter disease, edema, hydrocephalus).
- SUBDURAL HEMORRHAGE (SDH) IS A SEPARATE CATEGORY FROM "HEMORRHAGE": subdural blood/hematoma —
  acute or chronic — is an incidental extra-axial finding, not a stroke-type hemorrhage, and is
  clinically distinct from parenchymal/subarachnoid/intraventricular bleeding. Code any subdural
  hemorrhage or extra-axial collection as "SDH/Extra-axial Hemorrhage", never as "Hemorrhage".
- CHRONIC/OLD MICROHEMORRHAGE IS NOT "HEMORRHAGE": chronic hemosiderin deposition, susceptibility
  artifact/blooming "consistent with previous microhemorrhages," or any other clearly OLD, non-acute
  microbleed finding does NOT qualify for the Hemorrhage category. These are low-priority incidental
  findings — rank them below Atrophy/Volume Loss (see priority order below). The Hemorrhage category
  is reserved for an acute/current, clinically active, non-subdural hemorrhage only (e.g. acute
  intraparenchymal, subarachnoid, or intraventricular blood, or hemorrhagic transformation) —
  subdural blood is always "SDH/Extra-axial Hemorrhage" instead, regardless of acuity.
- A vascular malformation (AVM, cavernoma/cavernous malformation, developmental venous anomaly with
  a notable abnormality, dural AV fistula, etc.) that is NOT actively/acutely hemorrhaging is coded
  "Vascular Malformation". If it HAS bled, code the hemorrhage category instead (Hemorrhage, or
  SDH/Extra-axial Hemorrhage if the bleed is subdural) — an actively bleeding vascular malformation is
  documented as its hemorrhage, not as "Vascular Malformation".
- When more than one finding is described, do NOT default to Multiple. Choose the single most
  clinically significant category using this FIXED priority order, applied rigidly regardless of
  which finding is emphasized in the IMPRESSION versus the FINDINGS section, and regardless of which
  finding is mentioned first, last, or most prominently in the report text. This order reflects both
  clinical urgency and this cohort's actual empirical prevalence (chronic microvascular disease is the
  vast majority of cases; the remainder are edge cases ordered most-to-least common):
  Hemorrhage (acute/active only) > SDH/Extra-axial Hemorrhage > Vascular Malformation >
  Chronic Microvascular/White Matter Disease > Other > Mass/Tumor > Demyelinating/Inflammatory >
  Atrophy/Volume Loss > Edema > Hydrocephalus.
  This ranking always wins the tie-break. Do not let IMPRESSION-section wording, radiologist
  emphasis, or clinical-correlation language (e.g. "correlate clinically for possible dementia")
  override the fixed order — apply the same rank order every time these categories co-occur.
- Chronic/old microhemorrhage or hemosiderin (non-acute) ranks lowest of all — below Edema and
  Hydrocephalus. If it is the ONLY other-abnormality finding present (no microvascular disease, mass,
  etc.), classify MRI_Other_Abnormality_Type as "Other", never "Hemorrhage".
- Mild or incidental atrophy, edema, or old microhemorrhage/hemosiderin accompanying a higher-priority
  finding does not elevate the case to Multiple (e.g. chronic microvascular disease with incidental old
  microhemorrhage, or with mild associated atrophy, is "Chronic Microvascular/White Matter Disease",
  not Multiple).
- A hemorrhage that extends into, or is bounded by, an adjacent compartment (parenchyma, ventricle,
  or subarachnoid space) is still ONE Hemorrhage finding, not Multiple — do not subdivide by compartment.
  A hemorrhage that spans both a non-subdural compartment AND the subdural space (e.g. parenchymal
  hemorrhage with an adjacent subdural component) is coded as "Hemorrhage" (the higher-priority,
  non-subdural component), not Multiple and not SDH/Extra-axial Hemorrhage.
- Reserve Multiple only for two or more clearly independent, comparably significant, unrelated
  pathologies (e.g. a separate mass AND an unrelated separate ACUTE hemorrhage in a different location).
- Evidence is retained for LLM audit only; use one short source phrase and an empty string when negative.

Allowed MRI_Other_Abnormality_Type values:
- Chronic Microvascular/White Matter Disease
- Atrophy/Volume Loss
- Hemorrhage
- SDH/Extra-axial Hemorrhage
- Vascular Malformation
- Edema
- Mass/Tumor
- Hydrocephalus
- Demyelinating/Inflammatory
- Other
- Multiple
- N/A

{{
  "MRI_Technical_Quality": "Diagnostic" | "Limited" | "Nondiagnostic" | "N/A",
  "MRI_Acute_Infarct": "Yes" | "No" | "N/A",
  "MRI_Acute_Evidence": "",
  "MRI_Chronic_Infarct": "Yes" | "No" | "N/A",
  "MRI_Chronic_Location": "",
  "MRI_Chronic_Evidence": "",
  "MRI_Other_Abnormality": "Yes" | "No" | "N/A",
  "MRI_Other_Abnormality_Type": "Chronic Microvascular/White Matter Disease" |
    "Atrophy/Volume Loss" | "Hemorrhage" | "SDH/Extra-axial Hemorrhage" | "Vascular Malformation" |
    "Edema" | "Mass/Tumor" | "Hydrocephalus" | "Demyelinating/Inflammatory" | "Other" | "Multiple" | "N/A",
  "MRI_Other_Abnormality_Evidence": ""
}}

MRI BRAIN REPORT:
{mri_text}"""

MRI_ACUTE_LOCALIZATION_PROMPT = """An acute/subacute infarct is already confirmed. Use the short
location snippet as the primary lesion list and verify it against the full report. Return only broad
territory and bilateral status. """ + _JSON_ONLY + """

Acute location snippet: {acute_snippet}

Territory:
- Posterior: cerebellum, brainstem, thalamus, occipital, posterior temporal, cerebral peduncle,
  PCA/PICA/SCA/basilar territory.
- Anterior: frontal, parietal, non-posterior temporal, MCA/ACA, caudate, putamen, basal ganglia,
  anterior internal capsule.
- Both: at least one explicit anterior and one explicit posterior location.
Bilateral=Yes only when both left and right sides are explicit or the report says bilateral.
Multifocal on one side is not bilateral. A midline lesion alone is not bilateral.

{{
  "MRI_Acute_Territory": "Anterior" | "Posterior" | "Both",
  "MRI_Acute_Bilateral": "Yes" | "No"
}}

MRI BRAIN REPORT:
{mri_text}"""

MRI_CHRONIC_LOCALIZATION_PROMPT = """A localized chronic infarct is already confirmed. Use the short
location snippet as the primary lesion list and verify it against the full report. Return only broad
territory and bilateral status. """ + _JSON_ONLY + """

Chronic location snippet: {chronic_snippet}

Use the same territory and bilateral rules as the acute localization task.

{{
  "MRI_Chronic_Territory": "Anterior" | "Posterior" | "Both",
  "MRI_Chronic_Bilateral": "Yes" | "No"
}}

MRI BRAIN REPORT:
{mri_text}"""

_MRA_PATTERN = re.compile(
    r'\b(MRA|MR angiograph\w*|magnetic resonance angiograph\w*|time[- ]of[- ]flight|\bTOF\b)\b',
    re.IGNORECASE,
)

# v14.0.0 FIX (bug found via 15-case synthetic test set, 8/8 reproduction rate):
# detect_mra() previously matched ANY sentence containing the word "MRA" and treated a
# non-empty match as proof MRA was performed -- including sentences that explicitly NEGATE
# it, e.g. "MRA not performed with this study." The old code returned that exact negating
# sentence back as its own "evidence" for MRI_MRA_Included=Yes, which is backwards. This
# pattern catches a negation word/phrase occurring within ~40 chars before the MRA mention
# (covers "MRA not performed", "no MRA", "without MRA", "MRA was not obtained/included",
# "MRA deferred", "MRA not included") so a negated mention is correctly scored No.

# v14.0.2 FIX: the window between a negation word and the MRA mention now stops at a comma.
# Real radiology headers commonly read "STUDY WITHOUT CONTRAST, WITH MRA" -- "WITHOUT" there
# negates CONTRAST, an unrelated clause, not MRA (which is separately, positively affirmed by
# "WITH" right before it). The old unbounded 40-char window let "WITHOUT" reach across the
# comma to "MRA" and falsely flag a real positive MRA mention as negated. Found via 15-case
# synthetic re-test after v14.0.2: SAMPLE005's real "...WITH MRA" header was misread as No.
_MRA_NEGATION_PATTERN = re.compile(
    r'\b(not|no|without|deferred|declined|excluded|omitted)\b(?:(?!,)[^.!?]){0,40}\b'
    r'(MRA|MR angiograph\w*|magnetic resonance angiograph\w*|time[- ]of[- ]flight|\bTOF\b)\b'
    r'|\b(MRA|MR angiograph\w*|magnetic resonance angiograph\w*|time[- ]of[- ]flight|\bTOF\b)\b'
    r'(?:(?!,)[^.!?]){0,40}\b(not (?:performed|obtained|included|done|acquired)|was not|were not|'
    r'not included|not performed|deferred|declined)\b',
    re.IGNORECASE,
)


def _short_matching_sentence(text: str, pattern: re.Pattern, max_chars: int = 240) -> str:
    """Return a concise sentence containing the first explicit pattern match."""
    if not text or text == 'N/A':
        return ''
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', str(text)):
        if pattern.search(sentence):
            return ' '.join(sentence.split())[:max_chars]
    match = pattern.search(str(text))
    if not match:
        return ''
    start = max(0, match.start() - 80)
    end = min(len(str(text)), match.end() + 120)
    return ' '.join(str(text)[start:end].split())[:max_chars]


def detect_mra(text: str) -> tuple[str, str]:
    """MRA presence is a deterministic explicit-term extraction, not an LLM judgment.

    v14.0.0: now negation-aware. A sentence containing "MRA" is only treated as evidence
    of Yes if that same sentence does NOT also match the negation pattern (e.g. "MRA not
    performed with this study" no longer scores Yes)."""
    if not text or text == 'N/A':
        return 'No', ''
    sentence = _short_matching_sentence(text, _MRA_PATTERN)
    if not sentence:
        return 'No', ''
    if _MRA_NEGATION_PATTERN.search(sentence):
        return 'No', ''
    return 'Yes', sentence


def normalize_yes_no_na(value, default='N/A') -> str:
    value = str(value).strip()
    return value if value in {'Yes', 'No', 'N/A'} else default


def normalize_quality(value, performed: bool) -> str:
    value = str(value).strip()
    if not performed:
        return 'N/A'
    return value if value in {'Diagnostic', 'Limited', 'Nondiagnostic'} else 'Limited'


def normalize_territory(value) -> str:
    value = str(value).strip()
    return value if value in {'Anterior', 'Posterior', 'Both', 'N/A'} else 'N/A'


def apply_cth_rules(cth: dict, flags: list) -> dict:
    """Normalize CTH outputs and enforce simple field dependencies."""
    source = str(cth.get('CTH_Source', '')).strip()
    if source not in {'CTH Report', 'Embedded in CTA', 'Not Performed'}:
        source = 'Not Performed' if not source else 'CTH Report'
        flags.append('CTH source normalized to allowed schema')
    cth['CTH_Source'] = source

    if source == 'Not Performed':
        cth.update({
            'CTH_Acute_Finding':'N/A','CTH_Acute_Indeterminate':'N/A',
            'CTH_Acute_Type':'N/A','CTH_Acute_Evidence':'',
            'CTH_Microvascular':'N/A','CTH_Microvascular_Evidence':''
        })
        return cth

    acute = str(cth.get('CTH_Acute_Finding', '')).strip()
    cth['CTH_Acute_Finding'] = acute if acute in {'Acute','No Acute'} else 'No Acute'
    cth['CTH_Acute_Indeterminate'] = normalize_yes_no_na(
        cth.get('CTH_Acute_Indeterminate'), 'No')
    micro = str(cth.get('CTH_Microvascular', '')).strip()
    cth['CTH_Microvascular'] = micro if micro in {'Present','Not Present'} else 'Not Present'

    if cth['CTH_Acute_Finding'] != 'Acute':
        cth['CTH_Acute_Type'] = 'N/A'
        if cth['CTH_Acute_Indeterminate'] != 'Yes':
            cth['CTH_Acute_Evidence'] = ''
    else:
        acute_type = str(cth.get('CTH_Acute_Type', '')).strip()
        if acute_type in {'ICH','SAH','IVH'}:
            # v13.4.4: hemorrhage compartment is no longer distinguished on CTH — ICH/SAH/IVH
            # all collapse to a single "Hemorrhage" value (keeps stroke-workup documentation simple).
            cth['CTH_Acute_Type'] = 'Hemorrhage'
            flags.append(f'CTH acute type: compartment-specific {acute_type} collapsed to Hemorrhage')
        elif acute_type == 'SDH':
            # SDH is never a qualifying stroke-type acute finding — treat as if CTH found nothing
            # acute at all. If a real coexisting acute finding exists it will already have set a
            # different CTH_Acute_Type on this same call; if the LLM returned SDH as THE finding,
            # that means SDH was the only acute abnormality, so this case reverts to No Acute.
            cth['CTH_Acute_Finding'] = 'No Acute'
            cth['CTH_Acute_Indeterminate'] = 'No'
            cth['CTH_Acute_Type'] = 'N/A'
            cth['CTH_Acute_Evidence'] = ''
            flags.append('CTH acute type SDH treated as incidental (not a stroke finding); reverted to No Acute')
        elif acute_type not in {'Hemorrhage','Ischemic Infarct','Mass/Edema','Other'}:
            cth['CTH_Acute_Type'] = 'Other'
            flags.append('CTH acute type normalized to Other')
        if cth['CTH_Acute_Finding'] == 'Acute' and not str(cth.get('CTH_Acute_Evidence','')).strip():
            flags.append('CTH definite acute finding missing evidence')

    if cth['CTH_Microvascular'] == 'Not Present':
        cth['CTH_Microvascular_Evidence'] = ''
    return cth


def normalize_cta_grades(cta: dict, cta_performed: bool, flags: list) -> dict:
    """Grade 9 is reserved exclusively for a CTA that was never performed at all (no CTA
    text available for this case). Within a CTA that WAS performed, every vessel gets a
    0-4 grade — an un-named vessel or a stray/invalid 9 the LLM still returns is forced to
    0 (unmentioned = normal), per the v13.4.4 policy that silence is not evidence of disease."""
    keys = ['CTA_R_Vert','CTA_L_Vert','CTA_Basilar','CTA_R_ICA','CTA_L_ICA','CTA_R_MCA','CTA_L_MCA']
    for key in keys:
        if not cta_performed:
            cta[key] = 9
            cta[f'{key}_Evidence'] = 'CTA not performed'
            continue
        try:
            grade = int(float(cta.get(key, 0)))
        except (TypeError, ValueError):
            grade = 0
            flags.append(f'{key} invalid grade normalized to 0 (unmentioned=normal policy)')
        if grade == 9:
            flags.append(f'{key} model returned grade 9 on a performed CTA; forced to 0 (unmentioned=normal policy)')
            grade = 0
        if grade not in {0,1,2,3,4}:
            flags.append(f'{key} out-of-range grade {grade} normalized to 0')
            grade = 0
        cta[key] = grade
        ev_key = f'{key}_Evidence'
        evidence = str(cta.get(ev_key, '') or '').strip()
        if grade == 0:
            cta[ev_key] = ''
        elif not evidence:
            flags.append(f'{key} grade {grade} missing evidence')
    return cta


MRI_OTHER_TYPES = {
    'Chronic Microvascular/White Matter Disease',
    'Atrophy/Volume Loss',
    'Hemorrhage',
    'SDH/Extra-axial Hemorrhage',
    'Vascular Malformation',
    'Edema',
    'Mass/Tumor',
    'Hydrocephalus',
    'Demyelinating/Inflammatory',
    'Other',
    'Multiple',
    'N/A',
}

# v13.4.1 briefly used compartment-specific hemorrhage subtypes (ICH/IVH/SAH/SDH/
# Hemorrhagic Transformation), which caused over-triggering of "Multiple" whenever a
# single bleed extended into an adjacent compartment. Collapsed back to one broad
# "Hemorrhage" category (v13.4.2). v13.4.4 splits SDH back out into its own bucket
# ("SDH/Extra-axial Hemorrhage") since subdural hemorrhage is clinically an incidental/
# traumatic finding, not a stroke-type hemorrhage — it should never share a bucket with
# true parenchymal/subarachnoid/intraventricular (stroke-type) hemorrhage. This map
# keeps any stray old-style output normalized instead of falling through to "Other".
_LEGACY_HEMORRHAGE_SUBTYPES = {
    'ICH', 'IVH', 'SAH', 'Hemorrhagic Transformation',
}
_LEGACY_SDH_SUBTYPES = {
    'SDH', 'SDH/Extra-axial Collection',
}


def normalize_mri_other_type(value, other_status: str, flags: list) -> str:
    """Normalize the controlled non-infarct MRI abnormality category."""
    if other_status != 'Yes':
        return 'N/A'
    value = str(value or '').strip()
    if value in _LEGACY_HEMORRHAGE_SUBTYPES:
        return 'Hemorrhage'
    if value in _LEGACY_SDH_SUBTYPES:
        return 'SDH/Extra-axial Hemorrhage'
    if value in MRI_OTHER_TYPES and value != 'N/A':
        return value
    flags.append('MRI other abnormality Yes but type missing/invalid; normalized to Other')
    return 'Other'


def apply_mri_rules(mri: dict, mri_text: str, performed: bool, flags: list) -> dict:
    """Normalize MRI outputs and derive fields that do not require another LLM call."""
    if not performed:
        return {
            'MRI_Technical_Quality':'N/A',
            'MRI_Acute_Infarct':'N/A','MRI_Acute_Evidence':'',
            'MRI_Chronic_Infarct':'N/A','MRI_Chronic_Location':'N/A','MRI_Chronic_Evidence':'',
            'MRI_Other_Abnormality':'N/A','MRI_Other_Abnormality_Type':'N/A','MRI_Other_Abnormality_Evidence':'',
            'MRI_MRA_Included':'No','MRI_MRA_Evidence':'',
            'MRI_Acute_Territory':'N/A','MRI_Acute_Bilateral':'N/A',
            'MRI_Chronic_Territory':'N/A','MRI_Chronic_Bilateral':'N/A',
        }

    mri['MRI_Technical_Quality'] = normalize_quality(mri.get('MRI_Technical_Quality'), True)
    for key in ['MRI_Acute_Infarct','MRI_Chronic_Infarct','MRI_Other_Abnormality']:
        mri[key] = normalize_yes_no_na(mri.get(key), 'N/A')

    mra, mra_evidence = detect_mra(mri_text)
    mri['MRI_MRA_Included'] = mra
    mri['MRI_MRA_Evidence'] = mra_evidence

    acute = mri['MRI_Acute_Infarct']
    chronic = mri['MRI_Chronic_Infarct']
    other = mri['MRI_Other_Abnormality']
    mri['MRI_Other_Abnormality_Type'] = normalize_mri_other_type(
        mri.get('MRI_Other_Abnormality_Type'), other, flags)
    quality = mri['MRI_Technical_Quality']

    if acute != 'Yes':
        mri['MRI_Acute_Territory'] = 'N/A'
        mri['MRI_Acute_Bilateral'] = 'N/A'
        if acute == 'No':
            mri['MRI_Acute_Evidence'] = ''
    elif not str(mri.get('MRI_Acute_Evidence','')).strip():
        flags.append('MRI acute infarct Yes but location/evidence snippet is blank')

    if chronic != 'Yes':
        mri['MRI_Chronic_Territory'] = 'N/A'
        mri['MRI_Chronic_Bilateral'] = 'N/A'
        if chronic == 'No':
            mri['MRI_Chronic_Location'] = 'N/A'
            mri['MRI_Chronic_Evidence'] = ''
    else:
        if not str(mri.get('MRI_Chronic_Location','')).strip():
            flags.append('MRI chronic infarct Yes but location snippet is blank')
        if not str(mri.get('MRI_Chronic_Evidence','')).strip():
            flags.append('MRI chronic infarct Yes but chronicity evidence is blank')

    if other != 'Yes':
        mri['MRI_Other_Abnormality_Type'] = 'N/A'
    if other == 'No':
        mri['MRI_Other_Abnormality_Evidence'] = ''
        if acute != 'Yes' and chronic != 'Yes' and _has_unnegated_abnormality(mri_text):
            flags.append(
                'MRI other abnormality=No but report contains unnegated abnormality language; verify'
            )
    elif other == 'Yes' and not str(mri.get('MRI_Other_Abnormality_Evidence','')).strip():
        flags.append('MRI other abnormality Yes but evidence snippet is blank')

    if acute == 'Yes':
        mri['MRI_Acute_Territory'] = normalize_territory(
            mri.get('MRI_Acute_Territory', 'N/A'))
        mri['MRI_Acute_Bilateral'] = normalize_yes_no_na(
            mri.get('MRI_Acute_Bilateral'), 'N/A')
    if chronic == 'Yes':
        mri['MRI_Chronic_Territory'] = normalize_territory(
            mri.get('MRI_Chronic_Territory', 'N/A'))
        mri['MRI_Chronic_Bilateral'] = normalize_yes_no_na(
            mri.get('MRI_Chronic_Bilateral'), 'N/A')

    return mri

# ── CELL 8: Output schema ─────────────────────────────────────
OUTPUT_COLS = [
    'Time_to_CTH_hrs', 'Time_to_CTA_hrs', 'Time_to_MRI_hrs',
    'CTH_Source', 'CTH_Acute_Finding', 'CTH_Acute_Indeterminate', 'CTH_Acute_Evidence',
    'CTH_Acute_Type', 'CTH_Microvascular', 'CTH_Microvascular_Evidence',
    'CTA_R_Vert', 'CTA_R_Vert_Evidence', 'CTA_L_Vert', 'CTA_L_Vert_Evidence',
    'CTA_Basilar', 'CTA_Basilar_Evidence', 'CTA_R_ICA', 'CTA_R_ICA_Evidence',
    'CTA_L_ICA', 'CTA_L_ICA_Evidence', 'CTA_R_MCA', 'CTA_R_MCA_Evidence',
    'CTA_L_MCA', 'CTA_L_MCA_Evidence', 'CTA_Notable_Finding',
    'CTP_Performed', 'CTP_Technical_Quality', 'CTP_Deficit', 'CTP_Evidence',
    'MRI_Technical_Quality', 'MRI_Acute_Infarct', 'MRI_Acute_Evidence',
    'MRI_Acute_Territory', 'MRI_Acute_Bilateral',
    'MRI_Chronic_Infarct', 'MRI_Chronic_Location', 'MRI_Chronic_Evidence',
    'MRI_Chronic_Territory', 'MRI_Chronic_Bilateral',
    'MRI_Other_Abnormality', 'MRI_Other_Abnormality_Type', 'MRI_Other_Abnormality_Evidence',
    'MRI_MRA_Included', 'MRI_MRA_Evidence',
    'MRI_Acute_Chronic_Coexist', 'MRI_Any_Infarct',
    'Confidence_Score', 'Confidence_Reason', 'AI_QC_Flags', 'LLM_Calls_Made',
    'AI_Processed', 'AI_Error_Detail', 'AI_Timestamp'
]


def process_row(row: pd.Series, label: str) -> dict:
    """Run the v13.4.1.1 conditional cascade for one case."""
    cth_text  = safe_get(row, COL_CTH_REPORT)
    ctah_text = safe_get(row, COL_CTAH_REPORT)
    ctan_text = safe_get(row, COL_CTAN_REPORT)
    mri_text  = safe_get(row, COL_MRI_REPORT)
    arrival   = row.get(COL_ARRIVAL, None)

    t_cth = calc_hours(arrival, row.get(COL_CTH_TIME))
    t_cta = calc_hours(arrival, row.get(COL_CTAH_TIME))
    t_mri = calc_hours(arrival, row.get(COL_MRI_TIME))
    calls_made = 0
    qc_flags = []

    # Agent 1: CTH. Skip only when neither dedicated nor embedded source text exists.
    if cth_text == 'N/A' and ctah_text == 'N/A':
        cth = {
            'CTH_Source':'Not Performed','CTH_Acute_Finding':'N/A',
            'CTH_Acute_Indeterminate':'N/A','CTH_Acute_Type':'N/A',
            'CTH_Acute_Evidence':'','CTH_Microvascular':'N/A',
            'CTH_Microvascular_Evidence':''
        }
    else:
        tqdm.write(f"  {label} | Agent 1/6 CTH...")
        cth = call_model(CTH_GATE_PROMPT.format(cth_text=cth_text, ctah_text=ctah_text), 'CTH')
        calls_made += 1; time.sleep(SLEEP_SEC)
        cth = qc_check_cth_microvascular_evidence(cth, qc_flags)
        cth = qc_check_cth_impression_override_conflict(cth, cth_text, qc_flags)
        cth = qc_check_cth_hedge_language(cth, cth_text, qc_flags)
    cth = apply_cth_rules(cth, qc_flags)

    # Agent 2: CTA. Entirely absent CTA is deterministic grade 9.
    # NOTE: "absent" is detected purely by both source cells being blank/NaN
    # (safe_get() normalizes those to the literal string 'N/A'). This does
    # NOT parse free-text notes like "Not performed" or "Deferred" left in
    # a non-blank cell — such text is treated as a real report and sent to
    # the LLM, which will typically grade it 0 rather than 9. Input files
    # must leave CTA Head/Neck result cells truly blank when not performed;
    # see SETUP INSTRUCTIONS STEP 3 at the top of this file.
    cta_performed = not (ctah_text == 'N/A' and ctan_text == 'N/A')
    if cta_performed:
        tqdm.write(f"  {label} | Agent 2/6 CTA...")
        cta = call_model(CTA_GRADING_PROMPT.format(ctah_text=ctah_text, ctan_text=ctan_text), 'CTA')
        calls_made += 1; time.sleep(SLEEP_SEC)
        cta = qc_check_cta_grade1(cta, qc_flags)
        cta = qc_check_cta_grade4(cta, qc_flags)
    else:
        cta = {'CTA_Notable_Finding':''}
    cta = normalize_cta_grades(cta, cta_performed, qc_flags)

    # Agent 3: CTP only when explicit perfusion terminology exists.
    if is_ctp_likely_performed(ctah_text, ctan_text):
        tqdm.write(f"  {label} | Agent 3/6 CTP...")
        ctp = call_model(CTP_GATE_PROMPT.format(ctah_text=ctah_text, ctan_text=ctan_text), 'CTP')
        calls_made += 1; time.sleep(SLEEP_SEC)
        ctp['CTP_Performed'] = normalize_yes_no_na(ctp.get('CTP_Performed'), 'No')
        ctp['CTP_Technical_Quality'] = normalize_quality(
            ctp.get('CTP_Technical_Quality'), ctp['CTP_Performed'] == 'Yes')
        ctp['CTP_Deficit'] = normalize_yes_no_na(
            ctp.get('CTP_Deficit'), 'N/A' if ctp['CTP_Performed'] != 'Yes' else 'No')
        if ctp['CTP_Performed'] != 'Yes':
            ctp['CTP_Deficit'] = 'N/A'
            ctp['CTP_Technical_Quality'] = 'N/A'
        elif ctp['CTP_Technical_Quality'] == 'Nondiagnostic':
            ctp['CTP_Deficit'] = 'N/A'
        elif ctp['CTP_Deficit'] == 'Yes' and not str(ctp.get('CTP_Evidence','')).strip():
            qc_flags.append('CTP diagnostic deficit Yes but evidence snippet is blank')
    else:
        ctp = {'CTP_Performed':'No','CTP_Technical_Quality':'N/A',
               'CTP_Deficit':'N/A','CTP_Evidence':''}

    # Agent 4: MRI core. MRA is not queried (derived in Python).
    mri_performed = mri_text not in (None, '', 'N/A')
    if mri_performed:
        tqdm.write(f"  {label} | Agent 4/6 MRI core...")
        mri = call_model(MRI_CORE_PROMPT.format(mri_text=mri_text), 'MRI-Core')
        calls_made += 1; time.sleep(SLEEP_SEC)
    else:
        mri = {}
    mri = apply_mri_rules(mri, mri_text, mri_performed, qc_flags)

    # Agent 5: acute localization only when acute infarct is positive.
    if mri_performed and mri.get('MRI_Acute_Infarct') == 'Yes':
        tqdm.write(f"  {label} | Agent 5/6 MRI acute localization...")
        loc = call_model(MRI_ACUTE_LOCALIZATION_PROMPT.format(
            acute_snippet=mri.get('MRI_Acute_Evidence',''), mri_text=mri_text), 'MRI-AcuteLoc')
        calls_made += 1; time.sleep(SLEEP_SEC)
        mri.update(loc)

    # Agent 6: chronic localization independently runs when chronic infarct is positive.
    if mri_performed and mri.get('MRI_Chronic_Infarct') == 'Yes':
        tqdm.write(f"  {label} | Agent 6/6 MRI chronic localization...")
        snippet = mri.get('MRI_Chronic_Location') or mri.get('MRI_Chronic_Evidence','')
        loc = call_model(MRI_CHRONIC_LOCALIZATION_PROMPT.format(
            chronic_snippet=snippet, mri_text=mri_text), 'MRI-ChronicLoc')
        calls_made += 1; time.sleep(SLEEP_SEC)
        mri.update(loc)

    # Reapply dependency rules after localization.
    mri = apply_mri_rules(mri, mri_text, mri_performed, qc_flags)
    acute_yes = mri.get('MRI_Acute_Infarct') == 'Yes'
    chronic_yes = mri.get('MRI_Chronic_Infarct') == 'Yes'
    mri['MRI_Acute_Chronic_Coexist'] = (
        'Yes' if acute_yes and chronic_yes else ('No' if mri_performed else 'N/A'))
    mri['MRI_Any_Infarct'] = (
        'Yes' if acute_yes or chronic_yes else ('No' if mri_performed else 'N/A'))

    if mri_performed:
        cth = qc_check_cth_indeterminate_resolved_by_mri(cth, mri, qc_flags)

    qc_flags = list(dict.fromkeys(qc_flags))

    confidence_score, confidence_reason = compute_confidence(
        cth, cta, ctp, mri, qc_flags, cth_text, ctah_text, ctan_text, mri_text, mri_performed,
        cta_performed=cta_performed)

    tqdm.write(f"  {label} | ✅ case complete ({calls_made} LLM calls)")

    cth_keys = ['CTH_Source','CTH_Acute_Finding','CTH_Acute_Indeterminate',
                'CTH_Acute_Evidence','CTH_Acute_Type','CTH_Microvascular',
                'CTH_Microvascular_Evidence']
    cta_keys = ['CTA_R_Vert','CTA_R_Vert_Evidence','CTA_L_Vert','CTA_L_Vert_Evidence',
                'CTA_Basilar','CTA_Basilar_Evidence','CTA_R_ICA','CTA_R_ICA_Evidence',
                'CTA_L_ICA','CTA_L_ICA_Evidence','CTA_R_MCA','CTA_R_MCA_Evidence',
                'CTA_L_MCA','CTA_L_MCA_Evidence','CTA_Notable_Finding']
    ctp_keys = ['CTP_Performed','CTP_Technical_Quality','CTP_Deficit','CTP_Evidence']
    mri_keys = ['MRI_Technical_Quality','MRI_Acute_Infarct','MRI_Acute_Evidence',
                'MRI_Acute_Territory','MRI_Acute_Bilateral','MRI_Chronic_Infarct',
                'MRI_Chronic_Location','MRI_Chronic_Evidence','MRI_Chronic_Territory',
                'MRI_Chronic_Bilateral','MRI_Other_Abnormality',
                'MRI_Other_Abnormality_Type','MRI_Other_Abnormality_Evidence','MRI_MRA_Included','MRI_MRA_Evidence',
                'MRI_Acute_Chronic_Coexist','MRI_Any_Infarct']

    return {
        'Time_to_CTH_hrs':t_cth,'Time_to_CTA_hrs':t_cta,'Time_to_MRI_hrs':t_mri,
        **{k:cth.get(k,'') for k in cth_keys},
        **{k:cta.get(k,'') for k in cta_keys},
        **{k:ctp.get(k,'') for k in ctp_keys},
        **{k:mri.get(k,'') for k in mri_keys},
        'Confidence_Score':confidence_score,'Confidence_Reason':confidence_reason,
        'AI_QC_Flags':' | '.join(dict.fromkeys(qc_flags)),'LLM_Calls_Made':calls_made,
        'AI_Processed':'Yes','AI_Error_Detail':'',
        'AI_Timestamp':datetime.now().strftime('%Y-%m-%d %H:%M')
    }


# ── CELL 10: REDCap export builder ───────────────────────────
def build_redcap_export(df: pd.DataFrame, path: str):
    """Converts v12 pipeline output to a REDCap-importable CSV."""
    def col_or_blank(col):
        return df[col] if col in df.columns else pd.Series([''] * len(df), index=df.index)

    def fmt_dt(v):
        try:    return pd.to_datetime(v).strftime('%-m/%-d/%Y %-H:%M')
        except: return ''
    def fmt_date(v):
        try:    return pd.to_datetime(v).strftime('%-m/%-d/%Y')
        except: return ''
    def to_int(v):
        try:
            s = str(v).strip()
            return '' if s in ['', 'nan', 'None'] else str(int(float(s)))
        except: return ''
    def yn(v):
        return {'Yes': '1', 'No': '0', 'yes': '1', 'no': '0'}.get(str(v).strip(), '')
    def map_cth_acute(row):
        v = str(row['CTH_Acute_Finding']).strip()
        if v == 'No Acute':  return '0'
        if v in ('N/A', ''): return ''
        if v == 'Acute':
            t = str(row.get('CTH_Acute_Type', 'N/A')).strip()
            # v13.4.4: CTH_Acute_Type no longer distinguishes hemorrhage compartment (SDH is
            # excluded entirely — it's never a qualifying acute stroke finding on CTH). Any
            # legacy ICH/SAH/IVH value still maps to the REDCap "Hemorrhage" code (1) as a
            # safety net for older re-runs.
            if t in ('Hemorrhage', 'ICH', 'SAH', 'IVH'):
                return '1'
            return {'Ischemic Infarct': '2', 'Mass/Edema': '3'}.get(t, '4')
        return ''
    def map_micro(v):
        return {'Present': '1', 'Not Present': '0'}.get(str(v).strip(), '')
    def map_mri_acute(v):
        return {'Yes': '1', 'No': '0'}.get(str(v).strip(), '')
    def map_territory(v):
        return {'Posterior': '1', 'Anterior': '2', 'Both': '3'}.get(str(v).strip(), '')

    out = pd.DataFrame()
    out['record_id']           = col_or_blank(COL_ID)
    out['encounter_datetime']  = col_or_blank(COL_ARRIVAL).apply(fmt_dt)
    out['cth_datetime']        = col_or_blank(COL_CTH_TIME).apply(fmt_dt)
    out['ctah_datetime']       = col_or_blank(COL_CTAH_TIME).apply(fmt_dt)
    out['mri_datetime']        = col_or_blank(COL_MRI_TIME).apply(fmt_dt)
    out['time_to_cth_hrs']     = df['Time_to_CTH_hrs']
    out['time_to_ctah_hrs']    = df['Time_to_CTA_hrs']
    out['time_to_mri_hrs']     = df['Time_to_MRI_hrs']

    out['cth_source']              = df['CTH_Source']
    out['cth_acute']                = df.apply(map_cth_acute, axis=1)
    out['cth_acute_evidence']       = col_or_blank('CTH_Acute_Evidence').fillna('')
    out['cth_microvascular']        = df['CTH_Microvascular'].apply(map_micro)
    out['cth_microvascular_evidence'] = col_or_blank('CTH_Microvascular_Evidence').fillna('')

    for grade_col, out_col in [('CTA_R_Vert', 'v_r_vert'), ('CTA_L_Vert', 'v_l_vert'),
                                ('CTA_Basilar', 'v_basilar'), ('CTA_R_ICA', 'ant_r_ica'),
                                ('CTA_L_ICA', 'ant_l_ica'), ('CTA_R_MCA', 'ant_r_mca'),
                                ('CTA_L_MCA', 'ant_l_mca')]:
        out[out_col] = df[grade_col].apply(to_int)
        out[f"{out_col}_evidence"] = col_or_blank(f"{grade_col}_Evidence").fillna('')
    out['cta_notable'] = df['CTA_Notable_Finding'].fillna('')

    out['ctp_performed']  = df['CTP_Performed'].apply(yn)
    out['ctp_deficit']    = df['CTP_Deficit'].apply(yn)
    out['ctp_evidence']   = col_or_blank('CTP_Evidence').fillna('')

    out['mri_mra_included']            = col_or_blank('MRI_MRA_Included').apply(yn)
    out['mri_mra_evidence']            = col_or_blank('MRI_MRA_Evidence').fillna('')
    out['mri_other_abnormality']       = col_or_blank('MRI_Other_Abnormality').apply(yn)
    out['mri_other_abnormality_type']  = col_or_blank('MRI_Other_Abnormality_Type').fillna('')
    out['mri_other_abnormality_evidence'] = col_or_blank('MRI_Other_Abnormality_Evidence').fillna('')

    out['mri_acute_infarct']            = df['MRI_Acute_Infarct'].apply(map_mri_acute)
    out['mri_acute_evidence']           = col_or_blank('MRI_Acute_Evidence').fillna('')
    out['mri_acute_territory']          = df['MRI_Acute_Territory'].apply(map_territory)
    out['mri_acute_territory_evidence'] = col_or_blank('MRI_Acute_Territory_Evidence').fillna('')
    out['mri_acute_bilateral']          = df['MRI_Acute_Bilateral'].apply(yn)
    out['mri_acute_bilateral_evidence'] = col_or_blank('MRI_Acute_Bilateral_Evidence').fillna('')

    out['mri_chronic_infarct']            = df['MRI_Chronic_Infarct'].apply(yn)
    out['mri_chronic_location']           = col_or_blank('MRI_Chronic_Location').fillna('')
    out['mri_chronic_evidence']           = col_or_blank('MRI_Chronic_Evidence').fillna('')
    out['mri_chronic_territory']          = df['MRI_Chronic_Territory'].apply(map_territory)
    out['mri_chronic_territory_evidence'] = col_or_blank('MRI_Chronic_Territory_Evidence').fillna('')
    out['mri_chronic_bilateral']          = df['MRI_Chronic_Bilateral'].apply(yn)
    out['mri_chronic_bilateral_evidence'] = col_or_blank('MRI_Chronic_Bilateral_Evidence').fillna('')

    out['ai_confidence']     = df['Confidence_Score'].apply(to_int)
    out['ai_confidence_reason'] = col_or_blank('Confidence_Reason').fillna('')
    out['ai_qc_flags']       = col_or_blank('AI_QC_Flags').fillna('')
    out['ai_llm_calls_made'] = col_or_blank('LLM_Calls_Made').apply(to_int)
    out['ai_model_version']  = LLM_MODEL_NAME
    out['ai_processed_date'] = df['AI_Timestamp'].apply(
        lambda x: fmt_date(str(x).split(' ')[0]) if pd.notna(x) else '')
    out.to_csv(path, index=False)
    print(f"✅ REDCap export saved → {path} ({len(out)} rows, {len(out.columns)} columns)")





def load_source_dataframe(path: str) -> pd.DataFrame:
    """Load source dataset from .xlsx, .xls, .csv, or .tsv.

    CSV loading uses pandas' Python engine with sep=None so comma vs tab
    delimiters are auto-detected. This is helpful when an Excel sheet is
    exported as CSV/TSV from Excel, Numbers, or Epic-derived tools.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx", ".xlsm", ".xls"]:
        return pd.read_excel(path)
    if ext in [".csv", ".tsv", ".txt"]:
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, sep=None, engine="python", encoding="latin1")
    raise ValueError(
        f"Unsupported input file extension: {ext}. Use .xlsx, .xls, .csv, .tsv, or .txt"
    )


# ── CELL 11: Main pipeline loop ───────────────────────────────
def run_pipeline():
    """
    Main execution loop.
    - Loads or creates output Excel from input file
    - Skips already-processed rows (resume-safe)
    - Saves checkpoint every CHECKPOINT_N rows
    - Builds REDCap export CSV on completion
    """
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_EXCEL_PATH)), exist_ok=True)

    # Load existing output or build from source
    if os.path.exists(OUTPUT_EXCEL_PATH):
        print(f"⏳ Loading existing output file...", end=" ")
        df = pd.read_excel(OUTPUT_EXCEL_PATH)
        done = (df['AI_Processed'] == 'Yes').sum() if 'AI_Processed' in df.columns else 0
        print(f"✅ {len(df)} rows loaded ({done} already processed — will skip).")
    else:
        print("📂 Output file not found — loading source data...")
        if not os.path.exists(INPUT_FILE_PATH):
            raise FileNotFoundError(
                f"\n❌ Input file not found: {INPUT_FILE_PATH}"
                f"\n   Check INPUT_FILE_PATH in Cell 3 and confirm the file is in Drive."
            )
        df = load_source_dataframe(INPUT_FILE_PATH)
        df.to_excel(OUTPUT_EXCEL_PATH, index=False)
        print(f"✅ {len(df)} rows loaded and saved to output file.")

    # Ensure all output columns exist
    for col in OUTPUT_COLS:
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].astype(object)

    # Build work list
    if TEST_MODE:
        candidates = list(range(0, min(10, len(df))))
        print("🧪 TEST MODE — processing first 10 rows only.")
    else:
        candidates = list(range(START_IDX, len(df)))

    to_run  = [i for i in candidates if str(df.at[i, 'AI_Processed']) != 'Yes']
    err_log = []

    est_min = len(to_run) * 5 * SLEEP_SEC / 60
    print(f"\n{'='*62}")
    print(f"  Agentic Radiology Abstraction Pipeline")
    print(f"  Model         : {LLM_MODEL_NAME}")
    print(f"  Mode          : {'TEST (10 rows)' if TEST_MODE else 'FULL RUN'}")
    print(f"  Total rows    : {len(df)}")
    print(f"  To process    : {len(to_run)}")
    print(f"  Already done  : {len(candidates) - len(to_run)}")
    print(f"  Agents        : 6 conditional (CTH, CTA, CTP, MRI core, acute/chronic localization)")
    print(f"  Est. time     : ~{est_min:.0f} min (varies — 2-6 LLM calls/case depending on cascade path)")
    print(f"{'='*62}\n")

    if not to_run:
        print("🎉 All cases already processed. Building REDCap export...")
        build_redcap_export(df, REDCAP_EXPORT_PATH)
        return

    pbar = tqdm(to_run, unit="case", desc="Processing",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")

    for i in pbar:
        row = df.iloc[i]
        pid = row.get(COL_ID, f'row_{i}')
        pbar.set_postfix_str(f"ID={pid}")

        try:
            result = process_row(row, f"[{i+1}/{len(df)}] ID {pid}")
            for col, val in result.items():
                df.at[i, col] = val
        except Exception as e:
            df.at[i, 'AI_Processed']    = 'Error'
            df.at[i, 'AI_Error_Detail'] = str(e)[:300]
            df.at[i, 'AI_Timestamp']    = datetime.now().strftime('%Y-%m-%d %H:%M')
            err_log.append({'row': i, COL_ID: pid, 'error': traceback.format_exc()})
            tqdm.write(f"  ❌ ID {pid}: {str(e)[:100]}")

        if (i + 1) % CHECKPOINT_N == 0:
            df.to_excel(OUTPUT_EXCEL_PATH, index=False)
            tqdm.write(
                f"  💾 Checkpoint saved — "
                f"{(df['AI_Processed']=='Yes').sum()}/{len(df)} done"
            )

    # Final save
    df.to_excel(OUTPUT_EXCEL_PATH, index=False)
    if err_log:
        pd.DataFrame(err_log).to_csv(ERROR_LOG_PATH, index=False)
        print(f"⚠️  {len(err_log)} errors logged → {ERROR_LOG_PATH}")

    done = (df['AI_Processed'] == 'Yes').sum()
    errs = (df['AI_Processed'] == 'Error').sum()
    print(f"\n{'='*62}")
    print(f"  ✅ Completed : {done}")
    print(f"  ❌ Errors    : {errs}")
    print(f"  📁 Output    : {OUTPUT_EXCEL_PATH}")
    print(f"{'='*62}")

    print("\n⏳ Building REDCap export...")
    build_redcap_export(df, REDCAP_EXPORT_PATH)

    # Result preview
    print("\n📋 RESULT PREVIEW (processed rows):")
    preview_cols = [
        COL_ID, 'CTH_Acute_Finding', 'CTH_Microvascular',
        'CTP_Performed', 'CTP_Deficit',
        'MRI_Acute_Infarct', 'MRI_Acute_Territory',
        'MRI_Chronic_Infarct', 'MRI_Chronic_Territory',
        'Time_to_CTH_hrs', 'Time_to_MRI_hrs',
        'Confidence_Score', 'LLM_Calls_Made', 'AI_QC_Flags', 'AI_Processed'
    ]
    done_df = df[df['AI_Processed'] == 'Yes']
    display(done_df[[c for c in preview_cols if c in done_df.columns]].head(10))

    flagged = done_df['AI_QC_Flags'].astype(str).str.len().gt(0).sum() if 'AI_QC_Flags' in done_df.columns else 0
    print(f"\n🔎 Heuristic QC overrides: {flagged}/{len(done_df)} cases had at least one flag "
          f"(see AI_QC_Flags column / REDCap 'ai_qc_flags' for details)")

    if 'LLM_Calls_Made' in done_df.columns and len(done_df):
        call_counts = done_df['LLM_Calls_Made'].value_counts().sort_index()
        avg_calls = done_df['LLM_Calls_Made'].mean()
        print(f"\n📞 Cascade call distribution (avg {avg_calls:.2f} LLM calls/case):")
        for n_calls, n_cases in call_counts.items():
            print(f"     {n_calls} calls: {n_cases} cases ({100*n_cases/len(done_df):.1f}%)")


# ██████████████████████████████████████████████████████████
# ██                                                      ██
# ██   CELL 12: RUN                                       ██
# ██                                                      ██
# ██   1. Set TEST_MODE = True in Cell 3 for first run    ██
# ██   2. Verify output looks correct in preview table    ██
# ██   3. Set TEST_MODE = False and re-run for full data  ██
# ██   4. If interrupted: just re-run — skips done rows   ██
# ██                                                      ██
# ██████████████████████████████████████████████████████████

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Terminal-ready agentic radiology abstraction pipeline")
    parser.add_argument("--input", default=INPUT_FILE_PATH, help="Input .xlsx or .csv file")
    parser.add_argument("--output", default=OUTPUT_EXCEL_PATH, help="Output .xlsx file")
    parser.add_argument("--redcap", default=REDCAP_EXPORT_PATH, help="REDCap import CSV path")
    parser.add_argument("--error-log", default=ERROR_LOG_PATH, help="Error log CSV path")
    parser.add_argument("--api-key", default=None, help="AI Hub API key; safer to use LLM_API_KEY env var")
    parser.add_argument("--ad-object-id", default=None, help="AI Hub AD object ID; safer to use LLM_AUTH_ID env var")
    parser.add_argument("--aih-url", default=LLM_API_URL, help="Full AI Hub /generative endpoint URL")
    parser.add_argument("--model", default=LLM_MODEL_NAME, help="AI Hub model name, default gemini-2.5-flash")
    parser.add_argument("--full", action="store_true", help="Process the full dataset instead of first 10 rows")
    parser.add_argument("--start-idx", type=int, default=START_IDX, help="0-based row index to start/resume")
    parser.add_argument("--checkpoint-n", type=int, default=CHECKPOINT_N, help="Checkpoint every N rows")
    parser.add_argument("--sleep-sec", type=float, default=SLEEP_SEC, help="Sleep between sub-agent calls")
    args = parser.parse_args()

    INPUT_FILE_PATH = args.input
    OUTPUT_EXCEL_PATH = args.output
    REDCAP_EXPORT_PATH = args.redcap
    ERROR_LOG_PATH = args.error_log
    LLM_MODEL_NAME = args.model
    TEST_MODE = not args.full
    START_IDX = args.start_idx
    CHECKPOINT_N = args.checkpoint_n
    SLEEP_SEC = args.sleep_sec

    configure_llm(args.api_key, args.ad_object_id, args.aih_url, args.model)
    run_pipeline()
