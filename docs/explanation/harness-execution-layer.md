# Harness 执行层

> 状态:设计待审(2026-11-01) | 读者:架构 / 后端
> 上游:[变更单元契约](change-unit-contract.md)、[插件系统参考](../reference/plugin-system.md)
> 口径:本文是设计稿,字段与接口尚未实现。已落地的是变更单元、插件注册表与 docker compose 下游样例。

## 1. 位置

harness 不是新的一层,是 **intent 的提供者**:一个普通 agent 插件,把信号变成单元里的意图和候选效果。用哪个 agent 运行时(dsh / WorkBuddy / 自研)由清单声明。

分工:变更单元定义「改什么、怎么撤、算不算成」,harness 定义「谁想出这个改动」。

## 2. 清单增量

```yaml
runtime:
  kind: harness
  driver: dsh                # dsh | workbuddy | http | grpc
  entry: headless            # headless | session
  command: ["dsh", "--profile", "headless", "--json", "-"]
  session: resume            # resume | fresh
  limits: { seconds: 1800, max_turns: 200, max_tokens: 200000 }
```

- 不新增插件类型,`type: agent` 不变;
- `capabilities` / `tasks` / `capabilities_priority` 复用,调用方不改;
- 核心不消费 `runtime` 块,由适配器读取——与 `effects` 块同一种处理方式。

## 3. Assignment 与 Session

- **Assignment**:一次意图生成请求,带租户、信号、能力、限额、输出契约;
- **Session handle**:不透明字符串,控制面只存不解释;
- 换 harness 时用上下文重建会话,不迁移 handle;
- 存储:优先 DBOS workflow 状态;需要跨工作流查询时落一张表。

## 4. Worker 边界

- Worker 不写业务库,不持有 Issue / PR 状态;控制面持有全部业务真相;
- 每次模型调用归属到租户,超配额由网关拒绝;
- 远程 harness 走 gRPC;进程内适配器走 CLI / HTTP。

## 5. 部署

- 每租户一个 worker runtime;托管版的模型调用走网关的 per-tenant key;
- 自托管同一份 compose,租户数 N=1;
- 镜像由 oh-my-dsh-pack 提供,GweiOps 只维护契约与客户端。

## 6. 待定

- 第一个 IM 源(飞书 / 企微 / Slack)?
- 第一个告警源(Alertmanager / Grafana)?
- 计费单位(席位 / 事件 / 工单 / token)?

## 7. 阶段

D1–D5 见 [路线图](../plan/roadmap.md),顺序排在变更单元闭环之后。
