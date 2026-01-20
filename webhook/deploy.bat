@echo off
REM Deploy SMAD WhatsApp Poll Webhook to Google Cloud Functions
REM
REM Prerequisites:
REM 1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
REM 2. Authenticate: gcloud auth login
REM 3. Set project: gcloud config set project YOUR_PROJECT_ID
REM 4. Enable APIs:
REM    gcloud services enable cloudfunctions.googleapis.com
REM    gcloud services enable firestore.googleapis.com
REM    gcloud services enable cloudbuild.googleapis.com
REM
REM Usage:
REM   deploy.bat [PROJECT_ID] [REGION]
REM
REM Example:
REM   deploy.bat smad-pickleball us-west1

setlocal enabledelayedexpansion

REM Configuration
set "PROJECT_ID=%~1"
set "REGION=%~2"
set "FUNCTION_NAME=smad-whatsapp-webhook"

REM Get default project if not specified
if "%PROJECT_ID%"=="" (
    for /f "tokens=*" %%i in ('gcloud config get-value project 2^>nul') do set "PROJECT_ID=%%i"
)

REM Set default region
if "%REGION%"=="" set "REGION=us-west1"

if "%PROJECT_ID%"=="" (
    echo ERROR: No project ID specified and none set in gcloud config.
    echo Usage: deploy.bat PROJECT_ID [REGION]
    exit /b 1
)

echo === Deploying SMAD WhatsApp Poll Webhook ===
echo Project: %PROJECT_ID%
echo Region: %REGION%
echo Function: %FUNCTION_NAME%
echo.

REM Check if Firestore is initialized
echo Checking Firestore...
gcloud firestore databases list --project="%PROJECT_ID%" 2>nul | findstr /C:"(default)" >nul
if errorlevel 1 (
    echo Firestore not initialized. Creating database...
    gcloud firestore databases create --project="%PROJECT_ID%" --location="%REGION%" --type=firestore-native
    echo Firestore database created.
) else (
    echo Firestore already initialized.
)

REM Deploy the function
echo.
echo Deploying Cloud Function...
gcloud functions deploy "%FUNCTION_NAME%" ^
    --project="%PROJECT_ID%" ^
    --region="%REGION%" ^
    --runtime=python311 ^
    --trigger-http ^
    --allow-unauthenticated ^
    --entry-point=webhook ^
    --source=. ^
    --memory=256MB ^
    --timeout=60s ^
    --gen2

if errorlevel 1 (
    echo.
    echo ERROR: Deployment failed!
    exit /b 1
)

REM Get the function URL
echo.
echo === Deployment Complete ===

for /f "tokens=*" %%i in ('gcloud functions describe "%FUNCTION_NAME%" --project="%PROJECT_ID%" --region="%REGION%" --gen2 --format="value(serviceConfig.uri)" 2^>nul') do set "FUNCTION_URL=%%i"

echo.
echo Webhook URL: %FUNCTION_URL%
echo.
echo === Next Steps ===
echo 1. Go to GREEN-API dashboard: https://console.green-api.com/
echo 2. Select your instance (ID: check your .env file)
echo 3. Go to 'Webhooks' or 'Instance Settings'
echo 4. Set webhook URL to: %FUNCTION_URL%
echo 5. Enable these webhook types:
echo    - incomingMessageReceived (for incoming poll votes)
echo    - outgoingMessageReceived (for polls you create)
echo.
echo 6. Add to your .env file:
echo    GCP_PROJECT_ID=%PROJECT_ID%
echo.

endlocal
