# ╔══════════════════════════════════════════════════════════════════╗
# ║  Wilson Score Confidence Interval Functions                        ║
# ║  DizzyCTA Agentic Pipeline v13.5.2 — Statistical Analysis         ║
# ║  Author: Yasir El-Sherif, MD, PhD                                 ║
# ║  Description: Wilson CI for proportion accuracy and sample size   ║
# ║               calculation for kappa significance testing          ║
# ╚══════════════════════════════════════════════════════════════════╝

#' Wilson Score Confidence Interval
#'
#' Computes the Wilson score interval for a binomial proportion.
#' Preferred over the normal approximation when sample sizes are small
#' or when the proportion is near 0 or 1.
#'
#' @param successes Number of successful outcomes (concordant cases)
#' @param n Total number of trials
#' @param conf_level Confidence level (default 0.95)
#' @return data.frame with lower, point_estimate, upper
#'
#' @examples
#' wilson_ci(143, 148)  # 96.6% accuracy with 95% CI
wilson_ci <- function(successes, n, conf_level = 0.95) {
  z <- qnorm(1 - (1 - conf_level) / 2)
  p <- successes / n
  denom <- 1 + z^2 / n
  center <- (p + z^2 / (2 * n)) / denom
  spread <- z * sqrt(p * (1 - p) / n + z^2 / (4 * n^2)) / denom

  data.frame(
    lower = round(center - spread, 4),
    point_estimate = round(p, 4),
    upper = round(center + spread, 4)
  )
}

#' Sample Size for Kappa Significance Test
#'
#' Calculates the required sample size to detect a kappa significantly
#' different from a null hypothesis value.
#'
#' Based on the formula: n = 2 * (z_alpha/2 + z_beta)^2 / (k_true - k_null)^2
#'
#' @param k_null Null hypothesis kappa value (e.g., 0.40 for "moderate agreement")
#' @param k_true Expected true kappa value
#' @param alpha Significance level (default 0.05)
#' @param power Desired statistical power (default 0.80)
#' @return Integer sample size required
#'
#' @examples
#' n_for_kappa(0.40, 0.966)  # n needed for Tier 1 accuracy
n_for_kappa <- function(k_null, k_true, alpha = 0.05, power = 0.80) {
  z_alpha <- qnorm(1 - alpha / 2)
  z_beta  <- qnorm(power)

  n <- ceiling(2 * (z_alpha + z_beta)^2 / (k_true - k_null)^2)
  return(n)
}

#' Sample Size with Bonferroni Correction
#'
#' @param k_null Null hypothesis kappa
#' @param k_true Expected true kappa
#' @param n_tests Number of simultaneous tests (for Bonferroni correction)
#' @param power Desired power
#' @return Integer sample size
n_for_kappa_bonferroni <- function(k_null, k_true, n_tests = 6, power = 0.80) {
  alpha_bonf <- 0.05 / n_tests
  n_for_kappa(k_null, k_true, alpha = alpha_bonf, power = power)
}

# ── Study-specific calculations ──────────────────────────────────────

# Tier 1 fields (n=8) — publication-critical
# Bonferroni-corrected alpha for 6 primary metrics: 0.05/6 = 0.0083
tier1_fields <- c(
  "CTH_Acute_Finding", "CTH_Acute_Type", "CTH_Microvascular",
  "CTA_R_Vert", "CTA_L_Vert", "CTA_Basilar",
  "MRI_Acute_Infarct", "MRI_Chronic_Infarct"
)

# Wilson CIs for Tier 1 accuracy (n=148)
cat("\n=== Tier 1 Accuracy with 95% Wilson CIs (n=148) ===\n")
tier1_accuracy <- c(
  CTH_Acute_Finding = 0.952,
  CTH_Acute_Type    = 0.980,
  CTA_R_Vert        = 0.979,
  CTA_L_Vert        = 0.993,
  CTA_Basilar       = 1.000,
  MRI_Acute_Infarct = 0.986,
  MRI_Chronic_Infarct = 0.912
)

for (field in names(tier1_accuracy)) {
  acc <- tier1_accuracy[field]
  n_pos <- round(acc * 148)
  ci <- wilson_ci(n_pos, 148)
  cat(sprintf("  %-25s  %.3f  [%.3f, %.3f]  n_needed(H0=0.40)=%d\n",
              field, acc, ci$lower, ci$upper,
              n_for_kappa(0.40, acc)))
}

# Power targets for enrichment
cat("\n=== Enrichment Power Targets ===\n")
prevalence <- c(basilar = 0.046, hemorrhage = 0.021, acute_infarct = 0.107,
                chronic_infarct = 0.263, r_vert = 0.198, l_vert = 0.170)

for (finding in names(prevalence)) {
  n_random <- ceiling(14 / prevalence[finding])
  cat(sprintf("  %-20s  prevalence=%.1f%%  n_random_needed=%d\n",
              finding, prevalence[finding] * 100, n_random))
}
