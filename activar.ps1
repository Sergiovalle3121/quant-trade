# activar.ps1 - entorno local quant-trade (todo en D:, nada en C:)
# Uso:  . .\activar.ps1     (con el punto delante, para que aplique en tu shell)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Caches fuera de C: ---
$env:PIP_CACHE_DIR = 'D:\dev\.cache\pip'
$env:TMP           = 'D:\dev\.cache\tmp'
$env:TEMP          = 'D:\dev\.cache\tmp'
$env:MYPY_CACHE_DIR = 'D:\dev\.cache\mypy'
$env:RUFF_CACHE_DIR = 'D:\dev\.cache\ruff'

foreach ($d in @($env:PIP_CACHE_DIR, $env:TMP, $env:MYPY_CACHE_DIR, $env:RUFF_CACHE_DIR)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force $d | Out-Null }
}

# --- Higiene: nada de builds accidentales ni escritura en site-packages global ---
$env:PYTHONDONTWRITEBYTECODE = ''
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:PIP_REQUIRE_VIRTUALENV = '1'

# --- venv ---
& "$repo\.venv\Scripts\Activate.ps1"

Write-Host "quant-trade listo" -ForegroundColor Green
Write-Host ("  python      : " + (& python -c "import sys; print(sys.executable)"))
Write-Host ("  PIP_CACHE_DIR: " + $env:PIP_CACHE_DIR)
Write-Host ("  TMP          : " + $env:TMP)
