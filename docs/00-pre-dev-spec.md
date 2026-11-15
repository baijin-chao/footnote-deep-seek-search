# Deep Research Agent · 开发前置说明

> 版本 v0.1 ｜ 状态：**待确认，未开始编码**
> 本文档只描述"做什么、用什么做、按什么顺序做"。确认后再进入 M0。

---

## 0. 需要你先拍板的 6 件事

| # | 决策点 | 我的建议 | 备选 | 影响 |
|---|---|---|---|---|
| 1 | 主模型 | DeepSeek（OpenAI 兼容协议） | Qwen / GLM / 本地 Ollama | 决定 `providers/llm.py` 默认配置 |
| 2 | 搜索源 | Tavily API | 博查 Bocha / Serper / 自建 | 决定 key 申请与 `providers/search.py` |
| 3 | 交付形态 | CLI + 单页 Web（SSE 流式） | 仅 CLI / Next.js 前端 | 工作量差约 1 人日 |
| 4 | 离线兜底 | **必须做**（mock 回放模式） | 不做 | 决定能否无 key 演示、面试现场是否翻车 |
| 5 | 编排实现 | **自研状态机** | LangGraph | 影响面试深挖时的说服力 |
| 6 | 评测规模 | 50 题 | 20 题（更快） | 工作量差 0.5 人日 |

**关键前提**：即使你暂时没有 API key，项目也必须能在 `RUN_MODE=mock` 下完整跑通并产出报告。这是硬性要求，理由见 §11 风险 R1。

---

## 1. 项目定位

**一句话**：输入一个开放性问题，Agent 自主完成"拆解 → 检索 → 阅读 → 反思 → 补检索 → 写作"，输出一份每个结论都能溯源到原文的报告。

**面试展示目标（三个可量化成果）**

1. 任务成功率（自建 50 题）：基线 → 优化后，给出可复现的对比表
2. 引用可验证率：报告中每个 claim 都能点开原文并高亮对应片段
3. 成本与延迟：单次研究 ≤ 25 步 / ≤ 120 秒 / ≤ ¥0.6

**明确不做（Non-goals）**

- 不做通用聊天助手
- 不做多 Agent 协作（v2 再议，且必须带对照实验）
- 不做浏览器操作 / Computer Use（演示不稳定，风险高于收益）
- 不追求"全自主"，只做**有界自主**（bounded autonomy）

---

## 2. 环境实测结论（本机，已验证）

| 项 | 实测结果 | 对开发的影响 |
|---|---|---|
| Python | 3.12.14，路径 `C:\Users\baijin-chao\.dsh\dsh-runtimes\...\python\python.exe` | 用这个绝对路径，PATH 里的 `python` 是应用商店占位符（exit 9009） |
| Node | v24.21.0（bundled，不在 PATH） | MVP 不需要，前端走无构建方案 |
| git | **未安装** | 无法本地建仓；建议你装 Git for Windows，否则面试展示缺少提交历史 |
| docker | **未安装** | 沙箱隔离只能靠进程内限制，v2 再补 |
| 网络 | 可出网（`api.deepseek.com` 返回 401 说明 TLS 链路正常） | 能调真实 API |
| pip | 可用，但**沙箱下解包会失败**（`tempfile.mkdtemp` 目录权限异常） | 安装依赖需一次性提权；因此采用 `--target vendor/` 方案，不用 venv |
| 沙箱 | 工作区可读写；删除普通文件正常 | 开发无阻塞（已修复过一次工作区权限） |

**因此确定两条工程约束**

- **约束 A**：依赖只装一次，装到 `vendor/`，运行时用 `PYTHONPATH` 注入。不建 venv（venv 的 ensurepip 同样会踩 tempfile 权限问题）。
- **约束 B**：Python 代码里**不使用 `tempfile`**，临时文件统一落到 `.work/` 目录。

---

## 3. 技术栈

