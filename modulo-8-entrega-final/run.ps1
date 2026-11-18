# Levanta TODO el sistema sin Docker (Windows). Una sola instrucción:   .\run.ps1
#
#   1. crea el entorno virtual e instala las dependencias (solo la primera vez)
#   2. Redis: usa el que ya esté en REDIS_URL; si no hay, levanta uno (docker, o el servidor de desarrollo fakeredis)
#   3. sube la base de conocimiento a Pinecone (idempotente)
#   4. Phoenix (si instalaste requirements-phoenix.txt en .venv-phoenix o hay Docker) y la API
#
# Requiere un .env con las keys (copiá .env.example). Con Docker, alcanza con:  docker compose up --build
param([switch]$SinPhoenix, [int]$Puerto = 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Paso($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Puerto-Abierto($p) { (Test-NetConnection -ComputerName localhost -Port $p -WarningAction SilentlyContinue -InformationLevel Quiet) }

if (-not (Test-Path .env)) { throw "Falta el archivo .env: copiá .env.example a .env y completá las keys." }

Paso "Entorno virtual y dependencias"
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
$ErrorActionPreference = "Continue"   # Windows PowerShell 5.1 trata como error lo que pip escribe en stderr
& $py -m pip install -q --disable-pip-version-check -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install falló" }
$ErrorActionPreference = "Stop"

Paso "Redis (estado de los reclamos, cola y checkpoints)"
if (Puerto-Abierto 6379) { Write-Host "Ya hay un Redis en el puerto 6379: se usa ese." }
elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    docker run -d --name mesa-reclamos-redis -p 6379:6379 redis:7-alpine redis-server --appendonly yes | Out-Null
    Write-Host "Redis (docker) iniciado."
} else {
    Start-Process $py -ArgumentList "dev/redis_local.py" -WindowStyle Hidden
    Write-Host "Sin Docker: Redis de DESARROLLO (fakeredis) iniciado. No persiste a disco; no es para producción."
}
for ($i = 0; $i -lt 20 -and -not (Puerto-Abierto 6379); $i++) { Start-Sleep -Milliseconds 500 }

Paso "Base de conocimiento en Pinecone"
if ((Select-String -Path .env -Pattern '^RAG_BACKEND=local' -Quiet)) { Write-Host "RAG_BACKEND=local: se omite Pinecone." }
else { & $py scripts/ingestar.py }

Paso "Phoenix (trazas)"
$env:PHOENIX_COLLECTOR_ENDPOINT = ""
if ($SinPhoenix) { Write-Host "Omitido (-SinPhoenix): no se envían trazas." }
elseif (Puerto-Abierto 6006) { Write-Host "Phoenix ya está en http://localhost:6006"; $env:PHOENIX_COLLECTOR_ENDPOINT = "http://localhost:6006" }
elseif (Test-Path .venv-phoenix\Scripts\python.exe) {
    $env:PHOENIX_WORKING_DIR = "$PSScriptRoot\.phoenix"
    Start-Process .\.venv-phoenix\Scripts\python.exe -ArgumentList "-m phoenix.server.main serve" -WindowStyle Hidden
    $env:PHOENIX_COLLECTOR_ENDPOINT = "http://localhost:6006"
    Write-Host "Phoenix iniciado en http://localhost:6006"
} else {
    Write-Host "Phoenix no está instalado: python -m venv .venv-phoenix; .venv-phoenix\Scripts\pip install -r requirements-phoenix.txt" -ForegroundColor Yellow
    Write-Host "La API arranca igual, pero sin enviar trazas."
}

Paso "API en http://localhost:$Puerto/docs"
& $py -m uvicorn app.main:app --host 0.0.0.0 --port $Puerto
