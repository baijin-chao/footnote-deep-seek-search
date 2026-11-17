# Footnote — Deep Research Agent

输入一个开放性问题，Agent 自主完成「拆解 → 检索 → 阅读 → 反思 → 写作」，输出每个结论都能溯源到原文的报告。

> 当前版本：**v1.0**（引用可校验）　｜　进行中：V2 评测集
>
> 已发布：`v0.1` 最小闭环 · `v1.0` 引用回填校验

**为什么叫 Footnote**：研究报告最有价值的不是结论，是脚注——它决定了结论能不能被验证。这个项目的核心工作，就是让报告里的每个 `[En]` 都真的能回到原文，而不是一个装饰性的编号。

## 文档

| 文档 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | **开发规范**：不变量、分层、代码/测试/提交规则、环境手册 |
| [使用指南](docs/03-usage-guide.md) | 安装、命令、产物、排错、提问技巧 |
| [迭代路线](docs/01-roadmap.md) | V0–V5 每次迭代的目标与指标 |
| [引用校验](docs/05-citation-verification.md) | 方法、阈值、实测结果与已知局限 |
| [评测设计](docs/06-eval-design.md) | V2：20 题评测集、判分标准、失败分类、跑批工具 |
| [Bug 记录](docs/07-bugs.md) | 开发中真实踩过的坑：现象、根因、解决、教训 |
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

## 当前状态（V1）

**V1 新增：引用回填校验。** 报告里的每个 `[En]` 都会被拿去和对应证据的原文比对词面覆盖率，分三级输出：

| 等级 | 判据 | 含义 |
|---|---|---|
| 强支撑 | 覆盖率 ≥ 50% | 断言用词与原文高度重合 |
| 弱支撑 | 30% – 50% | 多为改写或综合表述，需人工复核 |
| 未证实 | < 30% | 可能编造，报告末尾会单列 |

参考来源改为**程序生成**，只列正文真正引用过的条目，模型不再自己编列表。

一次真实运行（RAG vs 微调）：

| 指标 | 数值 |
|---|---|
| 状态 | done |
| 证据数 | 12 |
| 步数 | 8 |
| token | 8,962 in / 1,111 out |
| 成本 | ¥0.029 |
| 耗时 | 21.6s |
| 引用断言 | 22 处：强支撑 8、弱支撑 12、未证实 2 |
| 落地率 | 91%（强+弱） |

方法与局限见 [docs/05-citation-verification.md](docs/05-citation-verification.md)。

### 仍未解决的

1. 子问题覆盖不均，可能漏掉关键角度 → V3 反思回环
2. 抓取失败只是跳过，没有分类重试 → V1 剩余部分
3. 没有评测集，"质量还行"仍是主观判断 → V2
4. 词面校验无法识别语义矛盾（数字被改但用词相同）→ V2 加模型校验

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
