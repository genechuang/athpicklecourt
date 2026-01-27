# SMAD PickleBot - Terraform Infrastructure

This directory contains Terraform configuration for managing GCP infrastructure for SMAD PickleBot.

## Prerequisites

1. **Terraform CLI** (v1.5+)
   ```powershell
   # Windows (via Chocolatey)
   choco install terraform

   # Or download from: https://www.terraform.io/downloads
   ```

2. **Google Cloud SDK**
   ```powershell
   # Authenticate
   gcloud auth login
   gcloud auth application-default login

   # Set project
   gcloud config set project smad-pickleball
   ```

3. **Permissions**
   - Your Google account needs `Owner` or `Editor` role on the project
   - For CI/CD, the service account needs appropriate IAM roles

## Initial Setup

### 1. Create State Bucket (One-time)

Terraform state is stored in GCS for collaboration and state locking.

```powershell
# Create bucket
gsutil mb -p smad-pickleball -l us-west1 gs://smad-pickleball-terraform-state

# Enable versioning
gsutil versioning set on gs://smad-pickleball-terraform-state

# Set lifecycle (keep 10 versions)
gsutil lifecycle set lifecycle.json gs://smad-pickleball-terraform-state
```

### 2. Initialize Terraform

```powershell
cd infra/terraform
terraform init
```

### 3. Import Existing Resources

Since the infrastructure already exists, we need to import it into Terraform state:

```powershell
# Service Account
terraform import google_service_account.bot projects/smad-pickleball/serviceAccounts/smad-pickleball-bot@smad-pickleball.iam.gserviceaccount.com

# Pub/Sub Topic
terraform import google_pubsub_topic.venmo_emails projects/smad-pickleball/topics/venmo-payment-emails

# Secrets (structure only, not values)
terraform import google_secret_manager_secret.venmo_token projects/smad-pickleball/secrets/VENMO_ACCESS_TOKEN
terraform import google_secret_manager_secret.google_creds projects/smad-pickleball/secrets/SMAD_GOOGLE_CREDENTIALS_JSON
terraform import google_secret_manager_secret.greenapi_instance_id projects/smad-pickleball/secrets/GREENAPI_INSTANCE_ID
terraform import google_secret_manager_secret.greenapi_api_token projects/smad-pickleball/secrets/GREENAPI_API_TOKEN

# Cloud Functions (Gen2)
terraform import google_cloudfunctions2_function.whatsapp_webhook projects/smad-pickleball/locations/us-west1/functions/smad-whatsapp-webhook
terraform import google_cloudfunctions2_function.venmo_sync projects/smad-pickleball/locations/us-west1/functions/venmo-sync-trigger
```

### 4. Create Variables File

```powershell
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

### 5. Plan and Apply

```powershell
# See what changes will be made
terraform plan

# Apply changes
terraform apply
```

## Directory Structure

```
infra/terraform/
├── main.tf              # Provider config, data sources
├── backend.tf           # GCS state backend
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── apis.tf              # Enabled GCP APIs
├── iam.tf               # Service accounts, IAM bindings
├── secrets.tf           # Secret Manager secrets (structure)
├── pubsub.tf            # Pub/Sub topics
├── functions.tf         # Cloud Functions (Gen2)
├── terraform.tfvars.example  # Example variables file
├── .gitignore           # Ignore state, vars, credentials
└── README.md            # This file
```

## Resources Managed

| Resource Type | Count | Description |
|---------------|-------|-------------|
| APIs | 9 | Sheets, Gmail, Functions, etc. |
| Service Account | 1 | smad-pickleball-bot |
| Secrets | 4 | Venmo, Google, GREEN-API |
| Pub/Sub Topic | 1 | venmo-payment-emails |
| Cloud Functions | 2 | whatsapp-webhook, venmo-sync |
| IAM Bindings | 5+ | Secret access, Pub/Sub publisher |

## Common Commands

```powershell
# Initialize (first time or after backend change)
terraform init

# Format code
terraform fmt

# Validate configuration
terraform validate

# Plan changes
terraform plan

# Apply changes
terraform apply

# Show current state
terraform show

# List resources in state
terraform state list

# Destroy (CAREFUL!)
terraform destroy
```

## GitHub Actions Integration

The workflow at `.github/workflows/terraform.yml` handles:

1. **On PR**: Runs `terraform plan` and comments on PR
2. **On merge to main**: Runs `terraform apply` automatically
3. **Manual trigger**: Can run plan, apply, or destroy

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | Service account JSON key (already exists) |

### Required GitHub Variables

| Variable | Description |
|----------|-------------|
| `SMAD_WHATSAPP_GROUP_ID` | SMAD group ID (already exists) |
| `ADMIN_DINKERS_WHATSAPP_GROUP_ID` | Admin group ID (already exists) |

## What's NOT in Terraform

These items are managed outside Terraform:

| Item | Reason |
|------|--------|
| Secret values | Security - stored in Secret Manager UI |
| OAuth tokens | User-specific browser auth |
| Google Sheet sharing | Not a GCP resource |
| Gmail watch | Requires OAuth, managed by script |
| Function source code | Deployed via CI/CD |
| GitHub Secrets/Variables | Different platform |

## Troubleshooting

### "Error acquiring state lock"

Another terraform process is running, or previous process crashed:

```powershell
# Force unlock (use with caution)
terraform force-unlock LOCK_ID
```

### "Resource already exists"

The resource exists but isn't in state. Import it:

```powershell
terraform import RESOURCE_TYPE.NAME RESOURCE_ID
```

### "Inconsistent dependency lock file"

Provider versions changed:

```powershell
terraform init -upgrade
```

### State Drift

Someone changed infrastructure via console:

```powershell
# See differences
terraform plan

# Refresh state from actual infrastructure
terraform refresh

# Or import the changes
terraform apply
```

## Security Notes

1. **Never commit**:
   - `terraform.tfvars` (contains group IDs)
   - `*.tfstate` files
   - Credential JSON files

2. **State file contains sensitive data**:
   - Stored encrypted in GCS
   - Access controlled via IAM

3. **Use least privilege**:
   - Service accounts have minimal required roles
   - Secrets are per-resource, not project-wide
