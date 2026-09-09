@echo off
rem Lance le moteur AI QA Agent. Double-cliquable depuis l'explorateur.
rem
rem Le repertoire de travail est deduit de l'emplacement de ce fichier (%~dp0), pas du
rem repertoire courant : double-cliquer dans l'explorateur et lancer depuis un terminal
rem ouvert ailleurs doivent donner le meme resultat.

setlocal
chcp 65001 >nul 2>&1
title Moteur AI QA Agent

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "PYTHON=%BACKEND%\.venv\Scripts\python.exe"
set "PORT=8000"

if not exist "%PYTHON%" (
    echo.
    echo   Environnement Python introuvable :
    echo     %PYTHON%
    echo.
    echo   Pour le creer :
    echo     python -m venv "%BACKEND%\.venv"
    echo     "%BACKEND%\.venv\Scripts\pip" install -e "%BACKEND%"
    echo.
    pause
    exit /b 1
)

rem Un port deja pris signifie presque toujours un moteur deja lance. Le dire evite de
rem chercher pourquoi le second refuse de demarrer.
netstat -ano -p tcp 2>nul | findstr /c:":%PORT% " | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo   Le port %PORT% est deja utilise : le moteur tourne probablement deja.
    echo   Verifiez sur http://127.0.0.1:%PORT%/health
    echo.
    echo   Pour arreter celui qui tourne, trouvez son PID avec :
    echo     netstat -ano ^| findstr :%PORT%
    echo.
    pause
    exit /b 1
)

cd /d "%BACKEND%"

echo.
echo   Moteur AI QA Agent
echo   ------------------
echo   API           http://127.0.0.1:%PORT%/api/v1
echo   Documentation http://127.0.0.1:%PORT%/docs
echo   Interface     http://localhost:8080
echo.
echo   Ctrl+C pour arreter.
echo.

"%PYTHON%" -m uvicorn qa_engine.main:app --host 127.0.0.1 --port %PORT%
set "CODE=%ERRORLEVEL%"

rem Sans cette pause, une erreur au demarrage fermerait la fenetre avant qu'on la lise.
if not "%CODE%"=="0" (
    echo.
    echo   Le moteur s'est arrete avec le code %CODE%.
    pause
)

endlocal
