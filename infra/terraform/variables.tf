# =============================================================================
# Input Variables
# =============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "smad-pickleball"
}

variable "region" {
  description = "GCP Region for resources"
  type        = string
  default     = "us-west1"
}

variable "environment" {
  description = "Environment name (prod, staging, dev)"
  type        = string
  default     = "prod"
}

# -----------------------------------------------------------------------------
# Google Sheets Configuration
# -----------------------------------------------------------------------------

variable "spreadsheet_id" {
  description = "Google Sheets Spreadsheet ID"
  type        = string
  default     = "1w4_-hnykYgcs6nyyDkie9CwBRwri7aJUblD2mxgNUHY"
}

variable "main_sheet_name" {
  description = "Main sheet name in the spreadsheet"
  type        = string
  default     = "2026 Pickleball"
}

# -----------------------------------------------------------------------------
# WhatsApp Group Configuration
# -----------------------------------------------------------------------------

variable "smad_whatsapp_group_id" {
  description = "SMAD WhatsApp group ID for polls"
  type        = string
  default     = ""  # Set via terraform.tfvars or environment
}

variable "admin_dinkers_group_id" {
  description = "Admin Dinkers WhatsApp group ID for notifications"
  type        = string
  default     = ""  # Set via terraform.tfvars or environment
}

# -----------------------------------------------------------------------------
# Cloud Function Configuration
# -----------------------------------------------------------------------------

variable "function_memory" {
  description = "Memory allocation for Cloud Functions (MB)"
  type        = number
  default     = 512
}

variable "function_timeout" {
  description = "Timeout for Cloud Functions (seconds)"
  type        = number
  default     = 60
}

variable "function_runtime" {
  description = "Python runtime version"
  type        = string
  default     = "python311"
}
