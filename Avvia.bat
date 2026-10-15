@echo off
setlocal
cd /d "%~dp0"
title Traduzione sottotitoli

if not exist "runtime\.ready" (
    echo Prima configurazione: scarico Python, ffmpeg e le librerie necessarie...
    echo Serve internet e qualche GB di spazio. Operazione da fare una sola volta.
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    if errorlevel 1 (
        echo.
        echo Configurazione fallita. Controlla il messaggio sopra e riprova.
        pause
        exit /b 1
    )
)

start "" "%~dp0runtime\python\pythonw.exe" "%~dp0app.py"
endlocal