### 3.1 核心选型

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.12 | 生态、AST/文本处理、评测脚本方便 |
| 编排 | **自研有限状态机**（`agent/machine.py`） | 状态可枚举、可单测、可序列化；面试能讲清每一步为什么发生 |
| LLM 接入 | 自研 `LLMProvider`，走 OpenAI 兼容协议 | 换模型只改配置；便于加 mock 与录制回放 |
| 搜索 | `SearchProvider` 抽象，默认 Tavily | 返回结构化结果 + 正文片段，省去二次抓取 |
| 抓取 | `httpx` + 正文抽取（trafilatura，失败降级 lxml 自写提取） | 轻量、无浏览器依赖 |
| 服务 | FastAPI + uvicorn + SSE | 流式推步骤，演示效果好；接口天然可被 curl 调用 |
| 存储 | SQLite（stdlib `sqlite3`） | 零运维，单文件可随仓库带走 |
| 可观测 | 自研 span + JSONL trace（对齐 OTel GenAI 语义字段） | 无外部依赖，面试现场可直接 `cat` 给面试官看 |
| 前端 | 单文件 HTML + 原生 JS + EventSource | 无构建、无 npm、断网也能开 |
| 测试 | pytest + respx（HTTP mock） | 工具层必须可离线测试 |
| 打包 | `scripts/setup.ps1` 装到 `vendor/` | 规避 venv/tempfile 限制 |

### 3.2 依赖清单（一次性安装）

```
fastapi  uvicorn  httpx  pydantic  python-dotenv  trafilatura  pytest  respx
```

约 20 个传递依赖，安装体积 < 40 MB。`pydantic` 由 fastapi 带入。

### 3.3 明确不用（及原因）

| 不用 | 原因 |
|---|---|
| LangGraph / LangChain | 黑盒，面试被问到内部实现会失分；且本项目状态机只有 7 个状态 |
| Playwright | 需下载浏览器（100MB+），演示环境不确定性高 |
| Postgres / Redis / 向量库 | MVP 阶段 SQLite 足够；上向量库是 v2 的"规模"话题，不是"正确性"话题 |
| Next.js | 需要 npm 构建链，收益不匹配成本 |
| 任何 SaaS 观测平台 | 演示必须能离线自证；Langfuse 留作 v2 可选导出 |

---

## 4. 架构

```
                    ┌──────────────────────────────┐
   CLI / Web  ────▶ │  server.py  (FastAPI + SSE)   │
                    └──────────────┬───────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  agent/machine.py  状态机     │
                    │  INIT→PLAN→GATHER→REFLECT→   │
                    │  WRITE→DONE  (可回环)         │
                    └───┬───────────┬──────────┬───┘
            ┌───────────┘           │          └────────────┐
            ▼                       ▼                       ▼
    ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
    │ planner/critic│      │ searcher/     │      │ writer        │
    │ (LLM 决策)     │      │ reader (工具)  │      │ (带引用写作)   │
    └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
            └──────────┬───────────┴──────────────────────┘
                       ▼
        ┌──────────────────────────────────┐
        │ providers: llm / search / fetch  │──▶ 外部 API 或 fixtures 回放
        └──────────────────────────────────┘
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
  store.py (SQLite: run/evidence)   trace.py (span JSONL)
```

**核心思想：Blackboard（黑板）模式。** 状态机是唯一写入者，每次状态转移把产出写进 SQLite；LLM 每步只看到"这一步需要的切片"，而不是全部历史。这既控住了上下文长度，也让"中断恢复"变成免费能力。

### 4.1 目录结构

```
C:\agent
├─ apps/web/index.html            # 单页 UI（无构建）
├─ src/dra/
│  ├─ main.py                     # CLI 入口
│  ├─ server.py                   # FastAPI + SSE
│  ├─ config.py                   # 配置与环境变量
│  ├─ models.py                   # 数据模型（pydantic）
│  ├─ store.py                    # SQLite 读写
│  ├─ trace.py                    # span 埋点与 JSONL 落盘
│  ├─ prompts/{plan,reflect,write}.md
│  ├─ providers/{base,llm,search,fetch}.py
│  ├─ agent/{machine,planner,searcher,reader,critic,writer}.py
│  └─ eval/{run_eval.py,judge.py,dataset/*.jsonl}
├─ tests/
├─ vendor/                        # pip --target 依赖（不提交）
├─ fixtures/                      # 录制回放（提交）
├─ docs/
├─ scripts/{setup.ps1,run.ps1,serve.ps1}
├─ .env.example
├─ .gitignore
└─ README.md
```

### 4.2 数据模型（SQLite 表）

