# 路线图

> 状态:现行 | 日期:2026-11-02
> 读者:维护者
> 口径:只列当前未完成的工作;已完成阶段的清单与 commit 区间留在 git,不在文档里保留。

| 工作 | 状态 | 下一步 |
| --- | --- | --- |
| 变更单元闭环 | 首个真实单元已跑通:GitHub 评论 → 回读验证 → 删除撤销;幂等键已落地 | 接进 DBOS 工作流(replace 现有回评步骤);账本从 JSONL 进业务库 |
| 远程提供者 | 解析层已支持 (租户, 目标),但提供者仍是进程内实例 | gRPC 提供者接线,插件部署在目标环境内、出站连回控制面 |
| Harness 执行层(D1–D5) | 设计待审,见 [Harness 执行层](../explanation/harness-execution-layer.md) | 排在变更单元之后:harness 只承担 intent 生成侧(D1) |
| gRPC 进程外插件(B5) | 骨架:`grpc_loader.py` 有代理与 `PLUGINS_GRPC` 解析,尚无 stub 生成与接线 | 代码生成、代理补全、超时隔离、demo、e2e、compose 示例 |
| Scheduler 循环 | 未排期:`engine/scheduler/` 为空,manifest 的 `type: schedule` 只登记不执行 | 明确是否保留 60s 触发;保留则补调度器,不保留则删掉该 trigger 声明 |
| SaaS 认证与计费 | 设计待审,属于 D4 | 认证/开通/租户隔离/配额/计费 |

## 加新工作

1. 先读 [平台架构](../explanation/platform-architecture.md) 与 [变更单元契约](../explanation/change-unit-contract.md),确认这件事有没有被决定过。
2. 在本表加一行,写清状态与下一步。
3. 完成后删掉本行,不保留历史记录。
