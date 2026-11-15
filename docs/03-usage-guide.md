# 使用指南

> 适用版本：V0 ｜ 最后更新：2026-11-15

---

## 一、五分钟上手

### 1. 打开终端，进入项目目录

```bat
cd /d C:\agent
```

### 2. 检查环境（可选，建议第一次做）

```bat
scripts\check.cmd
```

全部显示 `[ OK ]` 说明密钥与网络都通。若有 `[FAIL]`，看本文第五节。

### 3. 跑一个问题

```bat
scripts\run.cmd "什么是检索增强生成（RAG）？它的主要局限是什么？"
```

等 30–60 秒，终端会实时打印每一步，最后给出报告路径和本次成本。

### 4. 看报告

```bat
notepad .work\reports\<run_id>.md
```

报告中 `[E1]`、`[E2]` 是证据编号，对应「参考来源」列表。

---

## 二、命令参考

| 命令 | 作用 |
|---|---|
| `scripts\run.cmd "问题"` | 跑一次研究 |
| `scripts\run.cmd "问题" --quiet` | 只输出最终报告，不打印过程 |
| `scripts\run.cmd "问题" --max-steps 6` | 限制最大步数（默认 25） |
| `scripts\run.cmd "问题" --max-cny 0.05` | 限制单次成本上限 |
| `scripts\run.cmd "问题" --out D:\a.md` | 指定报告输出路径 |
| `scripts\run.cmd --help` | 查看全部参数 |
| `scripts\check.cmd` | 校验 `.env` 与 API 连通性 |
| `scripts\setup.ps1` | 重装依赖到 `vendor/`（需管理员） |

> 参数必须写在问题**后面**，问题用一对英文双引号包住。

---

## 三、产物说明

