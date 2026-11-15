# 启动 CLI：.\scripts\run.ps1 "你的研究问题"
# 依赖路径由本脚本注入，不需要先激活任何环境。

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# Python 解释器优先级：环境变量 DRA_PYTHON > 捆绑运行时
$Python = $env:DRA_PYTHON
if (-not $Python) {
    $Python = "C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
}
if (-not (Test-Path $Python)) {
    throw "找不到 Python 解释器：$Python。请设置环境变量 DRA_PYTHON 指向 python.exe"
}

$env:PYTHONPATH = "$Root\vendor;$Root\src"
$env:PYTHONIOENCODING = "utf-8"

& $Python -m dra @Rest
exit $LASTEXITCODE
