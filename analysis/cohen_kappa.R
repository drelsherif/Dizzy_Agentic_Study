# ╔══════════════════════════════════════════════════════════════════╗
# ║  Cohen's Kappa Functions                                          ║
# ║  DizzyCTA Agentic Pipeline v13.5.2 — Statistical Analysis         ║
# ║  Author: Yasir El-Sherif, MD, PhD                                 ║
# ║  Description: Inter-model and human-AI kappa calculations        ║
# ║               using the 'psych' package with robust fallbacks.   ║
# ╚══════════════════════════════════════════════════════════════════╝

#' Compute Cohen's Kappa between two raters
#'
#' Handles missing values, normalizes strings (trimming and lowercasing),
#' and uses the 'psych' package to compute Cohen's Kappa with confidence intervals.
#' If 'psych' is not available, falls back to an analytical calculation.
#'
#' @param rater1 Vector of ratings from rater 1
#' @param rater2 Vector of ratings from rater 2
#' @param conf_level Confidence level for the interval (default 0.95)
#' @return A data frame containing kappa, lower CI, upper CI, observed agreement, and sample size
#' @export
#'
#' @examples
#' compute_kappa(human$CTA_R_Vert, ai$CTA_R_Vert)
compute_kappa <- function(rater1, rater2, conf_level = 0.95) {
  # Normalize strings: coerce to character, trim whitespace, and convert to lowercase
  r1_norm <- tolower(trimws(as.character(rater1)))
  r2_norm <- tolower(trimws(as.character(rater2)))

  # Handle missing values: complete cases only
  valid <- !is.na(r1_norm) & r1_norm != "" & r1_norm != "nan" & r1_norm != "na" &
           !is.na(r2_norm) & r2_norm != "" & r2_norm != "nan" & r2_norm != "na"
  
  r1_clean <- r1_norm[valid]
  r2_clean <- r2_norm[valid]

  n <- length(r1_clean)
  if (n < 2) {
    warning("Fewer than 2 valid overlapping observations. Returning NA.")
    return(data.frame(
      kappa = NA_real_,
      lower = NA_real_,
      upper = NA_real_,
      observed_agreement = NA_real_,
      n = n
    ))
  }

  # Check if there is variation in ratings to avoid errors
  if (length(unique(r1_clean)) == 1 && length(unique(r2_clean)) == 1 && r1_clean[1] == r2_clean[1]) {
    return(data.frame(
      kappa = 1.0000,
      lower = 1.0000,
      upper = 1.0000,
      observed_agreement = 1.0000,
      n = n
    ))
  }

  # Primary calculation using psych package
  if (requireNamespace("psych", quietly = TRUE)) {
    ratings_df <- data.frame(Rater1 = r1_clean, Rater2 = r2_clean, stringsAsFactors = FALSE)
    
    res <- tryCatch({
      k_res <- psych::cohen.kappa(ratings_df, alpha = 1 - conf_level)
      
      # Extract unweighted kappa and confidence interval
      kappa_val <- k_res$kappa
      ci <- k_res$conf.int
      
      # Safe row extraction
      row_idx <- which(rownames(ci) == "unweighted kappa")
      if (length(row_idx) == 0) row_idx <- 1
      
      lower_val <- ci[row_idx, "lower"]
      upper_val <- ci[row_idx, "upper"]
      po_val <- k_res$agree[1] # Observed agreement
      
      data.frame(
        kappa = round(kappa_val, 4),
        lower = round(lower_val, 4),
        upper = round(upper_val, 4),
        observed_agreement = round(po_val, 4),
        n = n
      )
    }, error = function(e) {
      # Fallback if psych fails due to layout or other runtime issues
      return(compute_kappa_manual(r1_clean, r2_clean, conf_level))
    })
    
    return(res)
  } else {
    # Fallback to manual asymptotic calculation
    return(compute_kappa_manual(r1_clean, r2_clean, conf_level))
  }
}

#' Manual computation of Cohen's Kappa (fallback)
#'
#' @keywords internal
compute_kappa_manual <- function(r1, r2, conf_level = 0.95) {
  n <- length(r1)
  
  # Observed agreement
  po <- sum(r1 == r2) / n

  # Expected agreement (marginal products)
  cats <- unique(c(r1, r2))
  pe <- sum(sapply(cats, function(c) {
    (sum(r1 == c) / n) * (sum(r2 == c) / n)
  }))

  # Kappa
  kappa <- if (pe == 1) 1 else (po - pe) / (1 - pe)

  # Asymptotic SE and CI
  se_kappa <- sqrt((po * (1 - po)) / (n * (1 - pe)^2))
  z <- qnorm(1 - (1 - conf_level)/2)
  ci_lower <- max(-1, kappa - z * se_kappa)
  ci_upper <- min(1, kappa + z * se_kappa)

  data.frame(
    kappa = round(kappa, 4),
    lower = round(ci_lower, 4),
    upper = round(ci_upper, 4),
    observed_agreement = round(po, 4),
    n = n
  )
}

