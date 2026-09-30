@echo off
rem Starts the application queue dashboard and opens it in the browser.
rem Runs preflight first: every check is something that once broke a live run.
rem Add "--no-submit" after app.py for a test run that stops before the applier.
cd /d "%~dp0"
python preflight.py
if errorlevel 1 (
  echo.
  echo Preflight found a problem. Fix it before sending jobs, or press a key to start anyway.
  pause
)
cd /d "%~dp0dashboard"
start "" http://127.0.0.1:5057
python app.py
