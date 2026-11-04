# GweiOps 文档

> 状态:现行 | 日期:2026-11-02
> 读者:所有使用或修改 GweiOps 的人
> 口径:只描述当前 HEAD;实现历史在 git,不在文档里。

## 先读哪份

| 你想做什么 | 读这些 |
| --- | --- |
| 第一次了解平台 | [目标](explanation/goals.md) → [平台架构](explanation/platform-architecture.md) |
| 本地跑起来 | [根 README](../README.md) 的快速开始 |
| 写一个插件 | [写插件](how-to/write-a-plugin.md) → [插件系统](reference/plugin-system.md) |
| 查当前运行行为 | [运行时参考](reference/runtime.md) → [插件系统](reference/plugin-system.md) |
| 想知道一次自动变更的边界 | [变更单元契约](explanation/change-unit-contract.md) |
| 看接下来做什么 | [路线图](plan/roadmap.md) → [Harness 执行层](explanation/harness-execution-layer.md) |

## 文档地图

| 目录 | 装什么 | 读者 |
| --- | --- | --- |
| `explanation/` | 为什么这样设计、决策与愿景 | 架构、产品 |
| `reference/` | 字段、清单、端点、当前运行事实 | 插件作者、后端 |
| `how-to/` | 完成一件具体事 | 插件作者、运维 |
| `plan/` | 当前未完成的工作 | 维护者 |
