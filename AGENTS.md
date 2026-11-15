# AGENTS.md

本仓库的开发规范统一写在 [SKILL.md](SKILL.md)，请以该文件为准。

快速摘要：

- 状态机（`src/dra/agent/machine.py`）是唯一写入者，角色模块只做纯计算
- 所有外部 I/O 只允许出现在 `src/dra/providers/`，且必须包在 `tracer.span` 里
- 测试必须离线，提交前跑 `scripts\test.cmd`
- 绝不提交 `.env` / `vendor/` / `.work/` / `.tools/`
- 改动前先读 `docs/00-pre-dev-spec.md`，确认属于哪个迭代版本
