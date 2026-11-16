param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildBat = Join-Path $PSScriptRoot 'Build-Exe.bat'
$botExe = Join-Path $PSScriptRoot 'DungeonBot.exe'
$restartLog = Join-Path $PSScriptRoot 'rebuild-restart.log'
$restartStatus = Join-Path $PSScriptRoot 'rebuild-restart-status.json'
$gate = [System.Threading.Mutex]::new($false, 'Local\DungeonBotRebuildRestart')
$ownsGate = $false
function Status($stage, $detail) {
    @{ at = (Get-Date).ToString('o'); stage = $stage; detail = $detail } |
        ConvertTo-Json | Set-Content -LiteralPath $restartStatus -Encoding UTF8
    Add-Content -LiteralPath $restartLog -Value "$(Get-Date -Format o) $stage $detail"
}
try {
    $ownsGate = $gate.WaitOne(0)
    if (-not $ownsGate) { exit 0 }
    if (-not (Test-Path -LiteralPath $buildBat)) { throw 'Build-Exe.bat missing' }
    if ($CheckOnly) {
        Write-Output "Build: $buildBat"
        Write-Output "Launch: $botExe"
        exit 0
    }
    Status 'stopping' 'Stopping DungeonBot EXE processes'
    # Includes the PyInstaller parent and child, plus older named bot builds.
    $bots = @(Get-Process -Name 'DungeonBot*' -ErrorAction SilentlyContinue)
    foreach ($bot in $bots) {
        try {
            if (-not $bot.HasExited) { Stop-Process -InputObject $bot -Force -ErrorAction Stop }
        } catch {
            if (-not $bot.HasExited) { throw }
        }
    }
    foreach ($bot in $bots) {
        $bot.WaitForExit(10000) | Out-Null
        if (-not $bot.HasExited) { throw "Bot process $($bot.Id) did not exit" }
    }
    Status 'building' 'Running Build-Exe.bat; output follows'
    & $env:ComSpec /d /c 'call Build-Exe.bat --no-pause' >> $restartLog 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $botExe)) { throw 'Build did not produce DungeonBot.exe' }
    Status 'checking' 'Checking bundled templates, OCR and capture imports'
    $smoke = Start-Process -FilePath $botExe -ArgumentList '--build-smoke-test' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -Wait
    if ($smoke.ExitCode -ne 0) { throw "EXE smoke check failed: $($smoke.ExitCode)" }
    $result = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'exe-smoke-result.json') -Raw | ConvertFrom-Json
    if (-not $result.ok) { throw 'EXE smoke check did not report success' }
    $newBot = Start-Process -FilePath $botExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    Status 'started' "DungeonBot.exe launched; PID $($newBot.Id)"
} catch {
    Status 'failed' $_.Exception.Message
    exit 1
} finally {
    if ($ownsGate) { $gate.ReleaseMutex() }
    $gate.Dispose()
}
