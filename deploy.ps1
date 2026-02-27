# ============================================
# Persistent Memory - Deployment Script
# ============================================
# Voraussetzungen:
#   - Supabase CLI installiert (scoop install supabase)
#   - supabase login bereits ausgefuehrt
#
# Verwendung:
#   .\deploy.ps1
#   .\deploy.ps1 -SkipMigrations   # Nur Edge Function deployen
# ============================================

param(
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"

$PROJECT_DIR = $PSScriptRoot
$PROJECT_REF = "naatzputlsusiiczltzp"
$FUNCTION_URL = "https://$PROJECT_REF.supabase.co/functions/v1/memory-manager"

Write-Host ""
Write-Host "=== Persistent Memory Deployment ===" -ForegroundColor Cyan
Write-Host "Projekt: $PROJECT_DIR" -ForegroundColor Gray
Write-Host ""

# --- Schritt 1: Projekt verlinken ---
Write-Host "[1/4] Pruefe Supabase-Verlinkung..." -ForegroundColor Yellow
Set-Location $PROJECT_DIR

$linkedRef = $null
if (Test-Path "$PROJECT_DIR\supabase\.temp\project-ref") {
    $linkedRef = (Get-Content "$PROJECT_DIR\supabase\.temp\project-ref" -Raw).Trim()
}

if ($linkedRef -ne $PROJECT_REF) {
    Write-Host "  Verlinke Projekt..." -ForegroundColor Gray
    supabase link --project-ref $PROJECT_REF
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FEHLER: Projekt konnte nicht verlinkt werden." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  Projekt verlinkt: $PROJECT_REF" -ForegroundColor Green

# --- Schritt 2: Migrations ausfuehren ---
if (-not $SkipMigrations) {
    Write-Host ""
    Write-Host "[2/4] Fuehre Datenbank-Migrations aus..." -ForegroundColor Yellow
    supabase db push
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FEHLER: Migration fehlgeschlagen." -ForegroundColor Red
        Write-Host "  Alternative: SQL manuell im Supabase Dashboard ausfuehren." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Migrations erfolgreich." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[2/4] Migrations uebersprungen (-SkipMigrations)" -ForegroundColor Gray
}

# --- Schritt 3: Edge Function deployen ---
Write-Host ""
Write-Host "[3/4] Deploye Edge Function..." -ForegroundColor Yellow
supabase functions deploy memory-manager --no-verify-jwt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FEHLER: Function Deployment fehlgeschlagen." -ForegroundColor Red
    exit 1
}
Write-Host "  Edge Function deployed." -ForegroundColor Green

# --- Schritt 4: Funktionstest ---
Write-Host ""
Write-Host "[4/4] Teste Endpoint..." -ForegroundColor Yellow

# API_SECRET aus Umgebungsvariable oder .env lesen
$apiSecret = $env:API_SECRET
if (-not $apiSecret) {
    $envFile = "$PROJECT_DIR\.env"
    if (Test-Path $envFile) {
        foreach ($line in (Get-Content $envFile)) {
            if ($line -match "^API_SECRET=(.+)$") {
                $apiSecret = $matches[1].Trim('"').Trim("'")
            }
        }
    }
}

if (-not $apiSecret) {
    Write-Host "  WARNUNG: API_SECRET nicht gefunden (weder env noch .env)." -ForegroundColor Yellow
    Write-Host "  Manuell testen:" -ForegroundColor Gray
    Write-Host "  curl -s -H `"Authorization: Bearer DEIN_SECRET`" `"$FUNCTION_URL?action=load_session`"" -ForegroundColor Gray
} else {
    try {
        $headers = @{ "Authorization" = "Bearer $apiSecret" }
        $response = Invoke-RestMethod -Uri "$FUNCTION_URL`?action=load_session" -Headers $headers -Method Get
        if ($response.success -eq $true) {
            Write-Host "  Endpoint antwortet korrekt." -ForegroundColor Green
            $coreCount = $response.core.count
            $activeCount = $response.active.count
            $sessionsCount = $response.recent_sessions.count
            Write-Host "  Core: $coreCount | Active: $activeCount | Sessions: $sessionsCount" -ForegroundColor Gray
        } else {
            Write-Host "  WARNUNG: Unerwartete Antwort." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  FEHLER beim Test: $_" -ForegroundColor Red
    }
}

# --- Zusammenfassung ---
Write-Host ""
Write-Host "=== Deployment abgeschlossen ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Endpoint: $FUNCTION_URL" -ForegroundColor White
Write-Host ""
