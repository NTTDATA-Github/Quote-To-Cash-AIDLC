# Windows entry point for local.sh. Finds the real Git Bash regardless of where it's
# installed, so plain `bash` on PATH resolving to the WSL launcher stub (System32\bash.exe)
# instead of Git Bash never bites a developer - see local.sh's own WSL guard for what that
# looks like if it still happens.
$candidates = @()

foreach ($hive in 'HKCU:\SOFTWARE\GitForWindows', 'HKLM:\SOFTWARE\GitForWindows', 'HKLM:\SOFTWARE\WOW6432Node\GitForWindows') {
    try {
        $installPath = (Get-ItemProperty -Path $hive -Name InstallPath -ErrorAction Stop).InstallPath
        if ($installPath) { $candidates += (Join-Path $installPath 'bin\bash.exe') }
    } catch {}
}

$gitCmd = Get-Command git.exe -ErrorAction SilentlyContinue
if ($gitCmd) {
    $gitBinDir = Split-Path $gitCmd.Source -Parent   # ...\Git\cmd or ...\Git\bin
    $gitRoot = Split-Path $gitBinDir -Parent          # ...\Git
    $candidates += (Join-Path $gitBinDir 'bash.exe')
    $candidates += (Join-Path $gitRoot 'bin\bash.exe')
}

$candidates += @(
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
    "$env:LocalAppData\Programs\Git\bin\bash.exe"
)

$bash = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $bash) {
    Write-Error "Git Bash not found. Install Git for Windows: https://git-scm.com/download/win"
    exit 1
}

& $bash (Join-Path $PSScriptRoot 'local.sh') @args
exit $LASTEXITCODE
