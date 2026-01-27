# =============================================================================
# Secret Manager Configuration
# =============================================================================
# Defines the structure of secrets. Actual secret VALUES are not stored here.
# Secret values should be set manually via console or gcloud CLI.
#
# Import existing secrets:
#   terraform import google_secret_manager_secret.venmo_token projects/smad-pickleball/secrets/VENMO_ACCESS_TOKEN
#   terraform import google_secret_manager_secret.google_creds projects/smad-pickleball/secrets/SMAD_GOOGLE_CREDENTIALS_JSON
#   (repeat for each secret)
# =============================================================================

# -----------------------------------------------------------------------------
# Secret Definitions
# -----------------------------------------------------------------------------

resource "google_secret_manager_secret" "venmo_token" {
  secret_id = "VENMO_ACCESS_TOKEN"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_secret_manager_secret" "google_creds" {
  secret_id = "SMAD_GOOGLE_CREDENTIALS_JSON"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_secret_manager_secret" "greenapi_instance_id" {
  secret_id = "GREENAPI_INSTANCE_ID"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_secret_manager_secret" "greenapi_api_token" {
  secret_id = "GREENAPI_API_TOKEN"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Secret IAM Bindings
# -----------------------------------------------------------------------------
# Grant Cloud Functions access to specific secrets

resource "google_secret_manager_secret_iam_member" "venmo_token_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.venmo_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa_email}"
}

resource "google_secret_manager_secret_iam_member" "google_creds_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_creds.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa_email}"
}

resource "google_secret_manager_secret_iam_member" "greenapi_instance_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.greenapi_instance_id.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa_email}"
}

resource "google_secret_manager_secret_iam_member" "greenapi_token_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.greenapi_api_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_sa_email}"
}
