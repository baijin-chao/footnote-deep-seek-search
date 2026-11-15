# Deep Research Agent

输入一个开放性问题，Agent 自主完成「拆解 → 检索 → 阅读 → 反思 → 写作」，输出每个结论都能溯源到原文的报告。

> 当前版本：**V0**（最小闭环）。

## 文档

| 文档 | 内容 |
|---|---|
| [使用指南](docs/03-usage-guide.md) | 安装、命令、产物、排错、提问技巧 |
| [迭代路线](docs/01-roadmap.md) | V0–V5 每次迭代的目标与指标 |
| [未来展望](docs/04-outlook.md) | 浏览器界面设计、中期方向、长期加分项 |
| [开发前置说明](docs/00-pre-dev-spec.md) | 技术选型、架构、数据模型、评测方案 |
| [示例报告](docs/example-report-v0.md) | V0 真实产出 |

---

## 快速开始

```bat
REM 1. 安装依赖（已装过可跳过）
scripts\setup.ps1

REM 2. 配置密钥
copy .env.example .env
REM   然后编辑 .env，填入 LLM_API_KEY 与 SEARCH_API_KEY

REM 3. 跑一个问题
scripts\run.cmd "什么是检索增强生成（RAG）？它的主要局限是什么？"
```

PowerShell 用户：`powershell -ExecutionPolicy Bypass -File scripts\run.ps1 "问题"`

### 常用参数

| 参数 | 说明 |
|---|---|
| `--max-steps N` | 覆盖最大步数 |
| `--max-cny X` | 覆盖成本上限（元） |
| `--quiet` | 只输出最终报告 |
| `--out path.md` | 指定报告输出路径 |

产物位置：报告 `.work/reports/<run_id>.md`，trace `.work/traces/<run_id>.jsonl`，数据库 `.work/dra.db`。

---

## 架构

```
CLI (main.py)
   └── 状态机 (agent/machine.py)
         PLAN ──▶ GATHER ──▶ REFLECT ──▶ WRITE ──▶ DONE
                   │
                   ├── planner.py   LLM 拆解子问题（JSON 模式）
                   ├── searcher     Tavily → 博查 降级链
                   ├── reader.py    抓取 + 正文抽取 + 去重 + 可信度打分
                   └── writer.py    带 [E1] 引用的报告生成

providers/  llm(DeepSeek) · search(Tavily/Bocha) · fetch(httpx+trafilatura)
store.py    SQLite：run / sub_q / evidence / claim / report / span
trace.py    span 树 → SQLite + JSONL
```

**核心设计：状态外置。** 每步产出写入 SQLite，进 prompt 的只有证据摘要和编号，不累积全量历史。

---

## V0 基线数据

首个真实问题（RAG 定义与局限），模型 `deepseek-flash`：

| 指标 | 数值 |
|---|---|
| 状态 | done |
| 步数 | 8（1 计划 + 6 子问题 + 1 写作） |
| 证据数 | 12 |
| token | 8,700 in / 1,226 out |
| 成本 | ¥0.029 |
| 耗时 | 30.9s |
| span 数 | 34 |

**已观察到的 V0 缺陷**（V1/V2 要修的）：

1. 子问题「RAG 的主要局限」只采纳 1 篇正文，覆盖不足 → 反思回环缺失（V3）
2. 引用只有编号，没有回填校验，无法验证是否真的支持该句 → V1
3. 没有任何失败重试分类，抓取失败只是跳过 → V1
4. 没有评测集，上述“质量还行”是主观判断 → V2

---

## 目录

```
src/dra/           主代码
  agent/           状态机与各角色
  providers/       LLM / 搜索 / 抓取
  eval/            评测（V2 开始填充）
scripts/           启动与安装
docs/              设计文档与迭代路线
vendor/            依赖（不提交）
fixtures/          录制回放（V1 开始填充）
```

## 配置

见 [.env.example](.env.example)。关键项：`LLM_MODEL`（默认 `deepseek-flash`）、`BUDGET_MAX_CNY`（默认 0.6 元）。

## 已知环境约束（本机）

- 依赖装在 `vendor/`，靠 `PYTHONPATH` 注入，不使用 venv
- pip 创建的目录权限异常，安装后需对本目录树追加读权限（见 `docs/01-roadmap.md` 的运维备注）
- 未安装 git；如需版本历史请先装 Git for Windows

## License

[MIT](LICENSE) © 2026 baijin-chao

`vendor/` 下的第三方依赖各自遵循其上游许可证，不受本项目许可证影响。
