# TaskFlow AI 一键启动：Ollama 服务 + 后端 API
# 用法：powershell -ExecutionPolicy Bypass -File start.ps1
# 便携包内运行时自动使用 .\python\python.exe（无需预装 Python）

$ErrorActionPreference = "Stop"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OllamaExe = "C:\Users\admin\AppData\Local\Programs\Ollama\ollama.exe"

# 找可用的 Python：便携包内置 > 本地 venv > 系统 python
$PyCandidates = @(
    (Join-Path $BackendDir "python\python.exe"),
    (Join-Path $BackendDir ".venv\Scripts\python.exe")
)
$Python = $PyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) { $Python = "python" }

# 1. 启动 Ollama 服务（若未运行且已安装）
$ollamaUp = $false
try { Invoke-WebRequest -Uri "http://localhost:11434/api/version" -UseBasicParsing -TimeoutSec 2 | Out-Null; $ollamaUp = $true } catch {}
if (-not $ollamaUp) {
    # 常见安装位置探测
    $ollamaCandidates = @($OllamaExe, "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")
    $ollamaFound = $ollamaCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($ollamaFound) {
        Write-Host "[1/3] 启动 Ollama 服务..." -ForegroundColor Cyan
        $env:OLLAMA_MODELS = "$env:LOCALAPPDATA\Programs\Ollama\models"
        Start-Process -FilePath $ollamaFound -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 4
    } else {
        Write-Host "[1/3] 未检测到 Ollama（可继续运行，LLM 走 mock/云 API 通道）" -ForegroundColor Yellow
        # 无 Ollama 时回退 mock 通道，保证开箱可用
        if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "mock" }
    }
} else {
    Write-Host "[1/3] Ollama 已在运行" -ForegroundColor Green
    if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
}

# 2. 启动后端（若 8600 端口未占用）
$apiUp = $false
try { Invoke-WebRequest -Uri "http://localhost:8600/api/llm-info" -UseBasicParsing -TimeoutSec 2 | Out-Null; $apiUp = $true } catch {}
if (-not $apiUp) {
    Write-Host "[2/3] 启动 TaskFlow 后端（$($env:LLM_PROVIDER) 通道）..." -ForegroundColor Cyan
    Push-Location $BackendDir
    if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "qwen3:4b" }
    $env:PYTHONPYCACHEPREFIX = ".\.pycache"
    Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","app.main:app","--port","8600" -WindowStyle Hidden
    Pop-Location
    Start-Sleep -Seconds 5
} else {
    Write-Host "[2/3] 后端已在运行" -ForegroundColor Green
}

# 3. 完成
Write-Host "[3/3] 就绪！打开 http://localhost:8600 开始使用" -ForegroundColor Green
Write-Host "      管理员: admin / admin123   员工: 张工 / 123456"
Start-Process "http://localhost:8600"
