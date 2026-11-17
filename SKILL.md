# SKILL.md — 项目开发规范

> 适用范围：本仓库所有代码改动、文档改动、环境操作。
> 读者：参与本项目的 AI agent 与人类开发者。
> 与代码冲突时，以本文件为准；本文件与现实冲突时，先改本文件，再改代码。

---

## 0. 一句话原则

**任何改动都必须能被一句话说明"为什么"、一个命令验证"有效"、一条 trace 证明"发生过"。**

做不到这三点，就不要提交。

---

## 1. 项目不变量（改代码前先读）

这六条是设计前提，破坏它们等于换了一个项目：

| # | 不变量 | 含义 |
|---|---|---|
| I1 | **状态机是唯一写入者** | 只有 `agent/machine.py` 推进状态、写结果；角色模块（planner/reader/writer）只做纯计算并返回 |
| I2 | **状态外置** | 中间产物落 SQLite；进 prompt 的只有摘要与编号，不累积全量历史 |
| I3 | **每个外部调用都有 span** | LLM / 搜索 / 抓取 必须包在 `tracer.span(...)` 里，否则 trace 断链 |
| I4 | **预算在循环内检查** | 任何可能循环的地方（GATHER、反思轮）都要调 `_budget_reason` |
| I5 | **引用必须可校验** | 报告里的 `[En]` 要么能通过 `verify.py`，要么被标为未证实；不允许"只写编号不校验" |
| I6 | **可离线运行** | 新增任何外部依赖都必须同时提供 mock 路径，`RUN_MODE=mock` 下能跑通 |

---

## 2. 目录与分层

```
src/dra/
├── agent/        编排层：只做状态推进与决策，不直接发 HTTP
│   ├── machine.py    状态机（唯一写入者）
│   ├── planner.py    子问题拆解
│   ├── reader.py     抓取与清洗
│   └── writer.py     报告生成
├── providers/    接入层：所有外部 I/O 只允许出现在这里
│   ├── llm.py
│   ├── search.py
│   └── fetch.py
├── config.py     配置（环境变量 → Settings）
├── store.py      SQLite 持久化
├── trace.py      span 埋点
├── verify.py     引用校验
├── models.py     内部数据结构
└── util.py       无状态工具函数
```

**硬性规则**

- `agent/*` 里**禁止**出现 `httpx`、`requests`、`urllib` 的调用。需要外部数据，走 provider。
- `providers/*` 里**禁止**出现状态机逻辑、预算判断。它们只负责"调一次、返回结构化结果或抛异常"。
- 新增能力优先加在 `agent/`，而不是往 `machine.py` 里堆 `if`。machine 只该有状态转移。

---

## 3. 代码规范

### 3.1 基本约定

- Python 3.12，全部文件 `from __future__ import annotations`
- 公开函数写类型标注；内部小函数可省
- 数据用 `@dataclass`，跨模块契约用 `pydantic.BaseModel`（只用于 LLM 结构化输出）
- 模块头写一句 docstring 说明"这个文件负责什么、不负责什么"

### 3.2 语言约定（强制）

| 部分 | 语言 | 说明 |
|---|---|---|
| 标识符（变量/函数/类/常量/文件名） | **英文** | `def verify_citations(...)`、`class SearchChain` |
| **注释（行内、块、docstring）** | **中文** | 无例外，见下方自查命令 |
| 用户可见文案（CLI 输出、报告、错误信息） | **中文** | 报告本身也是中文，术语可保留英文原词 |
| 提交信息 | **类型英文 + 描述中文** | `feat: 引用回填校验`，见 §8.1 |
| 日志字段 / 事件名 / 配置键 | **英文** | `emit("search_done", results=8)` |

**所有注释一律用中文**，包括：模块 docstring、类/函数 docstring、行内 `#` 注释、分节注释。

允许的例外只有三类：

1. shebang（`#!/usr/bin/env python`）与编码声明
2. 被注释掉的 SQL / 正则 / URL 等字面量
3. `# type: ignore` 这类工具指令

自查命令（提交前跑一次，应无输出）：

```powershell
Get-ChildItem src,scripts -Recurse -Filter *.py |
  Select-String -Pattern '^\s*#\s*[A-Za-z]'
```

发现英文注释就改中文，而不是加进例外。

### 3.3 禁止事项

| 禁止 | 原因 |
|---|---|
| 使用 `tempfile` | 本机沙箱下 `mkdtemp` 创建的目录会丢权限，写入失败 |
| 引入新第三方依赖 | 依赖需审批，且要同步 `requirements.txt` 与 `vendor/` |
| `print()` 打日志 | 外部调用用 span；用户可见输出走 `emit()` 事件，由 `main.py` 渲染 |
| 裸 `except:` | 至少 `except Exception as exc` 并记录 |
| 把密钥写进代码或默认值 | 只从 `Settings` 取，来自 `.env` |

