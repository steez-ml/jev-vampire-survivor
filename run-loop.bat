@echo off
setlocal
cd /d "%~dp0bridge"
echo Starting the VampireJev loop. Keep this window open while you play.
echo Click Vampire Survivors, then tap Ctrl once to arm. Tap Ctrl again to disarm.
python -m vampirejev %*
if errorlevel 1 (
  echo.
  echo python -m vampirejev failed. Is Python on PATH?
  pause
)
endlocal
