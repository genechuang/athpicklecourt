# =============================================================================
# Cloud Functions (Gen2) Configuration
# =============================================================================
# Cloud Functions for webhook handling and event processing.
#
# Note: Cloud Functions Gen2 are deployed via gcloud or GitHub Actions
# because they require source code upload. This file defines the infrastructure
# aspects but the actual deployment happens in the CI/CD pipeline.
#
# Import existing:
#   terraform import google_cloudfunctions2_function.whatsapp_webhook projects/smad-pickleball/locations/us-west1/functions/smad-whatsapp-webhook
#   terraform import google_cloudfunctions2_function.venmo_sync projects/smad-pickleball/locations/us-west1/functions/venmo-sync-trigger
# =============================================================================

# -----------------------------------------------------------------------------
# Storage Bucket for Function Source Code
# -----------------------------------------------------------------------------
# Cloud Functions Gen2 can use Cloud Build, but having a dedicated bucket
# for source archives is useful for versioning and rollbacks

resource "google_storage_bucket" "function_source" {
  name     = "${var.project_id}-function-source"
  location = var.region
  project  = var.project_id

  # Automatically delete old versions after 30 days
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  # Enable versioning for rollback capability
  versioning {
    enabled = true
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  # Prevent accidental deletion
  force_destroy = false
}

# -----------------------------------------------------------------------------
# WhatsApp Webhook Function
# -----------------------------------------------------------------------------
# HTTP-triggered function for WhatsApp poll vote webhooks
#
# Note: This function is deployed via GitHub Actions (deploy-webhook.yml).
# Terraform manages the infrastructure definition but ignores runtime changes.

resource "google_cloudfunctions2_function" "whatsapp_webhook" {
  name     = "smad-whatsapp-webhook"
  location = var.region
  project  = var.project_id

  build_config {
    runtime     = var.function_runtime
    entry_point = "webhook"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = "whatsapp-webhook/source.zip"
      }
    }
  }

  service_config {
    # Allow unauthenticated access (webhook endpoint)
    ingress_settings               = "ALLOW_ALL"
    all_traffic_on_latest_revision = true
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  # Ignore changes managed by CI/CD deployment
  lifecycle {
    ignore_changes = [
      build_config,
      service_config[0].available_memory,
      service_config[0].max_instance_count,
      service_config[0].timeout_seconds,
      service_config[0].environment_variables,
      service_config[0].secret_environment_variables,
    ]
  }
}

# Allow unauthenticated invocations
resource "google_cloud_run_service_iam_member" "whatsapp_webhook_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.whatsapp_webhook.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# -----------------------------------------------------------------------------
# Venmo Sync Trigger Function
# -----------------------------------------------------------------------------
# Pub/Sub-triggered function for processing Venmo payment notifications
#
# Note: This function is deployed via GitHub Actions (deploy-webhook.yml).
# Terraform manages the infrastructure definition but ignores runtime changes.

resource "google_cloudfunctions2_function" "venmo_sync" {
  name     = "venmo-sync-trigger"
  location = var.region
  project  = var.project_id

  build_config {
    runtime     = var.function_runtime
    entry_point = "venmo_email_trigger"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = "venmo-trigger/source.zip"
      }
    }
  }

  service_config {
    ingress_settings               = "ALLOW_ALL"
    all_traffic_on_latest_revision = true
  }

  # Pub/Sub trigger
  event_trigger {
    trigger_region = var.region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.venmo_emails.id
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  # Ignore changes managed by CI/CD deployment
  lifecycle {
    ignore_changes = [
      build_config,
      service_config[0].available_memory,
      service_config[0].max_instance_count,
      service_config[0].timeout_seconds,
      service_config[0].environment_variables,
      service_config[0].secret_environment_variables,
      service_config[0].ingress_settings,
      event_trigger[0].retry_policy,
    ]
  }

  depends_on = [
    google_project_service.apis["cloudfunctions.googleapis.com"],
    google_project_service.apis["run.googleapis.com"],
    google_project_service.apis["eventarc.googleapis.com"],
  ]
}
