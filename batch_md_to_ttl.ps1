$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Get-Location
}

# Activate virtual environment
$ActivateScript = Join-Path $ScriptDir ".venv\Scripts\Activate.ps1"
if (Test-Path $ActivateScript) {
    . $ActivateScript
    Write-Host "Activated virtual environment." -ForegroundColor Green
} else {
    Write-Warning "Cannot find virtual environment at $ActivateScript"
}

$InputDir = Join-Path $ScriptDir "dataset_claim_network_md"
$OutputDir = Join-Path $ScriptDir "dataset_claim_network_ttl_new"
$MarkerScript = Join-Path $ScriptDir "code\PARSE\Papers\Pipeline\marker2ttl_NewOntology.py"

if (-not (Test-Path $MarkerScript)) {
    Write-Error "Cannot find marker2ttl_NewOntology.py at $MarkerScript"
    exit 1
}

# Create output base directory if it doesn't exist
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

# Convert all Markdown to TTL preserving directory structure
Get-ChildItem -Path $InputDir -Filter "*.md" -File -Recurse | ForEach-Object {
    $mdPath = $_.FullName
    
    # Calculate relative directory path to maintain structure
    $fileDirectory = $_.DirectoryName
    $relativeDir = ""
    if ($fileDirectory.Length -gt $InputDir.Length) {
        $relativeDir = $fileDirectory.Substring($InputDir.Length).TrimStart('\', '/')
    }
    
    $targetOutDir = Join-Path $OutputDir $relativeDir
    
    # Create target directory if it doesn't exist
    if (-not (Test-Path $targetOutDir)) {
        New-Item -ItemType Directory -Force -Path $targetOutDir | Out-Null
    }

    Write-Host "Converting: $mdPath`n       Out: $targetOutDir"
    
    # Run the Python script
    & python $MarkerScript -i "$mdPath" -o "$targetOutDir"
}

Write-Host "All done!" -ForegroundColor Green
