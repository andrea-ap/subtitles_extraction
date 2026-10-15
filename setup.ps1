# Configurazione portatile: scarica Python (con Tkinter), ffmpeg e le librerie in .\runtime\
# Nota: file volutamente solo ASCII (PowerShell 5.1 legge male l'UTF-8 senza BOM).
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$rt   = Join-Path $root "runtime"
$py   = Join-Path $rt "python"
$tmp  = Join-Path $rt "tmp"
$pye  = Join-Path $py "python.exe"
New-Item -ItemType Directory -Force $rt, $tmp | Out-Null

function Step($n, $text) { Write-Host ""; Write-Host "[$n/4] $text" -ForegroundColor Cyan }
function Download($url, $dest) {
    Write-Host "  scarico: $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

try {
    # 1) Python ufficiale estratto dagli MSI (nessuna installazione, nessun registro; include Tkinter)
    Step 1 "Python con Tkinter"
    if (-not (Test-Path (Join-Path $py "DLLs\_tkinter.pyd"))) {
        if (Test-Path $py) { Remove-Item $py -Recurse -Force }
        $ext = Join-Path $tmp "py311"
        if (Test-Path $ext) { Remove-Item $ext -Recurse -Force }
        foreach ($n in "core", "exe", "lib", "tcltk") {
            $msi = Join-Path $tmp "$n.msi"
            Download "https://www.python.org/ftp/python/3.11.9/amd64/$n.msi" $msi
            $p = Start-Process msiexec -Wait -PassThru -ArgumentList "/a", "`"$msi`"", "/qn", "TARGETDIR=`"$ext`""
            if ($p.ExitCode -ne 0) { throw "estrazione $n.msi fallita (codice $($p.ExitCode))" }
        }
        Get-ChildItem $ext -Filter *.msi | Remove-Item -Force
        Move-Item $ext $py
    } else { Write-Host "  gia presente" }

    # 2) ffmpeg
    Step 2 "ffmpeg"
    $ffdir = Join-Path $rt "ffmpeg"
    if (-not (Test-Path (Join-Path $ffdir "ffmpeg.exe"))) {
        $zip = Join-Path $tmp "ffmpeg.zip"
        $ext = Join-Path $tmp "ff"
        if (Test-Path $ext) { Remove-Item $ext -Recurse -Force }
        Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
        Write-Host "  estraggo..."
        Expand-Archive $zip $ext -Force
        New-Item -ItemType Directory -Force $ffdir | Out-Null
        foreach ($n in "ffmpeg.exe", "ffprobe.exe") {
            $f = Get-ChildItem $ext -Recurse -Filter $n | Select-Object -First 1
            Copy-Item $f.FullName $ffdir
        }
    } else { Write-Host "  gia presente" }

    # 3) pip + librerie (CUDA via pip: nessun toolkit di sistema richiesto)
    Step 3 "Librerie Python (faster-whisper, CUDA, traduttore) - puo richiedere diversi minuti"
    $ErrorActionPreference = "Continue"
    & $pye -m pip --version *> $null
    $havePip = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = "Stop"
    if (-not $havePip) {
        & $pye -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            $gp = Join-Path $tmp "get-pip.py"
            Download "https://bootstrap.pypa.io/get-pip.py" $gp
            & $pye $gp
            if ($LASTEXITCODE -ne 0) { throw "pip non installabile" }
        }
    }
    & $pye -m pip install --no-warn-script-location faster-whisper srt argostranslate nvidia-cublas-cu12 nvidia-cudnn-cu12
    if ($LASTEXITCODE -ne 0) { throw "installazione librerie fallita" }

    # 4) verifica
    Step 4 "Verifica"
    & $pye -c "import tkinter, faster_whisper, srt, argostranslate; print('  moduli OK')"
    if ($LASTEXITCODE -ne 0) { throw "verifica moduli fallita" }
    & (Join-Path $ffdir "ffmpeg.exe") -version | Select-Object -First 1

    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Set-Content -Path (Join-Path $rt ".ready") -Value "ok"
    Write-Host ""
    Write-Host "Configurazione completata." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host ("ERRORE: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
