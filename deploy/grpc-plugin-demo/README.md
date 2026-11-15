# 进程外插件示例

一个最小的 gRPC 插件:自己的进程、自己的依赖,核心只通过 `plugin.yaml` 里的
`endpoint` 找到它。能力、任务名映射、Hook 订阅全在清单里声明——wire 只承载调用。

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
# 4) 调一次它的能力(走能力通道,与进程内插件没有区别)
```

`PLUGINS_GRPC` 形式的临时接入也给支持(`name=host:port`),但那种方式拿不到清单,
插件一个能力都不会有——它只是让人确认"对面在不在"。把 `plugin.yaml` 放进插件目录
才是正道。

## 换个语言写

`proto/plugin.proto` 就是全部合同,任何有 gRPC 的语言都能照着实现:

```bash
protoc -I proto --python_out=. --grpc_python_out=. proto/plugin.proto  # 或任何目标语言
```
