# Deploy only to the explicitly selected Supabase project.
# Usage: ./deploy.ps1 -ProjectRef <20-character-project-ref>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]{20}$')]
    [string]$ProjectRef,
    [switch]$SkipMigrations,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$functionUrl = "https://${ProjectRef}.supabase.co/functions/v1/memory-manager"
$smokeHeaders = @{}

# Fail before remote mutations; never search unrelated .env or home files.
if (-not $SkipSmokeTest) {
    if (-not [string]::IsNullOrWhiteSpace($env:API_SECRET_API)) {
        $smokeHeaders['Authorization'] = 'Bearer ' + $env:API_SECRET_API.Trim()
        $smokeHeaders['X-Memory-Client'] = 'api'
    } elseif (-not [string]::IsNullOrWhiteSpace($env:API_SECRET)) {
        $smokeHeaders['Authorization'] = 'Bearer ' + $env:API_SECRET.Trim()
    } else {
        Write-Error 'Smoke-Test benoetigt API_SECRET_API oder API_SECRET. Nur bewusst mit -SkipSmokeTest ueberspringen.'
        exit 1
    }
}

Write-Host "Deployment-Ziel: $ProjectRef"
Write-Host "Endpoint: $functionUrl"
Push-Location $PSScriptRoot
$stage = 'Projektverknuepfung'
try {
    & supabase link --project-ref $ProjectRef
    if ($LASTEXITCODE -ne 0) { throw 'CLI failure' }
    if (-not $SkipMigrations) {
        $stage = 'Datenbankmigrationen'
        & supabase db push --linked
        if ($LASTEXITCODE -ne 0) { throw 'CLI failure' }
    } else {
        Write-Host 'Migrationen bewusst uebersprungen.'
    }
    $stage = 'Edge Function Deployment'
    & supabase functions deploy memory-manager --project-ref $ProjectRef --no-verify-jwt
    if ($LASTEXITCODE -ne 0) { throw 'CLI failure' }
    if ($SkipSmokeTest) {
        Write-Host 'Smoke-Test bewusst uebersprungen; Endpoint nicht verifiziert.'
    } else {
        $stage = 'Smoke-Test'
        $response = Invoke-RestMethod -Uri ($functionUrl + '?action=load_session') -Headers $smokeHeaders -Method Get -TimeoutSec 30 -MaximumRedirection 0
        if ($response.success -ne $true -or $response.action -ne 'load_session') { throw 'Unexpected response' }
        Write-Host 'Smoke-Test erfolgreich.'
    }
    Write-Host 'Deployment abgeschlossen.'
} catch {
    # Avoid leaking remote bodies or credential-bearing request details.
    Write-Host "FEHLER: $stage fehlgeschlagen. Deployment nicht als erfolgreich bestaetigt."
    exit 1
} finally {
    Pop-Location
}
exit 0
