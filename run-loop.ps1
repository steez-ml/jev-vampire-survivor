Set-Location $PSScriptRoot\bridge
Write-Host "Starting the VampireJev loop. Keep this window open while you play."
Write-Host "Click Vampire Survivors, then tap Ctrl once to arm. Tap Ctrl again to disarm."
Write-Host "If this opened as text in Cursor, close it and run .\run-loop.bat from the repo root instead."
python -m vampirejev @args
