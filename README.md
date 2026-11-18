# Footnote — Deep Research Agent

[![tests](https://github.com/baijin-chao/footnote-deep-seek-search/actions/workflows/tests.yml/badge.svg)](https://github.com/baijin-chao/footnote-deep-seek-search/actions/workflows/tests.yml)

输入一个开放性问题，Agent 自主完成「拆解 → 检索 → 阅读 → 反思 → 写作」，输出每个结论都能溯源到原文的报告。

> 当前版本：**v2.1-dev**（挑战集 12 题、判分校准、录制回放）
>
> 已发布：`v0.1` 最小闭环 · `v1.0` 引用回填校验

**为什么叫 Footnote**：研究报告最有价值的不是结论，是脚注——它决定了结论能不能被验证。这个项目的核心工作，就是让报告里的每个 `[En]` 都真的能回到原文，而不是一个装饰性的编号。

## 文档

| 文档 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | **开发规范**：不变量、分层、代码/测试/提交规则、环境手册 |
| [架构](docs/02-architecture.md) | 分层、模块职责、数据流、状态机、扩展点 |
| [使用指南](docs/03-usage-guide.md) | 安装、命令、产物、排错、提问技巧 |
| [迭代路线](docs/01-roadmap.md) | V0–V5 每次迭代的目标与指标 |
| [引用校验](docs/05-citation-verification.md) | 方法、阈值、实测结果与已知局限 |
| [评测设计](docs/06-eval-design.md) | V2：20 题评测集、判分标准、失败分类、跑批工具 |
| [判分校准](docs/08-calibration.md) | judge 与逐条标注的一致率、分歧分析与局限 |
| [挑战集](docs/09-challenge-set.md) | 12 道难题的设计、83% 基线与失败分析 |
| [Bug 记录](docs/07-bugs.md) | 开发中真实踩过的坑：现象、根因、解决、教训 |
| [未来展望](docs/04-outlook.md) | 浏览器界面设计、中期方向、长期加分项 |
| [开发前置说明](docs/00-pre-dev-spec.md) | 技术选型、架构、数据模型、评测方案 |
| [示例报告](docs/example-report.md) | V2 真实产出（含引用校验） |

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

REM 4. 跑评测（可选）
scripts\eval.cmd --limit 5

REM 5. 离线演示（用仓库内已录制的响应，不联网）
scripts\demo.cmd
```

PowerShell 用户：`powershell -ExecutionPolicy Bypass -File scripts\run.ps1 "问题"`

### 常用参数

| 参数 | 说明 |
|---|---|
| `--max-steps N` | 覆盖最大步数 |
| `--max-cny X` | 覆盖成本上限（元） |
| `--no-cache` | 禁用搜索缓存（评测时效题时用） |
| `--mode record` / `--mode mock` | 录制响应 / 离线重放（断网演示） |
| `--quiet` | 只输出最终报告 |
| `--out path.md` | 指定报告输出路径 |

评测命令 `scripts\eval.cmd`：`--limit N` 冒烟、`--tag 名称` 打标签便于对比、
`--resume` 断点续跑、`--rejudge <目录>` 只重跑判分、`--dry-run` 只校验数据集。

| 命令 | 作用 |
|---|---|
| `scripts\check.cmd` | 校验密钥与连通性 |
| `scripts\check_docs.cmd` | 检查文档是否落后于代码 |
| `scripts\test.cmd` | 跑单元测试（全离线） |
| `scripts\demo.cmd` | 回放已录制的演示（不联网，约 1 秒） |

产物位置：报告 `.work/reports/<run_id>.md`，trace `.work/traces/<run_id>.jsonl`，
数据库 `.work/dra.db`，评测结果 `.work/eval/<时间戳>-<tag>/summary.md`。

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

## 当前状态（V2）

**V1：引用回填校验。** 报告里的每个 `[En]` 都会被拿去和对应证据的原文比对词面覆盖率，分三级输出：

| 等级 | 判据 | 含义 |
|---|---|---|
| 强支撑 | 覆盖率 ≥ 50% | 断言用词与原文高度重合 |
| 弱支撑 | 30% – 50% | 多为改写或综合表述，需人工复核 |
| 未证实 | < 30% | 可能编造，报告末尾会单列 |

参考来源改为**程序生成**，只列正文真正引用过的条目，模型不再自己编列表。

**V2：评测集与跑批。** 20 题评测集 + judge + 失败归因 + 一键跑批，首轮基线：

| 指标 | 数值 |
|---|---|
| 成功率 | 100%（20/20） |
| 拒答正确率 | 100%（3/3） |
| 平均引用落地率 | 89% |
| 单题成本 / 总成本 | ¥0.029 / ¥0.575 |
| 延迟 P50 / P95 | 30.7s / 40.5s |
| 平均步数 | 7.8 |

> ⚠️ **100% 说明这套题太简单，不能用来衡量优化收益**，只能当回归集。
> 详见 [docs/07-bugs.md](docs/07-bugs.md) BUG-17；衡量提升需要另建挑战集。

**判分校准。** 抽 6 题 / 16 个要点判定，judge 与逐条阅读报告的结果一致 15 个：

| 指标 | 结果 | 门槛 |
|---|---|---|
| 要点级一致率 | **93.75%**（15/16） | ≥ 85% |
| 题级通过判定一致 | 6/6 | — |
| 单次判分稳定性 | 偶发抖动（同输入复跑结果不同） | 建议多次取多数 |

方法与两处不一致的根因见 [docs/08-calibration.md](docs/08-calibration.md)。

方法与局限见 [docs/05-citation-verification.md](docs/05-citation-verification.md)、
评测设计见 [docs/06-eval-design.md](docs/06-eval-design.md)。

**离线演示。** 仓库内附一份完整录制（21 个文件 / 313 KB），`scripts\demo.cmd` 直接回放：

| 指标 | 真实调用 | 离线重放 |
|---|---|---|
| 耗时 | 41.6s | **1.3s** |
| 证据 / 步数 | 10 / 7 | 10 / 7（一致） |
| token | 7159 / 1353 | 7159 / 1353（一致） |

**挑战集。** 另建 12 道刻意设计成弱点的题（精确数字、口径差异、需要计算、前提有错），单轮基线：

| 指标 | 结果 |
|---|---|
| 成功率 | 83%（10/12） |
| 总成本 / 延迟 | ¥0.317 / P50 28.9s · P95 41.0s |
| 失败集中 | 检索没拿到关键事实（未覆盖 × 2） |

> ⚠️ **单轮结果不可靠**：同一题两次运行覆盖率 67% → 0%，因为每次拆解与检索命中不同。
> V3 对比必须跑 3 轮取均值。详见 [docs/09-challenge-set.md](docs/09-challenge-set.md) §6。

### 仍未解决的

1. **回归集没有区分度**：20 题基线 100%，只能防退化；提升要看挑战集
2. **挑战集单轮噪声大**：12 题、1 题 8.3 个百分点，需多轮均值
3. **校准的标注由 agent 完成**，不是真人，严格的人机一致性待复标
4. 子问题覆盖不均，可能漏掉关键角度 → V3 反思回环
5. 抓取失败只是跳过，没有分类重试 → V1 剩余部分
6. 词面校验无法识别语义矛盾（数字被改但用词相同）

---

## 目录

```
src/dra/           主代码
  agent/           状态机与各角色
  providers/       LLM / 搜索 / 抓取
  eval/            评测：数据集校验、判分、指标、跑批
eval/dataset/      评测集（v1 回归集 / hard 挑战集）
scripts/           启动、安装、检查、测试、评测
tests/             离线单元测试（48 个）
.github/           CI（push 时跑 pytest）
docs/              设计文档与迭代记录
vendor/            依赖（不提交）
```

## 配置

见 [.env.example](.env.example)。关键项：`LLM_MODEL`（默认 `deepseek-flash`）、`BUDGET_MAX_CNY`（默认 0.6 元）。

## 已知环境约束（本机）

- 依赖装在 `vendor/`，靠 `PYTHONPATH` 注入，不使用 venv
- pip 创建的目录权限异常，安装后需对本目录树追加读权限（见 `scripts/setup.ps1`）
- Git 2.56 已安装在 `C:\GIT\Git`，但未加入 PATH；命令里请用完整路径或新开终端

## License

[MIT](LICENSE) © 2026 baijin-chao

`vendor/` 下的第三方依赖各自遵循其上游许可证，不受本项目许可证影响。
