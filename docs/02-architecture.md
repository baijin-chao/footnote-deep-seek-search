# 架构

> 配套：[00-pre-dev-spec.md](00-pre-dev-spec.md)（选型与取舍）、[SKILL.md](../SKILL.md)（开发规范）

---

## 1. 分层

```
┌──────────────────────────────────────────────┐
│ 入口层    main.py（CLI） / eval/__main__.py  │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 编排层    agent/machine.py（有限状态机）      │
│           planner · reader · writer          │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 接入层    providers/ llm · search · fetch    │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 基础设施  store.py（SQLite） trace.py verify │
│           cache.py recording.py config.py    │
└──────────────────────────────────────────────┘
```

**依赖方向只能向下。** 接入层不知道状态机的存在，基础设施不依赖任何上层。

---

## 2. 模块职责

| 模块 | 负责 | 明确不负责 |
|---|---|---|
| `main.py` | 解析命令行、渲染事件、打印摘要 | 业务逻辑 |
| `agent/machine.py` | 推进状态、检查预算、写库、发事件 | 调用外部 API、生成文案 |
| `agent/planner.py` | 把问题拆成子问题（结构化 JSON） | 检索、写作 |
| `agent/reader.py` | 抓取正文、去重、可信度打分 | 决定读几个、存库 |
| `agent/writer.py` | 组织证据、生成报告、触发校验 | 拼 URL、发请求 |
| `providers/llm.py` | 一次模型调用、重试、用量统计 | 状态管理 |
| `providers/search.py` | 搜索、多 provider 降级、命中缓存 | 正文抽取 |
| `providers/fetch.py` | HTTP 抓取、正文抽取 | 可信度判断 |
| `store.py` | 表结构与读写 | 任何业务判断 |
| `trace.py` | span 树、JSONL 落盘 | 指标计算 |
| `verify.py` | 引用回填校验（词面覆盖率） | 语义判断 |
| `recording.py` | 按请求参数哈希存取 `fixtures/`，支撑 record / mock | 决定何时录制或回放 |
| `cache.py` | 搜索结果缓存（精确 + 近似命中） | 决定用不用缓存 |
| `eval/*` | 跑批、判分、指标、报告 | 改变 agent 行为 |

---

## 3. 一次运行的数据流

```
用户问题
   │
   ├─ PLAN ──▶ LLM 拆解 → sub_q 表（3–6 条）
   │
   ├─ GATHER（每个子问题一轮）
   │    ├─ 缓存查找 → 命中则跳过搜索
   │    ├─ search ──▶ 结果列表
   │    ├─ fetch  ──▶ 正文抽取
   │    └─ 去重后写 evidence 表（含 content_hash、credibility）
   │
   ├─ REFLECT ──▶ 检查证据数与预算，决定继续还是收尾
   │
   ├─ WRITE
   │    ├─ 证据摘要 + 编号 → LLM 生成正文
   │    ├─ verify.py 回填校验 → 强/弱/未证实
   │    ├─ 程序生成参考来源（只列真正引用的）
   │    └─ claim 表记录每条断言的支持状态
   │
   └─ DONE ──▶ report 表 + trace JSONL + 终端摘要
```

---

## 4. 状态机

| 状态 | 进入条件 | 出口 |
|---|---|---|
| `INIT` | 收到问题 | → `PLAN` |
| `PLAN` | — | 有子问题 → `GATHER`；失败 → `FAILED` |
| `GATHER` | 存在 pending 子问题 | 全部处理完 → `REFLECT`；预算耗尽 → `REFLECT` |
| `REFLECT` | 有证据 | 证据数 0 → `FAILED`；否则 → `WRITE` |
| `WRITE` | — | → `DONE` |
| `FAILED` / `BUDGET_EXCEEDED` | 任意 | 终态，保留已有产物 |

**终止条件**：拿不到更多证据、步数上限、token/金额预算、耗时预算。

---

## 5. 数据模型

```sql
run        (id, question, status, mode, tokens_in/out, cost_cny, steps, started_at, ended_at, error)
sub_q      (id, run_id, text, status, order_no)
evidence   (id, run_id, sub_q_id, url, title, domain, snippet, content, content_hash, credibility)
claim      (id, run_id, text, evidence_ids_json, support)     -- supported|weak|unverified|missing
report     (run_id, markdown, citations_json, created_at)
span       (id, run_id, parent_id, name, kind, dur_ms, tokens_in/out, cost_cny, attrs, error)
search_cache (cache_key, provider, query, results, created_at)
```

`span` 的父子关系构成整条链路的树；`claim` 是引用校验的落点。

---

## 6. 扩展点

| 要加什么 | 改哪里 | 注意 |
|---|---|---|
| 新搜索源 | `providers/search.py` 新增类 + `build_search` 注册 | 必须自定义异常、加超时、**接录制器**、留 fixture |
| 新模型 | `.env` 改 `LLM_MODEL` | 计价参数要同时更新 |
| 新状态 | `machine.py` + 事件协议 + 本文档 | 四件事缺一不可（见 SKILL.md §4.1） |
| 新指标 | `eval/metrics.py` + `report.py` | 分母必须含失败题 |
| 新失败类别 | `metrics.FAILURES` + `FAILURE_LABELS` | 顺序即优先级，想清楚放哪 |

---

## 7. 为什么不用框架

自研状态机（而非 LangGraph）的三个理由：

1. **可解释**：七个状态、十几条转移，一页纸能画完；框架的隐式状态反而增加理解成本
2. **可测试**：状态转移是纯逻辑，可以用桩驱动，不需要起服务
3. **可回答**：面试问"你的 agent loop 怎么实现的"，能直接指代码，而不是说"我用了某某框架"

代价是自己实现持久化与中断恢复——这部分目前在 V4（断点续跑）里做。
