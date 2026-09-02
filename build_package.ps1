# 打包脚本：生成 TaskFlow AI 免安装分发包（dist/TaskFlowAI-便携版.zip）
# 内嵌 Python 3.12 便携版 + 依赖 + 应用代码 + SQLite 数据库
# 目标机器：Windows 10/11 x64，无需安装 Python/Docker
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = Join-Path $Root "dist"
$Pkg = Join-Path $Dist "TaskFlowAI"

Write-Host "[1/5] 清理旧产物..." -ForegroundColor Cyan
if (Test-Path $Pkg) { Remove-Item $Pkg -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Pkg | Out-Null

Write-Host "[2/5] 复制应用代码..." -ForegroundColor Cyan
Copy-Item (Join-Path $Root "backend\app") (Join-Path $Pkg "app") -Recurse
Copy-Item (Join-Path $Root "backend\static") (Join-Path $Pkg "static") -Recurse
Copy-Item (Join-Path $Root "backend\requirements.txt") $Pkg
Copy-Item (Join-Path $Root "README.md") $Pkg
# 带上已跑通的演示数据库（含演示员工/管理员/项目数据）
if (Test-Path (Join-Path $Root "backend\taskflow.db")) {
    Copy-Item (Join-Path $Root "backend\taskflow.db") $Pkg
}

Write-Host "[3/5] 获取嵌入式 Python（python embeddable zip）..." -ForegroundColor Cyan
$PyUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
$PyZip = Join-Path $env:TEMP "python-embed.zip"
$ProgressPreference = 'SilentlyContinue'
if (-not (Test-Path $PyZip)) {
    # python.org 国内一般可达；失败时提示手动下载
    try {
        Invoke-WebRequest -Uri $PyUrl -OutFile $PyZip -UseBasicParsing -TimeoutSec 600
    } catch {
        Write-Host "  下载失败，请手动下载 $PyUrl 解压到 $Pkg\python 后重跑" -ForegroundColor Yellow
        throw
    }
}
$PyDir = Join-Path $Pkg "python"
Expand-Archive -Path $PyZip -DestinationPath $PyDir -Force

# 启用 pip（解开 ._pth 限制）
$Pth = Join-Path $PyDir "python312._pth"
(Get-Content $Pth) -replace "^#import site", "import site" | Set-Content $Pth
# 下载 pip（get-pip.py）
$GetPip = Join-Path $env:TEMP "get-pip.py"
if (-not (Test-Path $GetPip)) {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing
}
& (Join-Path $PyDir "python.exe") $GetPip --no-warn-script-location --quiet

Write-Host "[4/5] 安装依赖到包内 site-packages..." -ForegroundColor Cyan
& (Join-Path $PyDir "python.exe") -m pip install -r (Join-Path $Pkg "requirements.txt") --no-warn-script-location --quiet --disable-pip-version-check

Write-Host "[5/5] 生成启动脚本..." -ForegroundColor Cyan
Copy-Item (Join-Path $Root "backend\start.ps1") $Pkg

$Bat = Join-Path $Pkg "启动.bat"
@"
@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
"@ | Out-File $Bat -Encoding utf8

# 压缩
Write-Host "压缩为 zip..." -ForegroundColor Cyan
$ZipPath = Join-Path $Dist "TaskFlowAI-portable.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $Pkg "*") -DestinationPath $ZipPath

$Size = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "完成: $ZipPath ($Size MB)" -ForegroundColor Green
