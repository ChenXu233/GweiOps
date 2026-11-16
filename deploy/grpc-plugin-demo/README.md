# 进程外插件示例

一个最小的 gRPC 插件:自己的进程、自己的依赖,核心只通过 `plugin.yaml` 里的
`endpoint` 找到它。能力、任务名映射、效果声明、配置声明全在清单里声明——wire 只承载调用。

它演示的不是"能连上",而是两件在进程外最容易漏的事:

- **当一个效果提供者**:`scan.todos` 是一条真效果。执行在目标目录落一个印记,句柄就是印记文件名,撤销 = 删掉它,验证 = 印记还在不在。变更单元推得完、撤得掉。
- **拿到自己的配置**:进程外读不到核心的环境变量与库,值由核心经 `Configure` 推下来。

字段与失败语义见[插件系统参考](../../docs/reference/plugin-system.md#进程外grpc插件)。

字段与失败语义见[插件系统参考](../../docs/reference/plugin-system.md#进程外grpc插件)。

## 跑一次

```bash
# 1) 起插件进程(仓库根)
uv run --project engine python deploy/grpc-plugin-demo/server.py

# 2) 让引擎装上它:清单默认 default_enabled: false,
#    把 plugin.yaml 拷进插件目录并打开
cp -r deploy/grpc-plugin-demo plugins/builtin/actions/demo-remote-scan
#    或者只拷声明、把 endpoint 留下:
PLUGINS_EXTRA_DIRS=$PWD/deploy PLUGINS_ENABLED=demo-remote-scan \
  uv run --project engine uvicorn engine.api.app:app --port 8000

# 3) 看它有没有被认出来
curl -sS localhost:8000/api/plugins | jq '.[] | select(.name=="demo-remote-scan")'
#    返回值里 capabilities 有 scan.todos,enabled 为 true

# 4) 给它的配置(核心会推下去;插件把它写进印记)
curl -sS -X PUT localhost:8000/api/settings/scopes/demo-remote-scan \
  -H 'content-type: application/json' \
  -d '{"values": {"note": "手工验证的印记"}}'

# 5) 当效果用:走出口或 intent 都会落成一个变更单元,
#    执行后在目标目录里能看到 <句柄>.gwei-scan.json
```

清单里 `default_enabled: false`:不被显式打开就不会加载,`GET /api/plugins`
会把它列出来并说明原因。

`PLUGINS_GRPC` 形式的临时接入也给支持(`name=host:port`),但该方式没有清单,
也就没有任何能力声明,只能用来确认远端可达。正式接入把 `plugin.yaml` 放进插件目录。

## 换个语言写

`proto/plugin.proto` 就是全部合同,任何有 gRPC 的语言都能照着实现:

```bash
protoc -I proto --python_out=. --grpc_python_out=. proto/plugin.proto  # 或任何目标语言
```
