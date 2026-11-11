# Genera dist\ArkivX.exe (un solo archivo, sin consola).
#
# Uso, desde la raíz del repositorio:
#   powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1 -ConPapelera
#
# Usa un entorno virtual limpio en build\venv para que el .exe no arrastre
# paquetes del Python global (Anaconda, etc.). Corre las pruebas antes de
# compilar y se detiene si alguna falla.
#
# -ConPapelera incluye send2trash: los duplicados eliminados van a la
# Papelera de Windows, pero Deshacer ya NO puede restaurarlos. Sin esa
# opción van a la cuarentena (~/.arkivx/cuarentena) y Deshacer sí funciona.
param(
    [switch]$ConPapelera,
    [string]$Python = "python"
)
# "Continue": en Windows PowerShell 5.1, con "Stop" cualquier aviso que un
# programa externo (pip) escriba en stderr detiene el script. Los fallos
# reales se detectan con $LASTEXITCODE después de cada comando.
$ErrorActionPreference = "Continue"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$build = Join-Path $raiz "build"
$venv = Join-Path $build "venv"
$py = Join-Path $venv "Scripts\python.exe"

Write-Host "== Pruebas"
& $Python -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron: no se genera el .exe." }

if (-not (Test-Path $py)) {
    Write-Host "== Creando entorno virtual en build\venv"
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el entorno virtual." }
}

Write-Host "== Instalando PyInstaller"
$paquetes = @("pyinstaller")
if ($ConPapelera) { $paquetes += "send2trash>=1.8" }
& $py -m pip install --quiet --disable-pip-version-check @paquetes
if ($LASTEXITCODE -ne 0) { throw "No se pudo instalar PyInstaller." }
if (-not $ConPapelera) {
    # Un venv reutilizado podría tenerlo de una corrida anterior.
    & $py -m pip show --quiet send2trash *> $null
    if ($LASTEXITCODE -eq 0) {
        & $py -m pip uninstall --quiet --yes send2trash
    }
}

Write-Host "== Compilando"
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name ArkivX `
    --paths $raiz `
    --distpath (Join-Path $raiz "dist") `
    --workpath (Join-Path $build "work") `
    --specpath $build `
    (Join-Path $PSScriptRoot "ArkivX.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló." }

$exe = Join-Path $raiz "dist\ArkivX.exe"
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "== Listo: $exe ($mb MB)"
