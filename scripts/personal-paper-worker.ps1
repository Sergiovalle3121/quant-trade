param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$RepositoryPath,
    [Parameter(Mandatory=$true)][string]$StatePath,
    [string]$ExpensesPath = ""
)
$ErrorActionPreference = "Stop"
$taskRepo = (Resolve-Path -LiteralPath $RepositoryPath).Path
$taskPython = (Resolve-Path -LiteralPath $PythonPath).Path
$taskState = [System.IO.Path]::GetFullPath($StatePath)
New-Item -ItemType Directory -Path $taskState -Force | Out-Null
Set-Location -LiteralPath $taskRepo
$env:PYTHONPATH = Join-Path $taskRepo "src"
$taskArguments = @("-m", "quant_trade.personal_paper", "worker",
    "--config", (Join-Path $taskRepo "configs/personal/etf_private_v1.yaml"),
    "--database", (Join-Path $taskState "prospective.sqlite"),
    "--cache", (Join-Path $taskState "market-cache"))
if ($ExpensesPath) {
    $taskArguments += @("--expenses", (Resolve-Path -LiteralPath $ExpensesPath).Path)
}
$taskLog = Join-Path $taskState ("worker-" + (Get-Date -Format "yyyyMMdd") + ".log")
# Windows PowerShell 5.1 turns each redirected stderr line of a native command
# into an error record; under "Stop" the first warning would abort the wrapper,
# truncate the log and hide the worker's exit code. Only this call continues.
$ErrorActionPreference = "Continue"
& $taskPython @taskArguments 2>&1 | ForEach-Object { "$_" } |
    Out-File -FilePath $taskLog -Append -Encoding utf8
$taskExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
exit $taskExitCode
