param(
  [switch]$KeepPython
)

$ErrorActionPreference = "Stop"

Write-Host "Removing Codex Account Manager bootstrap prerequisites for installation testing..."

$homeDir = $env:USERPROFILE
$targets = @(
  "$homeDir\.local\bin\codex-account.exe",
  "$homeDir\.local\bin\codex-account",
  "$homeDir\pipx\venvs\codex-account-manager",
  "$homeDir\pipx\shared",
  "$homeDir\pipx\logs",
  "$homeDir\.local\pipx\venvs\codex-account-manager",
  "$homeDir\.local\pipx\shared",
  "$homeDir\.local\pipx\logs",
  "$homeDir\.codex\ui-service\service.json",
  "$homeDir\.codex\account-manager\runtime-state.json",
  "$homeDir\AppData\Roaming\Codex Account Manager\runtime-state.json",
  "$homeDir\AppData\Local\Codex Account Manager\runtime-state.json"
)

function Remove-IfPresent {
  param([string]$PathValue)
  if (Test-Path -LiteralPath $PathValue) {
    Remove-Item -LiteralPath $PathValue -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Removed: $PathValue"
  } else {
    Write-Host "Not present: $PathValue"
  }
}

function Run-IfPresent {
  param(
    [string]$Command,
    [string[]]$Args
  )
  if (Get-Command $Command -ErrorAction SilentlyContinue) {
    try {
      & $Command @Args | Out-Null
      Write-Host "Ran: $Command $($Args -join ' ')"
    } catch {
      Write-Host "Command failed (ignored): $Command $($Args -join ' ')"
    }
  } else {
    Write-Host "Command not found, skipped: $Command"
  }
}

Run-IfPresent "$homeDir\.local\bin\codex-account.exe" @("ui-service", "stop")
Run-IfPresent "codex-account" @("ui-service", "stop")
Run-IfPresent "pipx" @("uninstall", "codex-account-manager")
Run-IfPresent "py" @("-m", "pip", "uninstall", "-y", "codex-account-manager")
Run-IfPresent "python" @("-m", "pip", "uninstall", "-y", "codex-account-manager")

foreach ($target in $targets) {
  Remove-IfPresent -PathValue $target
}

if (-not $KeepPython) {
  $pythonPkg = Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "Python 3.11* (64-bit)" } |
    Select-Object -First 1

  if ($pythonPkg -and $pythonPkg.QuietUninstallString) {
    $quiet = [string]$pythonPkg.QuietUninstallString
    $exe = if ($quiet -match '"([^"]+)"') { $Matches[1] } else { ($quiet -split " ")[0] }
    if (Test-Path -LiteralPath $exe) {
      Start-Process -FilePath $exe -ArgumentList "/uninstall", "/quiet" -Wait
      Write-Host "Removed: $($pythonPkg.DisplayName)"
    } else {
      Write-Host "Python uninstaller not found: $exe"
    }
  } else {
    Write-Host "Python 3.11 uninstall entry not present."
  }
} else {
  Write-Host "Kept Python runtime (--KeepPython)."
}

Write-Host ""
Write-Host "Kept intentionally:"
Write-Host "  $homeDir\.codex\account-profiles"
Write-Host "  $homeDir\.codex\profile-homes"
Write-Host "  exported .camzip archives"
Write-Host ""
Write-Host "Cleanup complete."
