# =============================================================================
# Output Values
# =============================================================================
# Useful values to reference after terraform apply.
# =============================================================================

# -----------------------------------------------------------------------------
# Project Information
# -----------------------------------------------------------------------------

output "project_id" {
  description = "GCP Project ID"
  value       = var.project_id
}

output "project_number" {
  description = "GCP Project Number"
  value       = data.google_project.current.number
}

output "region" {
  description = "GCP Region"
  value       = var.region
}

# -----------------------------------------------------------------------------
# Service Account
# -----------------------------------------------------------------------------

# output "bot_service_account_email" {
#   description = "Bot service account email"
#   value       = google_service_account.bot.email
# }

output "compute_service_account_email" {
  description = "Default compute service account email (used by Cloud Functions)"
  value       = local.compute_sa_email
}

# -----------------------------------------------------------------------------
# Cloud Functions URLs
# -----------------------------------------------------------------------------

output "whatsapp_webhook_url" {
  description = "WhatsApp webhook function URL"
  value       = google_cloudfunctions2_function.whatsapp_webhook.service_config[0].uri
}

output "venmo_sync_function_name" {
  description = "Venmo sync function name"
  value       = google_cloudfunctions2_function.venmo_sync.name
}

# -----------------------------------------------------------------------------
# Pub/Sub
# -----------------------------------------------------------------------------

output "venmo_emails_topic" {
  description = "Pub/Sub topic for Venmo email notifications"
  value       = google_pubsub_topic.venmo_emails.name
}

output "venmo_emails_topic_id" {
  description = "Pub/Sub topic ID for Venmo email notifications"
  value       = google_pubsub_topic.venmo_emails.id
}

# -----------------------------------------------------------------------------
# Storage
# -----------------------------------------------------------------------------

output "function_source_bucket" {
  description = "GCS bucket for function source code"
  value       = google_storage_bucket.function_source.name
}

# -----------------------------------------------------------------------------
# Secrets
# -----------------------------------------------------------------------------

output "secret_ids" {
  description = "Secret Manager secret IDs"
  value = {
    venmo_token          = google_secret_manager_secret.venmo_token.secret_id
    google_creds         = google_secret_manager_secret.google_creds.secret_id
    greenapi_instance_id = google_secret_manager_secret.greenapi_instance_id.secret_id
    greenapi_api_token   = google_secret_manager_secret.greenapi_api_token.secret_id
  }
}
