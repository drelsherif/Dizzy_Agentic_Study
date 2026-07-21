# ╔══════════════════════════════════════════════════════════════════╗
# ║  Field-Level Accuracy and Confusion Matrix Functions              ║
# ║  DizzyCTA Agentic Pipeline v13.5.2 — Statistical Analysis         ║
# ║  Author: Yasir El-Sherif, MD, PhD                                 ║
# ╚══════════════════════════════════════════════════════════════════╝

#' Field-level accuracy (exact categorical agreement)
#'
#' @param human Vector of human reviewer ratings
#' @param ai Vector of AI pipeline ratings
#' @return List with accuracy, concordant count, total, discordant count
#'
#' @examples
#' field_accuracy(human$CTA_Basilar, ai$CTA_Basilar)
field_accuracy <- function(human, ai) {
  # Normalize: strip whitespace, convert to lowercase for comparison
  h <- tolower(trimws(as.character(human)))
  a <- tolower(trimws(as.character(ai)))

  # Remove NA pairs
  valid <- !is.na(h) & h != "" & !is.na(a) & a != "" &
           h != "nan" & a != "nan"
  h <- h[valid]
  a <- a[valid]

  n <- length(h)
  if (n == 0) return(list(accuracy = NA, concordant = 0, total = 0, discordant = 0))

  concordant <- sum(h == a)
  discordant <- n - concordant
  accuracy <- concordant / n

  list(
    accuracy = round(accuracy, 4),
    concordant = concordant,
    total = n,
    discordant = discordant
  )
}

#' Confusion matrix with row/col labels
#'
#' @param human Vector of human reviewer ratings (reference)
#' @param ai Vector of AI pipeline ratings (comparator)
#' @return Labeled confusion matrix table
#'
#' @examples
#' confusion_matrix(human$CTA_R_Vert, ai$CTA_R_Vert)
confusion_matrix <- function(human, ai) {
  h <- trimws(as.character(human))
  a <- trimws(as.character(ai))

  valid <- !is.na(h) & h != "" & !is.na(a) & a != ""
  h <- factor(h[valid])
  a <- factor(a[valid], levels = levels(h))

  tbl <- table(Human = h, Claude = a)
  return(tbl)
}

#' Overall accuracy across all fields
#'
#' @param df Data frame with human and AI columns
#' @param human_cols Character vector of human column names
#' @param ai_cols Character vector of AI column names (parallel to human_cols)
#' @return data.frame with per-field accuracy and overall summary
overall_accuracy <- function(df, human_cols, ai_cols) {
  results <- data.frame(
    Field = character(),
    Accuracy = numeric(),
    Concordant = integer(),
    Discordant = integer(),
    Total = integer()
  )

  for (i in seq_along(human_cols)) {
    result <- field_accuracy(df[[human_cols[i]]], df[[ai_cols[i]]])
    results <- rbind(results, data.frame(
      Field = human_cols[i],
      Accuracy = result$accuracy,
      Concordant = result$concordant,
      Discordant = result$discordant,
      Total = result$total
    ))
  }

  # Overall
  total_conc <- sum(results$Concordant)
  total_disc <- sum(results$Discordant)
  total_all <- sum(results$Total)
  overall_acc <- total_conc / total_all

  cat("\n=== Field-Level Accuracy Summary ===\n")
  print(results, row.names = FALSE)
  cat(sprintf("\n  OVERALL: %.4f (%d/%d)\n", overall_acc, total_conc, total_all))

  return(list(
    per_field = results,
    overall_accuracy = round(overall_acc, 4),
    total_concordant = total_conc,
    total_discordant = total_disc,
    total_comparisons = total_all
  ))
}

# ── Study-specific field definitions ─────────────────────────────────
# Fields for comparison (parallel human and AI column names)

human_fields <- c(
  "CTH_Acute_Finding", "CTH_Acute_Type", "CTH_Microvascular",
  "CTA_R_Vert", "CTA_L_Vert", "CTA_Basilar",
  "CTA_R_ICA", "CTA_L_ICA", "CTA_R_MCA", "CTA_L_MCA",
  "CTP_Performed", "CTP_Deficit",
  "MRI_Acute_Infarct", "MRI_Acute_Territory", "MRI_Acute_Bilateral",
  "MRI_Chronic_Infarct", "MRI_Chronic_Territory", "MRI_Chronic_Bilateral",
  "MRI_Other_Abnormality", "MRI_Other_Abnormality_Type", "MRI_MRA_Included"
)

# Expected results from the study (n=148):
# Tier 1 mean accuracy: 0.966
# Tier 2 mean accuracy: 0.946
# Overall: 0.939 (2524/2688 field comparisons)
