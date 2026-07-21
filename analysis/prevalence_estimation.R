# ╔══════════════════════════════════════════════════════════════════╗
# ║  Prevalence Estimation and Enrichment Power Functions             ║
# ║  DizzyCTA Agentic Pipeline v13.5.2 — Statistical Analysis         ║
# ║  Author: Yasir El-Sherif, MD, PhD                                 ║
# ║  Description: Multi-model consensus prevalence and Wilson-based    ║
# ║               enrichment sample size calculation                  ║
# ╚══════════════════════════════════════════════════════════════════╝

#' Estimate finding prevalence from multi-model consensus
#'
#' Uses majority vote across multiple model outputs to estimate
#' the population prevalence of a finding.
#'
#' @param df Data frame with model output columns
#' @param field Field name to estimate prevalence for
#' @param model_cols Character vector of model column names
#' @param positive_value The value representing a positive finding (e.g., "Yes", "1")
#' @return List with prevalence, count, n_total, per_model_estimates
#'
#' @examples
#' estimate_prevalence(df, "CTA_Basilar", c("Claude_Basilar", "GPT5_Basilar", "Gemini_Basilar"), positive_value = "1")
estimate_prevalence <- function(df, field, model_cols, positive_value = "Yes") {
  n_total <- nrow(df)
  per_model <- numeric(length(model_cols))
  names(per_model) <- model_cols

  for (i in seq_along(model_cols)) {
    col <- model_cols[i]
    vals <- tolower(trimws(as.character(df[[col]])))
    pos_count <- sum(vals == tolower(positive_value), na.rm = TRUE)
    per_model[i] <- pos_count / n_total
  }

  # Majority vote: positive if >= 50% of models agree
  votes <- sapply(1:n_total, function(row_idx) {
    vals <- sapply(model_cols, function(col) {
      v <- tolower(trimws(as.character(df[[col]][row_idx])))
      v == tolower(positive_value)
    })
    if (sum(vals, na.rm = TRUE) >= ceiling(length(model_cols) / 2)) 1 else 0
  })

  consensus_positive <- sum(votes)
  prevalence <- consensus_positive / n_total

  list(
    field = field,
    prevalence = round(prevalence, 4),
    count = consensus_positive,
    n_total = n_total,
    per_model_prevalence = round(per_model, 4)
  )
}

#' Calculate enrichment sample size needed
#'
#' Given the prevalence of a finding and a target number of positive
#' cases, calculates how many total cases would be needed under pure
#' random sampling.
#'
#' @param prevalence Estimated prevalence of the finding (0-1)
#' @param target_positives Minimum number of positive cases needed (default 14)
#' @return Integer total sample size needed
#'
#' @examples
#' power_for_enrichment(0.046, 14)  # Basilar: 4.6% prevalence → need 305 cases
power_for_enrichment <- function(prevalence, target_positives = 14) {
  ceiling(target_positives / prevalence)
}

#' Full enrichment design table
#'
#' @param prevalence_df Data frame with findings and their prevalence
#' @param target_positives Target positive cases per finding
#' @return data.frame with enrichment recommendations
enrichment_design <- function(prevalence_df, target_positives = 14) {
  prevalence_df$n_random_needed <- ceiling(target_positives / prevalence_df$prevalence)
  prevalence_df$enrichment_needed <- prevalence_df$n_random_needed > 150

  cat("\n=== Enrichment Design Summary ===\n")
  cat(sprintf("  Target: >= %d positive cases per finding\n\n", target_positives))

  for (i in 1:nrow(prevalence_df)) {
    row <- prevalence_df[i, ]
    cat(sprintf("  %-30s  prevalence=%.1f%%  n_random=%d  enrichment=%s\n",
                row$finding, row$prevalence * 100, row$n_random_needed,
                ifelse(row$enrichment_needed, "YES", "no")))
  }

  return(prevalence_df)
}

# ── Study-specific prevalence estimates ──────────────────────────────
# These were computed from the 719-case cohort using three-way model consensus
# (Claude Sonnet 4.6, GPT-5.4, Gemini 3.5 Flash)

study_prevalence <- data.frame(
  finding = c("CTH_Acute_Finding", "CTH_Hemorrhage", "MRI_Acute_Infarct",
              "MRI_Chronic_Infarct", "CTA_R_Vert_abnormal", "CTA_L_Vert_abnormal",
              "CTA_Basilar_abnormal", "CTA_R_ICA_abnormal", "CTA_L_ICA_abnormal"),
  prevalence = c(0.070, 0.021, 0.107, 0.263, 0.198, 0.170, 0.046, 0.107, 0.087)
)

cat("\n=== Study Prevalence Estimates (719-case cohort) ===\n")
enrichment_design(study_prevalence, target_positives = 14)
