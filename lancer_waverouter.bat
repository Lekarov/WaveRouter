@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   WaveRouter - Lancement
echo ============================================

REM --- Verification de Python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Installez Python 3.11+ depuis https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Creation de l'environnement virtuel si absent ---
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Environnement virtuel introuvable, creation en cours...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer l'environnement virtuel.
        pause
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

REM --- Marqueur pour eviter de reinstaller a chaque lancement ---
set "MARKER=.venv\.deps_installed"

for %%F in (requirements.txt) do set "REQ_TIME=%%~tF"

if not exist "%MARKER%" (
    set NEED_INSTALL=1
) else (
    REM Reinstalle si requirements.txt est plus recent que le marqueur
    for %%F in ("%MARKER%") do set "MARKER_TIME=%%~tF"
    if "!REQ_TIME!" GTR "!MARKER_TIME!" set NEED_INSTALL=1
)

if defined NEED_INSTALL (
    echo [INFO] Installation/mise a jour des dependances...
    "%VENV_PY%" -m pip install --upgrade pip >nul
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERREUR] Echec de l'installation des dependances.
        pause
        exit /b 1
    )
    echo installed> "%MARKER%"
) else (
    echo [INFO] Dependances deja installees, verification rapide...
    "%VENV_PY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check
)

echo [INFO] Demarrage de WaveRouter...
"%VENV_PY%" main.py %*

if errorlevel 1 (
    echo.
    echo [ERREUR] WaveRouter s'est ferme avec une erreur.
    pause
)

endlocal
