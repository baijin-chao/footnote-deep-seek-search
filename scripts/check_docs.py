"""检查文档是否跟上了代码。

三类检查：
1. `src/dra` 下的模块是否都出现在 docs/02-architecture.md 的模块表里
2. 模块表里是否还留着已被删除的模块
3. `.env.example` 里的配置项是否都出现在 config.py 中，README 的相对链接是否有效

退出码 0 表示文档与代码一致，1 表示有遗漏。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "dra"
ARCH = ROOT / "docs" / "02-architecture.md"
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG = SRC / "config.py"

EXEMPT = {"__init__.py", "__main__.py"}
# 模块表里用通配写法覆盖整个目录时，这些前缀视为已记录
WILDCARD_OK = ("eval/",)


def setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def list_modules() -> set[str]:
    modules = set()
    for path in SRC.rglob("*.py"):
        if path.name in EXEMPT:
            continue
        modules.add(path.relative_to(SRC).as_posix())
    return modules


def documented_modules() -> set[str]:
    text = ARCH.read_text(encoding="utf-8")
    # 只看模块职责表里的反引号路径
    found = set()
    for match in re.findall(r"`([\w/]+\.py)`", text):
        found.add(match)
    return found


def check_modules() -> list[str]:
    problems = []
    actual = list_modules()
    documented = documented_modules()

    for module in sorted(actual):
        covered = module in documented or any(module.startswith(p) for p in WILDCARD_OK)
        if not covered:
            problems.append(f"模块未写入 docs/02 模块表：src/dra/{module}")

    for name in sorted(documented):
        # 模块表里的相对写法（如 agent/machine.py）直接比对；根级模块同名即可
        if "/" in name:
            exists = (SRC / name).exists()
        else:
            exists = any(Path(m).name == name for m in actual)
        if not exists:
            problems.append(f"模块表引用了不存在的模块：{name}")

    return problems


def check_env_keys() -> list[str]:
    problems = []
    config_text = CONFIG.read_text(encoding="utf-8")
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        upper = key.upper()
        if upper not in config_text.upper():
            problems.append(f"配置项未在 config.py 中出现：{key}")
    return problems


def check_readme_links() -> list[str]:
    problems = []
    text = README.read_text(encoding="utf-8")
    for target in re.findall(r"\]\((?!https?://)([^)#]+)", text):
        if not (ROOT / target).exists():
            problems.append(f"README 链接失效：{target}")
    return problems


def main() -> int:
    setup_stdout()
    problems = check_modules() + check_env_keys() + check_readme_links()

    if not problems:
        print("[OK] 文档与代码一致")
        return 0

    print(f"[FAIL] 发现 {len(problems)} 处文档落后：")
    for item in problems:
        print(f"  - {item}")
    print("\n修复后再提交；文档同步要求见 SKILL.md §7。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