### 3.4 错误处理

- provider 层：捕获网络/解析异常，**转成带语义的异常**（`LLMError` / `SearchError`）
- 编排层：区分三类
  - 可降级（搜索源失败）→ 换下一个 provider
  - 可跳过（单篇抓取失败）→ 标记 `fetch_failed` 继续
  - 不可继续（规划失败）→ 进 `FAILED`，保留已有产物
- 任何重试都要有上限和退避，禁止无限重试

### 3.5 时间与金额

- 时间统一 `util.now_iso()`（带时区）
- 金额一律用 `Settings.cost_cny()` 计算，不在业务代码里写单价
- 浮点比较用 `EPS` 容差，禁止直接 `>=` 比较比例阈值

---

## 4. Agent 层规则

### 4.1 状态转移

```
INIT → PLAN → GATHER ⇄ REFLECT → WRITE → DONE
                   ↘ FAILED / BUDGET_EXCEEDED / CANCELLED
```

新增状态时必须同时完成四件事：

1. 在 `TERMINAL` 或转移表里登记
2. `_emit("state", ...)` 有对应事件
3. `docs/00-pre-dev-spec.md` 的状态表更新
4. 有一个测试或 mock 场景能走到该状态

### 4.2 预算

每个长循环开头：

```python
reason = self._budget_reason(stats, elapsed)
if reason:
    stop_reason = reason
    state = "REFLECT"   # 或直接进 WRITE 输出部分结果
    break
```

**永远不要**让预算超限后静默继续，也永远不要直接抛错——要降级输出已得结论。

### 4.3 事件协议（与前端/CLI 的契约）

```python
self._emit("state", state="GATHER", steps=3)
self._emit("plan", questions=[...])
self._emit("search", question="...")
self._emit("search_done", results=8)
self._emit("read_done", docs=3)
self._emit("reflect", evidence_count=12, stop_reason=None)
self._emit("verify", total=22, supported=8, weak=12, unverified=2, missing=0)
self._emit("done", run_id=..., stats={...})
self._emit("error", message="...")
```

新增事件：先更新本节，再更新 `main.py` 的渲染，最后更新 `docs/04-outlook.md` 的 SSE 表。

---

## 5. Provider 规则

每个 provider 必须满足三件事：

1. **接口统一**：`search(query) -> list[SearchResult]` / `fetch(url) -> Page` / `complete(messages) -> LLMResult`
2. **异常语义化**：抛自己的异常类，不把 `httpx` 的异常泄漏到上层
3. **可录制**：`RUN_MODE=record` 把响应写入 `fixtures/`，`mock` 时读回放

新增 provider 的检查清单：

- [ ] 有超时设置
- [ ] 有单次重试（含退避）
- [ ] 返回值有上限（条数/字节）
- [ ] 在 `fixtures/` 下留一份样例响应
- [ ] 有对应的离线单测（用 `respx` mock HTTP）

---

## 6. 测试规范

- 测试必须**离线**，不允许真实调用 API
- HTTP 用 `respx` 打桩；文件读取用 `tmp_path`
- 每个 bug 修复配一个回归测试，命名描述行为：`test_<场景>_<期望>`
- 运行：

```bat
scripts\test.cmd
```

- 提交前必须全绿。测试失败时**不允许**用 `--no-verify` 或跳过绕过。

---

## 7. 文档规范

| 文档 | 什么时候必须改 |
|---|---|
| `README.md` | 能力变化、指标更新、快速开始命令变化 |
| `docs/00-pre-dev-spec.md` | 架构、数据模型、状态机、接口变化 |
| `docs/01-roadmap.md` | 迭代进度变化（打勾/标注完成） |
| `docs/03-usage-guide.md` | 用户可见的命令、参数、产物、配置变化 |
| `docs/04-outlook.md` | 新增远期方向或被证伪的计划 |
| `docs/07-bugs.md` | **修复任何 bug 后必须补一条**（现象/根因/解决/教训） |
| `SKILL.md`（本文件） | 规则本身变化 |

**指标写法**：必须是"同一套输入 + 可复现命令 + 具体数字"。禁止写"效果显著提升"。

---

## 8. Git 规范

### 8.1 提交信息

Conventional Commits 格式，但**描述用中文**：类型前缀保留英文（便于工具解析与筛选），冒号后的摘要与正文用中文。

