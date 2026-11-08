@echo off
REM Inicia a API (porta 8000) e o site (porta 5173) e abre o navegador.
cd /d "%~dp0backend"
start "Wealth Balancer API" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd /d "%~dp0frontend"
if not exist node_modules call npm install
start "Wealth Balancer Web" cmd /k npx vite --host localhost --port 5173 --strictPort
timeout /t 4 >nul
start "" http://localhost:5173