```sql
run        (id PK, question, status, mode, config_json,
            tokens_in, tokens_out, cost_cny, started_at, ended_at, error)
sub_q      (id PK, run_id, text, status, priority, order_no)
evidence   (id PK, run_id, sub_q_id, url, title, domain, snippet,
            content, content_hash, credibility, fetched_at)
claim      (id PK, run_id, text, evidence_ids_json, support)   -- supported|unverified|contradicted
span       (id PK, run_id, parent_id, name, kind, ts_start, ts_end,
            tokens_in, tokens_out, cost_cny, status, attrs_json, error)
report     (run_id PK, markdown, citations_json, created_at)
```

### 4.3 状态机

| 状态 | 进入条件 | 动作 | 出口 |
|---|---|---|---|
| `INIT` | 收到问题 | 建 run、检查预算 | → PLAN |
| `PLAN` | — | LLM 输出 3–6 个子问题（结构化 JSON） | → GATHER |
| `GATHER` | 存在待办子问题 | 每个子问题：search → fetch → 抽取 → 写 evidence | 全部完成 → REFLECT |
| `REFLECT` | 有 evidence | Critic 判断：覆盖度/矛盾/缺口 | 有缺口且预算足 → GATHER（补检索）；否则 → WRITE |
| `WRITE` | — | 基于 evidence 生成带 `[E12]` 标记的报告 | → DONE |
| `DONE` | — | 校验引用、落库、统计 | 终态 |
| `FAILED` / `BUDGET_EXCEEDED` / `CANCELLED` | 任意 | 保留部分产物，输出已得结论 | 终态 |

**终止条件（四重，必须全部实现）**：拿到 `finish` 信号、步数上限、token/金额预算、连续两轮无新增 evidence。

---

## 5. 关键设计决策（面试会被追问的点）

**ADR-1｜自研状态机而非 LangGraph**
收益：可直接回答"你的 agent loop 怎么实现的"；支持断点恢复；状态转移可单测。
代价：自己实现持久化与重入，约多花 0.5 人日。

**ADR-2｜状态外置**
Evidence 全文落 SQLite，进 prompt 的只有摘要 + id。防止上下文随步数线性膨胀，这是单次研究能压到 120 秒内的前提。

**ADR-3｜引用溯源做到 span 级**
写入 evidence 时记录正文偏移；生成报告后跑一遍回填校验，claim 与 evidence 片段不匹配则降级标记 `[未证实]`，**绝不编造引用**。

**ADR-4｜预算感知**
每次 LLM/搜索调用前先扣预算；剩余预算不足时 REFLECT 强制进入 WRITE，输出"已知结论 + 明确未覆盖项"。

**ADR-5｜可录制回放**
三个 provider 统一接口，`RUN_MODE=live|record|mock`。mock 模式读 `fixtures/`，保证无 key、断网、限流时仍能完整演示。

**ADR-6｜依赖 vendor 化**
受环境限制，依赖装到 `vendor/` 并靠 `PYTHONPATH` 注入；`setup.ps1` 一条命令可重建。

---

## 6. 开发步骤（含验收标准）

| 阶段 | 内容 | 工期 | 验收标准（DoD） |
|---|---|---|---|
| **M0 脚手架** | 目录、配置、日志、`setup.ps1`、vendor 安装、.gitignore | 0.5d | `run.ps1 --mock "测试问题"` 能跑通并打印占位报告 |
| **M1 Provider 层** | llm/search/fetch 三接口 + live/record/mock 三实现 + 单测 | 1d | mock 下 3 个 provider 各有测试通过，全程不联网 |
| **M2 主循环** | 状态机 + planner/searcher/reader/critic/writer + 落库 | 1.5d | 一个真实问题端到端产出 markdown 报告，状态可回放 |
| **M3 引用** | claim 抽取、span 回填、校验与降级标记 | 1d | 报告中每条引用可点开原文；构造 3 个错误引用被正确标记 |
| **M4 观测** | span 树、耗时/成本聚合、JSONL | 0.5d | 每次 run 有完整 trace，`trace.jsonl` 可读 |
| **M5 评测** | 50 题集 + harness + LLM judge + 人工抽检表 | 1.5d | 一条命令输出指标表（成功率/引用率/步数/成本/延迟） |
| **M6 迭代** | 至少 3 轮"看失败 trace → 改 → 重测" | 2d | 成功率相对基线提升 ≥ 10 个百分点，留下对比表 |
| **M7 Web** | SSE 流式 + 单页 UI | 1d | 浏览器实时看到每一步，可中途取消 |
| **M8 包装** | README、架构图、demo 脚本、3 分钟讲解稿 | 1d | 陌生人照 README 10 分钟内跑起来 |

