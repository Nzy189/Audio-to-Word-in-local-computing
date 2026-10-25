param([string]$PythonExe = 'F:\Claude Code Project\DeepTutor\FunASR\.venv\Scripts\python.exe')
$ErrorActionPreference = 'Stop'
$workerDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'FunASR Python was not found. Supply -PythonExe with your existing environment.' }
$workerConfig = Join-Path $workerDirectory 'worker.env'
$workerScript = Join-Path $workerDirectory 'server.py'
$workerData = Join-Path $env:LOCALAPPDATA 'ShengjianWorker'
New-Item -ItemType Directory -Force -Path $workerData | Out-Null
$existingListener = Get-NetTCPConnection -LocalPort 18788 -State Listen -ErrorAction SilentlyContinue
if ($existingListener) { Write-Output 'Port 18788 is already listening. No duplicate worker was started.'; exit 0 }
$workerArgs = '"' + $workerScript + '" --config "' + $workerConfig + '"'
$workerProcess = Start-Process -FilePath $PythonExe -ArgumentList $workerArgs -WorkingDirectory $workerDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $workerData 'console.log') -RedirectStandardError (Join-Path $workerData 'console-error.log')
Write-Output ('Worker launched, PID ' + $workerProcess.Id + '. Logs: ' + $workerData)
