# =============================================================================
# SMAD PickleBot - Terraform Configuration
# =============================================================================
# This Terraform configuration manages GCP infrastructure for SMAD PickleBot.
#
# To import existing resources:
#   terraform import google_pubsub_topic.venmo_emails projects/smad-pickleball/topics/venmo-payment-emails
#   terraform import google_cloudfunctions2_function.whatsapp_webhook projects/smad-pickleball/locations/us-west1/functions/smad-whatsapp-webhook
#   terraform import google_cloudfunctions2_function.venmo_sync projects/smad-pickleball/locations/us-west1/functions/venmo-sync-trigger
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Provider Configuration
# -----------------------------------------------------------------------------

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

# Reference existing project (we don't create it, just reference it)
data "google_project" "smad" {
  project_id = var.project_id
}

# Get project number for IAM bindings
data "google_project" "current" {
  project_id = var.project_id
}
