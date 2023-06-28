/*
 * Copyright 2023 Google. This software is provided as-is, without warranty or 
 * representation for any use or purpose. Your use of it is subject to your 
 * agreement with Google.  
*/

# Local variables to be configured
locals {
    region = "us-central1"
}

data "google_client_config" "current" {
    # this reads the env var GOOGLE_PROJECT=<projectid>
}

data "archive_file" "function_source" {
    type = "zip"
    source_dir = "${path.module}/function_source"
    output_path = "function_source.zip"
}

resource "google_storage_bucket" "gcf_source_bucket" {
  name     = "${data.google_client_config.current.project}-x-gcf-source"  # Every bucket name must be globally unique
  location = "US"
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "gcf_source_object" {
  name   = "function-source.zip"
  bucket = google_storage_bucket.gcf_source_bucket.name
  source = data.archive_file.function_source.output_path
}

resource "google_storage_bucket" "subscriber_listing_bucket" {
  name     = "${data.google_client_config.current.project}_subscriber_listing"  # Every bucket name must be globally unique
  location = "US"
  uniform_bucket_level_access = true
  force_destroy = true
}

resource "google_service_account" "service_account" {
  account_id   = "expired-subs-sa"
  display_name = "Service Account for identifying expired service accounts"
  project = data.google_client_config.current.project
}

resource "google_cloudfunctions_function" "function" {
  name = "expiration-identifier"
  region = local.region
  description = "Expired Subscription Identifier"
  runtime = "python311"

  entry_point = "main"  
  trigger_http = true
  service_account_email = google_service_account.service_account.email


  source_archive_bucket = google_storage_bucket.gcf_source_bucket.name
  source_archive_object = google_storage_bucket_object.gcf_source_object.name

  environment_variables = {
    PROJECT_ID = data.google_client_config.current.project,
    BUCKET = google_storage_bucket.subscriber_listing_bucket.name
    # LOG_LEVEL = "DEBUG" # defaults to INFO
    # Causes a re-deploy of the function when the source changes
    SOURCE_SHA = data.archive_file.function_source.output_sha
  }
}




resource "google_project_iam_member" "gcs_iam" {
  role = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.service_account.email}"
  project = google_cloudfunctions_function.function.project
}

resource "google_project_iam_member" "pubsub_iam" {
  role = "roles/pubsub.editor"
  member = "serviceAccount:${google_service_account.service_account.email}"
  project = google_cloudfunctions_function.function.project
}

resource "google_cloudfunctions_function_iam_member" "invoker" {
  project = google_cloudfunctions_function.function.project
  cloud_function = google_cloudfunctions_function.function.name
  region = google_cloudfunctions_function.function.region
  role = "roles/cloudfunctions.invoker"
  member = "serviceAccount:${google_service_account.service_account.email}"

  depends_on = [
    google_project_iam_member.gcs_iam,
    google_project_iam_member.pubsub_iam
  ]
}


resource "google_cloud_scheduler_job" "job" {
  name             = "expired-subscription-identifier-job"
  description      = "calls an HTTP function to identify expired subscriptions"
  schedule         = "0 * * * *" # every hour
  time_zone        = "America/New_York"
  attempt_deadline = "320s"

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions_function.function.https_trigger_url

    oidc_token {
        service_account_email = google_service_account.service_account.email
    }
  }

  region = local.region

}