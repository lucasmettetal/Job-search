@echo off
:: ============================================================
::  JobBot — Lancement de l'interface web (Windows)
::  Double-clic sur ce fichier pour ouvrir le dashboard.
:: ============================================================

title JobBot Dashboard
cd /d "%~dp0"

echo.
echo  =============================================
echo   JobBot - Lancement de l'interface locale
echo  =============================================
echo.

:: ---- Vérification de Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Installe Python depuis https://python.org
    pause
    exit /b 1
)

:: ---- Environnement virtuel ----
if exist ".venv\Scripts\python.exe" (
    echo  Activation de l'environnement virtuel...
    call .venv\Scripts\activate.bat
) else (
    echo  Aucun environnement virtuel trouve - utilisation du Python systeme
)

:: ---- Installation des dependances ----
echo  Verification des dependances...
pip install -r requirements.txt --quiet --no-warn-script-location
if errorlevel 1 (
    echo [ERREUR] Impossible d'installer les dependances.
    pause
    exit /b 1
)

:: ---- Création du dossier .streamlit ----
if not exist ".streamlit" mkdir ".streamlit"

:: Désactiver la surveillance des fichiers pour éviter les redémarrages
:: quand app.py écrit dans config.yaml ou .env
if not exist ".streamlit\config.toml" (
    echo [server]> .streamlit\config.toml
    echo fileWatcherType = "none">> .streamlit\config.toml
    echo headless = false>> .streamlit\config.toml
)

:: ---- Lancement ----
echo.
echo  Ouverture dans le navigateur...
echo  Pour arreter : ferme cette fenetre ou appuie sur Ctrl+C
echo.

streamlit run app.py --server.port 8501 --server.headless false

pause
