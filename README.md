# DizzyCTA Agentic Pipeline v13.5.2 — Code Repository

**Study:** A Multi-Agent Large Language Model Pipeline for Structured Abstraction of Stroke-Workup Neuroimaging Reports: Design, Prevalence-Informed Validation, and Potential for Large-Scale Retrospective and Prospective Cohort Curation

**Author:** Yasir El-Sherif, MD, PhD  
Department of Neurology, Staten Island University Hospital (Northwell Health)  
yelsherif@northwell.edu

## Overview

This repository contains the cleaned pipeline code, prompt templates, statistical analysis scripts, and documentation for the DizzyCTA Agentic Pipeline v13.5.2 — a four-agent sequential LLM pipeline that abstracts structured clinical variables from stroke-workup neuroimaging reports (CT head, CTA head/neck, CT perfusion, and MRI brain) across a 719-case retrospective cohort.

The pipeline was developed through 14 major versions (v1.0–v13.5.2) using a four-phase strategy: single-model disagreement-driven iteration, multi-model agreement optimization, frontier-model refinement, and prevalence-informed enrichment design.

## Repository Structure

```
code_repository/
├── agentic_radiology_pipeline_v13_5_2.py   # Main pipeline (cleaned, ~2000 lines)
├── requirements.txt                        # Python dependencies
├── LICENSE                                  # MIT License
├── CODE_AVAILABILITY_STATEMENT.txt          # For manuscript
├── README.md                                # This file
├── analysis/                                # R statistical analysis scripts
│   ├── wilson_ci.R                          # Wilson CI + sample size functions
│   ├── cohen_kappa.R                        # Inter-model and human-AI kappa
│   ├── accuracy_metrics.R                   # Field-level accuracy + confusion matrices
│   ├── prevalence_estimation.R              # Multi-model prevalence + enrichment power
│   └── run_all.R                           # Master script (sources all above)
└── docs/
    ├── data_dictionary.md                   # Field definitions, allowed values, tiers
    └── prompt_templates_reference.md        # Agent prompt schemas and decision rules
```

## Setup

### Python (pipeline)
```bash
pip install -r requirements.txt

# Set environment variables for your LLM API
export LLM_API_KEY="your-api-key"
export LLM_AUTH_ID="your-auth-id"
export LLM_API_URL="https://your-llm-api-endpoint.example.com/generative"
export LLM_MODEL="claude-sonnet-4.6"  # or other supported model
```

### R (analysis)
```R
install.packages(c("psych", "irr"))  # optional, for kappa verification
source("analysis/run_all.R")
```

## Usage

```python
# Run the pipeline on an Excel file with radiology report columns
python agentic_radiology_pipeline_v13_5_2.py --input reports.xlsx --output results.xlsx
```

The input Excel file must have columns: `ID`, `ED Arrival`, `First CTH Result`, `First CTAH Result`, `First CTAN Result`, `First MRB Result`.

## Data Availability

- **Pipeline code, prompts, schemas, QC logic, and analysis scripts:** Available in this repository (MIT license)
- **Raw radiology report text and patient-identifiable data:** NOT available due to IRB data-governance restrictions
- **Structured output dataset (719 cases) and human-review comparison (148 cases):** Available from corresponding author upon reasonable request, subject to Northwell Health IRB approval

## Code Development Disclosure

Pipeline development was conducted by the investigator with AI-assisted coding tools (Anthropic Claude, OpenAI ChatGPT) under direct clinical supervision. All clinical decision rules, output schemas, quality-control logic, and refinement criteria were specified by the investigator; the AI tools were used for code implementation only.

## License

MIT License — see [LICENSE](LICENSE) file.

## Citation

If you use this code or methodology in your research, please cite:

> El-Sherif Y. A Multi-Agent Large Language Model Pipeline for Structured Abstraction of Stroke-Workup Neuroimaging Reports: Design, Prevalence-Informed Validation, and Potential for Large-Scale Retrospective and Prospective Cohort Curation. [Journal name]. [Year].
