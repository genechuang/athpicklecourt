# =============================================================================
# Terraform Backend Configuration
# =============================================================================
# Stores Terraform state in Google Cloud Storage for team collaboration
# and state locking.
#
# Initial Setup (run once):
#   1. Create the GCS bucket:
#      gsutil mb -p smad-pickleball -l us-west1 gs://smad-pickleball-terraform-state
#   2. Enable versioning:
#      gsutil versioning set on gs://smad-pickleball-terraform-state
#   3. Initialize Terraform:
#      terraform init
# =============================================================================

terraform {
  backend "gcs" {
    bucket = "smad-pickleball-terraform-state"
    prefix = "terraform/state"
  }
}
