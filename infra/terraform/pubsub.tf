# =============================================================================
# Cloud Pub/Sub Configuration
# =============================================================================
# Pub/Sub topics and subscriptions for event-driven processing.
#
# Import existing:
#   terraform import google_pubsub_topic.venmo_emails projects/smad-pickleball/topics/venmo-payment-emails
# =============================================================================

# -----------------------------------------------------------------------------
# Venmo Payment Emails Topic
# -----------------------------------------------------------------------------
# Receives notifications from Gmail API when Venmo payment emails arrive

resource "google_pubsub_topic" "venmo_emails" {
  name    = "venmo-payment-emails"
  project = var.project_id

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  # Message retention for replay capability
  message_retention_duration = "86400s" # 24 hours
}

# -----------------------------------------------------------------------------
# Dead Letter Topic (Optional)
# -----------------------------------------------------------------------------
# For failed message processing - uncomment if needed

# resource "google_pubsub_topic" "venmo_emails_dlq" {
#   name    = "venmo-payment-emails-dlq"
#   project = var.project_id
#
#   labels = {
#     environment = var.environment
#     managed_by  = "terraform"
#   }
# }

# -----------------------------------------------------------------------------
# Subscription (created automatically by Eventarc for Cloud Functions)
# -----------------------------------------------------------------------------
# Note: When using Eventarc triggers with Cloud Functions Gen2,
# the subscription is created automatically. We don't need to manage it here.