**合计约 10 人日**（按每天 4–5 小时有效投入，约两周）。M0–M2 是关键路径，M5/M6 决定项目上限。

---

## 7. 评测方案（决定这个项目能不能"过面试"）

**数据集**：50 题，覆盖 5 类（事实型 15 / 对比型 10 / 时效型 10 / 多跳推理 10 / 无解问题 5）。
每题标注：`question`、`must_cover`（必须覆盖的要点）、`must_cite`（必须引用的来源类型）、`should_refuse`（是否属于"查不到就该说不知道"）。

**指标定义**

| 指标 | 计算方式 | 目标 |
|---|---|---|
| 任务成功率 | 人工/LLM 双判：要点覆盖率 ≥ 80% 且无事实错误 | ≥ 75% |
| 引用支持率 | 随机抽 20 条 claim，人工核对引用是否支持该句 | ≥ 90% |
| 拒答正确率 | 5 道无解题中，明确说明"未找到可靠来源"的比例 | ≥ 80% |
| 平均步数 / P95 耗时 / 单次成本 | trace 聚合 | ≤ 25 / ≤ 120s / ≤ ¥0.6 |

**判官校准**：LLM judge 只做初筛，人工抽检 20 条与 judge 结果比对，一致率 < 85% 就改 prompt 或改人工为主。**这一步必须写进 README**——它证明你懂 LLM-as-judge 的偏差。

---

## 8. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 演示现场无 key / 限流 / 断网 | 演示失败 | mock 回放模式（硬性要求）+ 预录 fixture |
| R2 | 搜索 API 额度或反爬 | 抓取失败 | 多 provider 降级；抓取失败标记 `fetch_failed` 而非中断 |
| R3 | LLM 输出非法 JSON | 状态机卡死 | pydantic 校验 + 一次修复重试 + 降级模板 |
| R4 | 上下文爆炸 | 延迟与成本失控 | 状态外置 + 结果截断 + 摘要 |
| R5 | 引用幻觉 | 报告不可信 | span 回填校验，不匹配即降级 |
| R6 | 沙箱 pip/临时目录限制 | 环境搭不起来 | vendor + 禁用 tempfile（已在 §2 固化） |

---

## 9. 配置项（`.env.example`）

```ini
RUN_MODE=live              # live | record | mock
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash           # V4.1-Flash-1017（默认主力）
LLM_MODEL_STRONG=deepseek-v4-pro   # V4-Pro-0813（困难 case 对照）
LLM_API_KEY=sk-xxx
SEARCH_PROVIDER=tavily     # tavily | bocha | mock
SEARCH_API_KEY=tvly-xxx
BOCHA_API_KEY=             # 可选，降级链用
BUDGET_MAX_STEPS=25
BUDGET_MAX_TOKENS=60000
BUDGET_MAX_CNY=0.6
BUDGET_MAX_SECONDS=120
DB_PATH=./.work/dra.db
TRACE_DIR=./.work/traces
FIXTURES_DIR=./fixtures
```

> 计价口径：`deepseek-flash` 输入 $0.30 / 输出 $1.20（每百万 token），`deepseek-v4-pro` 输入 $1.32 / 输出 $3.96，均为峰值价。配置里用美元计价 + `USD_TO_CNY` 换算，避免汇率写死在代码里。

---

## 10. 交付物清单

1. 可运行代码（`scripts/setup.ps1` + `scripts/run.ps1` 两条命令起步）
2. `README.md`：定位、架构图、指标表、快速开始、失败案例分析
3. `docs/`：本文件 + 评测报告 + 迭代记录
4. 3 分钟演示脚本（含一段失败 trace 的归因讲解）
5. （建议）GitHub 仓库与提交历史

---

## 11. 下一步

你确认 §0 的 6 个决策点（尤其 1、2、4）后，我按 M0 → M2 先做出**可端到端跑通的最小版本**，再进入评测迭代。

如果你没有 key：直接告诉我，我按 `mock` 优先开发，你之后补 key 只需改 `.env`，代码不动。