```
feat: 引用校验：把每个 [En] 回填到原文比对

- verify.py：切句、中文 bigram 分词、三级判定
- 参考来源改为按实际引用生成
- 新增 12 个离线测试
```

规则：

- 标题一行，不超过 50 字，不加句号
- 空一行再写正文要点，每条以 `-` 开头
- 正文说清"改了什么、为什么"，不写"优化了代码"这种空话
- 类型前缀：`feat` / `fix` / `refactor` / `docs` / `test` / `chore`

**历史说明**：仓库前 5 个提交是英文的，属于规则建立前的产物，不重写历史（重写需要 force push，会破坏引用）。从本规则生效之日起，新提交一律用中文描述。

### 8.2 绝对不能提交

```
.env          （密钥）
vendor/       （依赖，体积大）
.work/        （报告、trace、数据库）
.tools/       （本地工具）
__pycache__/
```

提交前必查：

```bat
git status --short
git diff --cached --name-only | findstr /I ".env vendor .work"
```

有任何命中就停下来。

### 8.3 分支

单人项目直接在 `main` 上提交；只有做实验性改动（如多 Agent 对照）才开分支，且分支名带前缀：`exp/multi-agent`。

---

## 9. 环境操作手册

### 9.1 常用命令

| 目的 | 命令 |
|---|---|
| 检查环境 | `scripts\check.cmd` |
| 跑一次研究 | `scripts\run.cmd "问题"` |
| 跑测试 | `scripts\test.cmd` |
| 装依赖 | `scripts\setup.ps1`（需完全权限） |
| 推送 | `git push` |

### 9.2 本机特异性（踩过的坑，别再踩）

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError` 但依赖已装 | pip 创建的目录丢了用户权限 | 重跑 `scripts\setup.ps1`（内含 `icacls` 修复） |
| pip 安装报 `PermissionError` | 沙箱禁止写临时目录 | 安装命令需完全权限，且 `TMP` 指向 `.work\tmp` |
| `无法加载 .ps1` | PowerShell 执行策略 | 用 `.cmd` 包装器 |
| 中文乱码 | 控制台代码页与输出编码不一致 | 代码里强制 UTF-8 + `chcp 65001`（已封装在 `util.setup_console`） |
| `git` 找不到 | 安装在 `C:\GIT\Git`，不在 PATH | 用完整路径，或新开终端 |
| git 报 `SEC_E_NO_CREDENTIALS` | schannel 在受限环境不可用 | 仓库已配置 `http.sslBackend=openssl` |
| push 失败 `could not read Username` | 需要交互式认证 | 在自己的终端执行 push，让 GCM 弹浏览器 |

### 9.3 依赖变更流程

1. 说明为什么现有依赖不够
2. 固定版本写进 `requirements.txt`
3. `scripts\setup.ps1` 安装
4. 验证权限修复生效（`import` 成功）
5. 同步更新 `.env.example`（如果是新的配置项）

---

## 10. 定义完成（DoD）

一个改动算完成，需要同时满足：

- [ ] `scripts\test.cmd` 全绿
- [ ] `scripts\run.cmd "问题"` 端到端能跑通（改动涉及主链路时）
- [ ] trace 里有对应的 span，且能在 JSONL 里看到
- [ ] 相关文档已更新（见 §7）
- [ ] 修的是 bug 的话，`docs/07-bugs.md` 已补记录
- [ ] 提交信息符合 §8.1
- [ ] `git status` 里没有不该提交的文件
- [ ] 如果改了指标口径，README 的数字同步更新

---

## 11. 禁止清单（直接拒绝执行）

1. **不打招呼就重构**。改动超过 3 个文件或跨层，先说明方案。
2. **为了让指标好看而调整口径**。换题、改阈值、砍难例都算作弊；要改必须在提交信息里写清楚。
3. **删掉失败分支**。让测试变绿的正确方式是修 bug，不是删断言。
4. **引入"看起来高级"但无验证的技术**（向量库、多 Agent、微服务化）。先证明现有方案不够。
5. **跳过 trace 直接调 prompt**。没有失败证据的 prompt 改动一律视为猜测。
6. **把密钥、报告、依赖提交进仓库**。

---

## 12. 给 AI agent 的额外指令

- 改动前先读 `docs/00-pre-dev-spec.md` 与 `docs/01-roadmap.md`，确认这次改动属于哪个版本
- 一次只做一件事；不要在一次提交里同时改架构和修 bug
- 不确定的地方（阈值、接口形态、指标口径）先问，不要自己拍板
- 每次改完，主动报告：改了哪些文件、为什么、如何验证、仍未解决什么
- 发现本文档与现实不符时，**先修文档**，再改代码
