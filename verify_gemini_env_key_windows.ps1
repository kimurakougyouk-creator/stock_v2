#requires -Version 5.1
# Run this after pasting the real GEMINI_API_KEY into .env with a text
# editor (never into chat). It never prints the key itself -- only
# whether settings loaded a non-empty key, and (if -LiveCheck is passed)
# whether Gemini actually accepted it. -LiveCheck makes one real network
# call to Google's Gemini generateContent endpoint -- no trading action
# and no broker involved, but it is a genuine external API call, not a
# cost-free local check, and is never made unless -LiveCheck is passed
# explicitly.
param(
    [switch]$LiveCheck
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoDir = if ($env:IBKR_REPO_DIR) {
    [System.IO.Path]::GetFullPath($env:IBKR_REPO_DIR)
} else {
    Join-Path $HOME "stock_v2_latest"
}
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
$EnvFile = Join-Path $RepoDir ".env"

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "BLOCKED: .env not found at $EnvFile"
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found."
}

$script = @'
import sys
sys.path.insert(0, "src")
from ai_asset_platform.ai.settings import load_ai_settings

settings = load_ai_settings()
print("provider:", settings.provider)
print("gemini_model:", settings.gemini_model)
print("has_gemini_key:", bool(settings.gemini_api_key))
print("key_length:", len(settings.gemini_api_key))

if "--live-check" in sys.argv and settings.gemini_api_key:
    from ai_asset_platform.ai.gemini_client import GeminiClient

    client = GeminiClient(api_key=settings.gemini_api_key)
    try:
        result = client.request(
            model=settings.gemini_model,
            system_prompt="You are a connectivity check. Reply with exactly the JSON requested.",
            payload={"prompt": 'Return exactly this JSON object and nothing else: {"ok": true}'},
        )
        print("live_check: REACHED_GEMINI")
        print("live_check_result_ok:", bool(result.get("ok") is True))
    except Exception as exc:
        print("live_check: FAILED -", type(exc).__name__, "-", str(exc)[:200])
'@

# Allocate the temp script with FileMode.CreateNew under a fresh random
# name rather than a fixed name written with unconditional -Force /
# WriteAllText. An earlier revision used a fixed name
# ("_verify_gemini_env_key_tmp.py") and unconditionally overwrote, then
# unconditionally deleted, whatever file already sat at that exact path
# -- destroying any unrelated file someone happened to have there.
# CreateNew throws instead of succeeding if anything already exists at
# the chosen name, so this script can only ever write to, and later
# delete, a file it is certain it just created itself.
$tempScript = $null
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    $candidate = Join-Path $RepoDir (".verify-gemini-" + [System.IO.Path]::GetRandomFileName() + ".py")
    try {
        $fs = [System.IO.File]::Open($candidate, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
        $fs.Close()
        $tempScript = $candidate
        break
    } catch [System.IO.IOException] {
        continue
    }
}
if (-not $tempScript) {
    throw "BLOCKED: could not allocate a unique temporary script file in $RepoDir"
}
[System.IO.File]::WriteAllText($tempScript, $script, (New-Object System.Text.UTF8Encoding($false)))
try {
    Push-Location $RepoDir
    if ($LiveCheck) {
        & $PythonExe $tempScript --live-check
    } else {
        & $PythonExe $tempScript
    }
} finally {
    Pop-Location
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}
