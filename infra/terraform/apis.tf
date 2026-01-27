# =============================================================================
# Google Cloud APIs
# =============================================================================
# Enable required APIs for the project.
#
# Import existing:
#   terraform import google_project_service.sheets smad-pickleball/sheets.googleapis.com
#   terraform import google_project_service.gmail smad-pickleball/gmail.googleapis.com
#   (repeat for each API)
# =============================================================================

locals {
  required_apis = [
    "sheets.googleapis.com",           # Google Sheets API
    "gmail.googleapis.com",            # Gmail API (for watch notifications)
    "secretmanager.googleapis.com",    # Secret Manager
    "cloudfunctions.googleapis.com",   # Cloud Functions
    "cloudbuild.googleapis.com",       # Cloud Build (required for Functions)
    "run.googleapis.com",              # Cloud Run (Gen2 Functions backend)
    "pubsub.googleapis.com",           # Pub/Sub
    "eventarc.googleapis.com",         # Eventarc (Gen2 Functions triggers)
    "artifactregistry.googleapis.com", # Artifact Registry (Functions container images)
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project = var.project_id
  service = each.value

  # Don't disable APIs when removing from Terraform
  # This prevents accidental destruction of dependent resources
  disable_on_destroy = false
}