每次运行产生四样东西，都在 `.work\` 下：

| 路径 | 内容 | 用途 |
|---|---|---|
| `.work\reports\<run_id>.md` | 最终报告 | 阅读、演示 |
| `.work\traces\<run_id>.jsonl` | 每个 span 的耗时/token/父子关系 | 分析哪一步慢、哪一步失败 |
| `.work\dra.db` | 结构化全量数据（run/子问题/证据/报告/span） | 复查、二次统计 |
| 终端输出 | 实时进度 | 观察 Agent 是否"跑偏" |

### 看 trace（排查问题的主要手段）

```powershell
$f = Get-ChildItem .work\traces\*.jsonl | Sort-Object LastWriteTime | Select-Object -Last 1
Get-Content $f.FullName -Encoding UTF8 | ForEach-Object {
  $o = $_ | ConvertFrom-Json
  "{0,-10} {1,-6} {2,6}ms  tok={3}/{4}" -f $o.name, $o.kind, $o.dur_ms, $o.tokens_in, $o.tokens_out
}
```

重点看三类异常：
- `status = error` 的 span（哪一步报错）
- `dur_ms` 特别大的 span（哪一步慢）
- `attrs.deduped = true`（抓到了重复页面）

### 查某次运行存了什么

```powershell
$py = "$env:DRA_PYTHON"
# 若未设置，用捆绑解释器：
$py = "C:\Users\baijin-chao\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $py -c "import sqlite3;c=sqlite3.connect(r'C:\agent\.work\dra.db');print(c.execute('select id,question,status,steps,cost_cny from run order by started_at desc limit 5').fetchall())"
```

---

## 四、配置说明

所有配置在 `.env`，改完立即生效（无需重启任何服务）。

### 常用配置

| 配置项 | 默认 | 说明 |
|---|---|---|
| `LLM_MODEL` | `deepseek-flash` | 主力模型 |
| `LLM_MODEL_STRONG` | `deepseek-v4-pro` | 升级档，做对照实验用 |
| `SEARCH_PROVIDER` | `tavily` | 主搜索源；`bocha` 为备 |
| `SEARCH_MAX_RESULTS` | 8 | 每个子问题取多少条结果 |
| `BUDGET_MAX_STEPS` | 25 | 最大步数 |
| `BUDGET_MAX_CNY` | 0.6 | 最大成本（元） |
| `BUDGET_MAX_SECONDS` | 120 | 最大耗时（秒） |
| `REFLECT_MAX_ROUNDS` | 2 | 反思补检索轮数（V3 生效） |
| `VERIFY_STRONG` | 0.5 | 引用判定为「强支撑」的词面覆盖率阈值 |
| `VERIFY_WEAK` | 0.3 | 判定为「弱支撑」的阈值，低于此为「未证实」 |

### 换模型

改 `LLM_MODEL` 即可，代码不用动。可选：`deepseek-flash`、`deepseek-v4-pro`。

价格按美元配置（`PRICE_MAIN_INPUT` 等）+ `USD_TO_CNY` 换算，用于成本统计。

### 换搜索源

```ini
SEARCH_PROVIDER=bocha
BOCHA_API_KEY=sk-xxx
```

两个 key 都配好时，Tavily 失败会自动降级到博查。

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 终端中文乱码 | 终端编码与输出不一致 | 已修：`run.cmd` 会 `chcp 65001`。若仍乱码，先手动执行 `chcp 65001` 再跑 |
| `'python' 不是内部或外部命令` | PATH 里是应用商店占位符 | 不要直接敲 `python`，用 `run.cmd` |
| `无法加载文件 run.ps1，禁止运行脚本` | PowerShell 执行策略 | 用 `run.cmd`；或 `powershell -ExecutionPolicy Bypass -File scripts\run.ps1 "问题"` |
| `ModuleNotFoundError: No module named 'xxx'` | 依赖未装，或 vendor 目录权限丢失 | 管理员运行 `scripts\setup.ps1` |
| `HTTP 401` | key 无效或没保存 | 跑 `scripts\check.cmd` 定位 |
| `HTTP 429` | 触发限流 | 等一分钟再跑；或把 `SEARCH_MAX_RESULTS` 调小 |
| 报告里出现"未找到可靠来源" | 该子问题没搜到有效正文 | 正常行为（设计如此，禁止编造）；可换更具体的问法 |
| 运行时长时间无输出 | 6 个子问题串行检索，正常 | 约 30–90 秒；可按 `Ctrl+C` 中断 |
| 成本比预期高 | 子问题多、正文长 | 调小 `SEARCH_MAX_RESULTS` 或 `BUDGET_MAX_CNY` |

---

## 六、写一个好问题的建议

Agent 表现与问题质量强相关。实测下来：

| 好问题 | 差问题 | 原因 |
|---|---|---|
| "2026 年国产开源大模型有哪些主要发布，能力对比如何" | "说说 AI" | 前者可拆解、可检索 |
| "RAG 相比微调在哪些场景更划算" | "RAG 好不好" | 前者有比较维度 |
| "某行业 2025 年市场规模及增速" | "某行业未来会怎样" | 前者有可核查的数据点 |

三条经验：
1. **带时间、范围、比较对象**，Agent 才知道搜什么
2. **一次问一件事**，多主题会稀释证据
3. **无法从公开资料得出答案的问题**（如内部数据、未来预测），它应该拒答而不是编——这正是要观察的行为

---

## 七、当前能力边界（V1）

诚实地说清楚它现在**不能**做什么，避免误用：

- ⚠️ 引用校验是**词面比对**：能挡住"完全没有来源"的编造，挡不住"数字被改但用词相同"的篡改（V2 加模型校验）
- ⚠️ 弱支撑占比较高时（常见于改写型报告），需要人工复核，不能只看通过率
- ❌ 子问题覆盖不均，可能漏掉关键角度（V3 修）
- ❌ 不做多轮追问，一次运行一个独立问题
- ❌ 不读 PDF / 图片 / 需登录的页面
- ❌ 没有 Web 界面，只有命令行
- ❌ 不支持多人并发（SQLite + 单进程）

这些边界就是下一阶段的工作，见 [04-outlook.md](04-outlook.md)。
