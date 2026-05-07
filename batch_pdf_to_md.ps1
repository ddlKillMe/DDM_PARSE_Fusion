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

$InputDir = Join-Path $ScriptDir "dataset_claim_network"
$OutputDir = Join-Path $ScriptDir "dataset_claim_network_md"

# Convert all PDFs to Markdown preserving directory structure
Get-ChildItem -Path $InputDir -Filter "*.pdf" -File -Recurse | ForEach-Object {
    $pdfPath = $_.FullName
    
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

    Write-Host "Converting: $pdfPath`n       Out: $targetOutDir"
    marker_single "$pdfPath" --output_dir "$targetOutDir"
}

Write-Host "All done!" -ForegroundColor Green