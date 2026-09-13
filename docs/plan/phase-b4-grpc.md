# docs/plan/phase-b4-grpc.md(子计划)
# Phase B4 子计划:gRPC 进程外插件(骨架 + 管线设计)

> 状态:骨架已落地,stub 管线待实施 | 母本:README.md Phase B(第四轮)

## 目标形态

`PLUGINS_GRPC="billing=127.0.0.1:50051,..."` 声明的每个端点是一个独立进程,
实现 proto/plugin.proto 的 PluginService;engine 侧 GrpcPluginProxy 把它接入
registry,事件/Hook/能力分发对进程内插件与 gRPC 插件完全一致——闭源插件
(计费等)以任意语言运行在引擎进程之外。

## 已落地(骨架)

- [x] `grpc_loader.py`:GrpcPluginProxy(PluginBase)代理 + PLUGINS_GRPC 解析 +
      register_grpc_plugins()(真实 Manifest,走 registry.register);
- [x] 依赖缺失(gRPC stub 未生成)时显式 NotImplementedError,不影响进程内插件。

## 待实施

- [ ] A1 proto 代码生成管线:grpcio-tools 由 `proto/plugin.proto` 生成
      `engine/plugin_manager/_grpc_stubs/`(构建脚本 + 提交产物二选一,倾向构建期生成);
- [ ] A2 GrpcPluginProxy 补全:Startup/Shutdown/HealthCheck/HandleEvent/ExecuteTask
      的 gRPC 调用 + async 桥(grpc.aio);
- [ ] A3 超时/重试/断连策略(per-call deadline 10s,失败隔离与进程内插件一致);
- [ ] A4 演示插件:Python 参考实现(echo agent,grpc server 骨架 ~60 行);
- [ ] A5 e2e 测试:子进程起 demo server → registry 注册 → 事件送达断言
      (CI 需 grpcio,标记 skip-if-missing);
- [ ] A6 compose:独立 service 示例(billing 插件镜像占位)。

## 风险

- Windows CI 上 grpcio wheel 可用性(python 3.13 有 wheel,风险低);
- 事件载荷跨进程序列化需与 DBOS checkpoint 兼容(JSON 已满足);
- 鉴权:进程间 mTLS/共享密钥——随认证阶段统一。
