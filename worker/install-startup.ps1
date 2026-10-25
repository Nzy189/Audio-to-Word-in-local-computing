param([string]$PythonExe = 'F:\Claude Code Project\DeepTutor\FunASR\.venv\Scripts\pythonw.exe')
$ErrorActionPreference = 'Stop'
$workerDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'FunASR pythonw.exe was not found. Supply -PythonExe.' }
$workerShell = New-Object -ComObject WScript.Shell
$workerShortcut = $workerShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Shengjian GPU Worker.lnk'))
$workerShortcut.TargetPath = $PythonExe
$workerShortcut.Arguments = '"' + (Join-Path $workerDirectory 'server.py') + '" --config "' + (Join-Path $workerDirectory 'worker.env') + '"'
$workerShortcut.WorkingDirectory = $workerDirectory
$workerShortcut.WindowStyle = 7
$workerShortcut.Description = 'FunASR GPU transcription worker for the NAS, over the local network'
$workerShortcut.Save()
Write-Output 'Installed a shortcut for this user. The GPU worker starts after Windows sign-in.'
