# 安装依赖到 vendor/。
# 注意：本机沙箱对 pip 的临时目录有限制，这个脚本需要在"完全权限"下执行一次。

param(
    [string]$Python = ""
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

if (-not $Python) {
    $Python = $env:DRA_PYTHON
}
if (-not $Python) {
    $Python = "C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
}
if (-not (Test-Path $Python)) {
    throw "找不到 Python 解释器：$Python"
}

$tmp = Join-Path $Root ".work\tmp"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TMP = $tmp
$env:TEMP = $tmp

Write-Host "使用解释器: $Python"
Write-Host "安装到:     $Root\vendor"

& $Python -m pip install --no-cache-dir --target "$Root\vendor" -r "$Root\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    throw "依赖安装失败（exit=$LASTEXITCODE）"
}

# 本机 pip 创建的目录会丢失继承的读取权限，补一条"所有用户可读"，否则运行时会 ImportError
$vendor = Join-Path $Root "vendor"
& icacls $vendor /grant "*S-1-1-0:(OI)(CI)(RX)" /T /C /Q | Out-Null
Write-Host "已修正依赖目录读取权限"

Write-Host "`n完成。运行: .\scripts\run.cmd `"你的问题`""
exit 0
