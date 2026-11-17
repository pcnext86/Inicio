@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (where python >nul 2>nul && (set PY=python) || (echo Python nao encontrado. Instala em python.org e marca "Add to PATH". & pause & exit /b))
start "" http://localhost:4890
%PY% server.py
pause
