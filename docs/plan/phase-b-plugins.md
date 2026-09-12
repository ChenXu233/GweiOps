# Phase B 子计划:插件系统 v2

> 状态:实施中 | 母本:[docs/plan/README.md](README.md) Phase B
> 前置:Phase A 已完成(事件载荷带 `tenant_slug`)。

## 探索结论(实施前核实)

1. **容器打包 bug**:engine 镜像 build context 为 `./engine`(compose.override 与 CI
   build.yml),`plugins/` 从未进镜像——容器内 webhook 的插件 import 必然失败。
   Registry 发现依赖插件文件,本轮一并修复打包(仓库根 context + 显式 COPY)。
2. **github-app 适配器缺 manifest**(在用,需补);`adapters/github`(token 版遗留)
   的 `.client/.git` 导入存疑 → 发现过程逐插件隔离,坏插件记日志+metrics 跳过。
3. 4 个插件文件带 `sys.path.insert` hack(diagnoser/fixer/reporter/github),
   sensor/github-app 已是正常 `engine.` 导入 → 全部统一。
4. Manifest `triggers` 即事件订阅——保守事件链无需新字段;capabilities 与
   execute_task 任务名不一致(`patch.generate` vs `generate_patches`)→ 新增
   `tasks` 映射。
5. `k8s-scaler` 只有空 `__init__.py`,无 plugin.yaml——glob 自然跳过,无需特判。

## B1 核心模块(engine/plugin_manager/)

- [x] `manifest.py`:`Manifest.from_yaml()`;字段 name/version/type/description/
      class_name(必填)/triggers/capabilities + 可选 hooks.offered、
      hooks.subscribe[point,mode,priority,failure_mode,handler]、
      capabilities_priority、tasks(cap→task);非法值抛 ManifestError;
      `event_subscriptions` 派生属性。
- [x] `registry.py`:`PluginRegistry`(可实例化,模块级 `registry` 单例供生产);
      `discover(builtin_dir=None, extra_dirs=None)`——builtin 默认
      `cwd/plugins/builtin`,extra 目录入 sys.path 后按包路径导入;
      import/实例化逐插件隔离(metrics `plugin_discovery_errors_total`);
      三索引:events、capabilities(priority 择优)、hooks(priority 排序);
      `launch/shutdown/health_check_all` 错误隔离;
      `run_capability(cap, params)`(task 名查 tasks 映射,回退 `cap.replace('.','_')`)。
- [x] `events.py`:`EventBus(registry).publish(event, payload)`——fan-out 到事件
      索引,per-subscriber 超时 10s + 异常隔离 + metrics;best-effort 语义
      (持久化/重试归 DBOS,见模块 docstring)。
- [x] `hooks.py`:`HookPipeline(registry).apply(point, payload) -> dict
      {"allowed", "payload"}`——observe 收集 / transform 链式 / veto 短路;
      veto 审计(metrics `plugin_hook_veto_total{plugin,point}` + WARNING 载荷摘要);
      fail_open 跳过 / fail_closed 按 veto;默认 handler `handle_hook`。
- [x] `base.py`:PluginBase 增非抽象 `handle_hook`(默认恒等返回,兼容全部既有插件)。
- [x] 删除 `dispatcher.py`(死代码);`__init__.py` 导出
      registry/events/hooks 单例 + Manifest 等。

## B2 Manifest 数据

- [x] 新建 `plugins/builtin/adapters/github-app/plugin.yaml`
      (class_name GitHubAppAdapter,triggers 取自其 info());
- [x] 8 份现有 yaml 增 `class_name`;
- [x] fixer 增 `tasks: {patch.generate: generate_patches}`;
- [x] `proto/plugin.proto` 增量:HookSubscription 消息 + PluginInfo 字段 7/8
      (仅声明,wire-compatible)。

## B3 导入清理

- [x] diagnoser/fixer/reporter/github(及发现的其他)去 `sys.path.insert`,
      统一 `from engine.plugin_manager.base import ...`。

## B4 接线

- [x] `app.py` lifespan:`registry.discover() → registry.launch()` 替代逐个
      adapter/sensor 启动(失败隔离:坏凭据不再阻止启动,webhook 请求时才失败)。
- [x] `runtime.py`:get_adapter/get_sensor 委托 registry(name 查找),
      registry 未加载时回退旧直连单例(既有 41 测试零改动)。
- [x] `pipeline.py`:
  - `publish_event_step` / `apply_hooks_step`(DBOS step 封装——事件与 hook 必须
    走 step 以获得 checkpoint,恢复重放不重复执行);
  - triage:persist 后 `apply_hooks_step("issue.triaged", ...)`(观察)→
    `publish_event_step("sensor.processed", {tenant_slug, issue})(保守链);
  - fix:@gwei 链 `patch.generated` transform → `comment.posting` veto 检查;
  - fixer 经 `registry.run_capability("patch.generate", params)`,无 provider 或
    异常回退 `_generate_patches_impl`(既有单测保持直连)。

## B5 打包修复

- [x] `docker-compose.override.yml`:engine build context 改仓库根 +
      `dockerfile: engine/Dockerfile`;volume 改挂 `./engine:/app/engine` +
      `./plugins:/app/plugins`;
- [x] CI `build.yml` engine 构建同改(context: `.`);
- [x] `engine/Dockerfile`:builder `COPY engine/pyproject.toml`;runtime 显式
      `COPY engine/ ./engine/` + `COPY plugins/ ./plugins/` + entrypoint;
- [x] `engine/alembic.ini`:`script_location = %(here)s/migrations`;
      `entrypoint.sh`:`alembic -c engine/alembic.ini upgrade head`。

## B6 测试(`tests/test_integration/test_plugin_system.py`)

- [x] manifest:解析/缺字段拒绝/非法 mode 拒绝/event_subscriptions 派生;
- [x] 发现:正常加载、坏 import 插件隔离跳过、重复 name 拒绝;
- [x] 三索引正确性;能力优先级择优 + tasks 映射;
- [x] 事件 fan-out、异常/超时隔离、metrics;
- [x] hooks 三档 + priority 排序 + fail_open/fail_closed + veto 审计;
- [x] 既有 41 测试全绿。

## 验收

全量测试全绿;dogfood 冒烟 triage SUCCESS 且日志出现 diagnoser 经事件链触发;
`docker build`(仓库根 context)成功且镜像内含 plugins/;文档状态回写。
