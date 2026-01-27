# =============================================================================
# IAM Configuration
# =============================================================================
# Service accounts and IAM bindings for SMAD PickleBot.
#
# Import existing service account:
#   terraform import google_service_account.bot projects/smad-pickleball/serviceAccounts/smad-pickleball-bot@smad-pickleball.iam.gserviceaccount.com
# =============================================================================

# -----------------------------------------------------------------------------
# Service Account for the Bot (Optional - currently using github-deploy)
# -----------------------------------------------------------------------------
# Note: Currently the project uses 'github-deploy' service account for CI/CD
# and the default compute service account for Cloud Functions.
# Uncomment below to create a dedicated bot service account if needed.

# resource "google_service_account" "bot" {
#   account_id   = "smad-pickleball-bot"
#   display_name = "SMAD Pickleball Bot"
#   description  = "Service account for SMAD PickleBot automation"
#   project      = var.project_id
# }

# resource "google_project_iam_member" "bot_secret_accessor" {
#   project = var.project_id
#   role    = "roles/secretmanager.secretAccessor"
#   member  = "serviceAccount:${google_service_account.bot.email}"
# }

# -----------------------------------------------------------------------------
# Cloud Functions Service Account
# -----------------------------------------------------------------------------

# The default Compute Engine service account used by Cloud Functions
locals {
  compute_sa_email = "${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}

# Allow Cloud Functions to access secrets
resource "google_project_iam_member" "functions_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${local.compute_sa_email}"
}

# -----------------------------------------------------------------------------
# Gmail API Push Notifications
# -----------------------------------------------------------------------------

# Allow Gmail to publish to Pub/Sub
# This is a Google-managed service account that sends push notifications
resource "google_pubsub_topic_iam_member" "gmail_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.venmo_emails.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
}
