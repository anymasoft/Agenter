# install-cuda-torch.ps1 - install CUDA-enabled PyTorch into Agenter venv.
# Must close Agenter UI before running.
#
# Usage:
#   .\install-cuda-torch.ps1               # auto-detect CUDA version
#   .\install-cuda-torch.ps1 cu121         # force specific CUDA wheel
#   .\install-cuda-torch.ps1 -Revert       # revert to CPU torch

param(
    [string]$CudaVer = "auto",
    [switch]$Revert
)

$ErrorActionPreference = "Stop"
$python = "C:\BUFFER\ERP\agenter\backend\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Python venv not found: $python" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Current PyTorch ===" -ForegroundColor Cyan
& $python -c "import torch; print('torch =', torch.__version__); print('cuda  =', torch.cuda.is_available())"

if ($Revert) {
    Write-Host ""
    Write-Host "=== Revert to CPU torch ===" -ForegroundColor Yellow
    & $python -m pip uninstall -y torch
    & $python -m pip install torch
    Write-Host ""
    & $python -c "import torch; print('done -> torch', torch.__version__, 'cuda', torch.cuda.is_available())"
    exit 0
}

# Auto-detect CUDA version from nvidia-smi
if ($CudaVer -eq "auto") {
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) {
        Write-Host "nvidia-smi not found. Pass version explicitly: cu118/cu121/cu124/cu126" -ForegroundColor Red
        exit 1
    }
    $smiOut = & nvidia-smi
    $cudaLine = $smiOut | Select-String "CUDA Version:" | Select-Object -First 1
    if ($cudaLine -match "CUDA Version:\s+(\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if     ($major -ge 12 -and $minor -ge 6) { $CudaVer = "cu126" }
        elseif ($major -ge 12 -and $minor -ge 4) { $CudaVer = "cu124" }
        elseif ($major -ge 12 -and $minor -ge 1) { $CudaVer = "cu121" }
        elseif ($major -ge 11 -and $minor -ge 8) { $CudaVer = "cu118" }
        else {
            Write-Host "Driver CUDA $major.$minor is too old. Update driver." -ForegroundColor Red
            exit 1
        }
        Write-Host ""
        Write-Host "Detected driver CUDA $major.$minor -> using $CudaVer" -ForegroundColor Green
    } else {
        Write-Host "Failed to parse CUDA version from nvidia-smi" -ForegroundColor Red
        exit 1
    }
}

$indexUrl = "https://download.pytorch.org/whl/$CudaVer"

Write-Host ""
Write-Host "=== Install torch+$CudaVer (about 2.5 GB) ===" -ForegroundColor Cyan
Write-Host "Index: $indexUrl"
Write-Host ""

Write-Host "Step 1: uninstall current torch..." -ForegroundColor Yellow
& $python -m pip uninstall -y torch
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: uninstall returned $LASTEXITCODE - continuing" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Step 2: download torch+$CudaVer..." -ForegroundColor Yellow
& $python -m pip install torch --index-url $indexUrl
if ($LASTEXITCODE -ne 0) {
    Write-Host "Install FAILED. Try: .\install-cuda-torch.ps1 cu121" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
& $python -c "import torch; print('torch =', torch.__version__); print('cuda  =', torch.cuda.is_available()); print('gpu   =', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')"

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Green
Write-Host "  1. Start Agenter: python main.py" -ForegroundColor White
Write-Host "  2. Delete data\platform_docs_chroma\ (incomplete CPU index)" -ForegroundColor White
Write-Host "  3. Click 'Build semantic index' in UI - should take ~5 min on GPU" -ForegroundColor White
Write-Host ""
Write-Host "Revert at any time: .\install-cuda-torch.ps1 -Revert" -ForegroundColor DarkGray