#' Compute pairwise kappa across multiple model columns
#'
#' Computes pairwise Cohen's Kappa for all unique pairs of columns in model_cols.
#'
#' @param df Data frame containing all model outputs
#' @param model_cols Character vector of column names for each model
#' @return A tidy data frame with pairwise comparison results
#' @export
#'
#' @examples
#' multi_model_kappa(data, c("Claude_R_Vert", "GPT5_R_Vert", "Gemini_R_Vert"))
multi_model_kappa <- function(df, model_cols) {
  if (!requireNamespace("dplyr", quietly = TRUE)) {
    stop("Package 'dplyr' is required for multi_model_kappa.")
  }
  
  n_models <- length(model_cols)
  results_list <- list()
  counter <- 1
  
  for (i in 1:(n_models - 1)) {
    for (j in (i + 1):n_models) {
      col1 <- model_cols[i]
      col2 <- model_cols[j]
      
      k_res <- compute_kappa(df[[col1]], df[[col2]])
      
      results_list[[counter]] <- dplyr::tibble(
        model1 = col1,
        model2 = col2,
        kappa = k_res$kappa,
        lower = k_res$lower,
        upper = k_res$upper,
        observed_agreement = k_res$observed_agreement,
        n_complete = k_res$n
      )
      counter <- counter + 1
    }
  }
  
  results_df <- dplyr::bind_rows(results_list)
  
  # Generate a matrix representation for console printing
  kappa_matrix <- matrix(NA, n_models, n_models, dimnames = list(model_cols, model_cols))
  diag(kappa_matrix) <- 1.0000
  for (row in 1:nrow(results_df)) {
    m1 <- results_df$model1[row]
    m2 <- results_df$model2[row]
    val <- results_df$kappa[row]
    kappa_matrix[m1, m2] <- val
    kappa_matrix[m2, m1] <- val
  }
  
  mean_kappa <- mean(results_df$kappa, na.rm = TRUE)
  
  cat(sprintf("\n=== Pairwise Kappa Matrix (n=%d models, %d pairs) ===\n", n_models, nrow(results_df)))
  print(round(kappa_matrix, 4))
  cat(sprintf("  Mean Pairwise Kappa: %.4f\n", mean_kappa))
  
  # Return both the tidy data frame and the matrix representation as a list
  return(list(
    tidy_results = results_df,
    matrix = kappa_matrix,
    mean_kappa = round(mean_kappa, 4)
  ))
}

#' Compute kappa across all fields for two raters
#'
#' @param df Data frame with both raters' outputs
#' @param rater1_prefix Prefix for rater 1 columns (e.g., "Claude_")
#' @param rater2_prefix Prefix for rater 2 columns (e.g., "Human_")
#' @param fields Character vector of field names (without prefix)
#' @return data.frame with per-field kappa values
all_field_kappa <- function(df, rater1_prefix, rater2_prefix, fields) {
  results <- data.frame(
    Field = character(),
    Kappa = numeric(),
    Lower = numeric(),
    Upper = numeric(),
    Agreement = numeric(),
    N = integer(),
    stringsAsFactors = FALSE
  )

  for (field in fields) {
    col1 <- paste0(rater1_prefix, field)
    col2 <- paste0(rater2_prefix, field)

    if (col1 %in% names(df) && col2 %in% names(df)) {
      result <- compute_kappa(df[[col1]], df[[col2]])
      results <- rbind(results, data.frame(
        Field = field,
        Kappa = result$kappa,
        Lower = result$lower,
        Upper = result$upper,
        Agreement = result$observed_agreement,
        N = result$n,
        stringsAsFactors = FALSE
      ))
    }
  }

  cat("\n=== Per-Field Kappa ===\n")
  print(results, row.names = FALSE)
  cat(sprintf("\n  Mean kappa: %.4f\n", mean(results$Kappa, na.rm = TRUE)))

  return(results)
}

# ── Study fields ─────────────────────────────────────────────────────
tier1_fields <- c(
  "CTH_Acute_Finding", "CTH_Acute_Type", "CTH_Microvascular",
  "CTA_R_Vert", "CTA_L_Vert", "CTA_Basilar",
  "MRI_Acute_Infarct", "MRI_Chronic_Infarct"
)

tier2_fields <- c(
  "CTA_R_ICA", "CTA_L_ICA", "CTA_R_MCA", "CTA_L_MCA",
  "CTH_Acute_Indeterminate", "CTP_Performed", "CTP_Deficit",
  "MRI_Acute_Territory", "MRI_Acute_Bilateral",
  "MRI_Chronic_Territory", "MRI_Chronic_Bilateral",
  "MRI_Other_Abnormality", "MRI_Other_Abnormality_Type", "MRI_MRA_Included"
)
