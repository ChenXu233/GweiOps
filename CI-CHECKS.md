# CI 校验

> 状态:现行 | 日期:2026-11-15
> 读者:提交 PR 的人、维护者
> 口径:只写当前 HEAD 的校验长什么样。为什么这么设计见本文各节的括注。

校验只有一处实现:`.cnb.yml` 末尾的校验作业,PR 与 master 推送都跑。
GitHub 上的 workflows 只构建镜像、部署、发 release,**不跑测试**。

## 跑什么

| 阶段 | 运行镜像 | 缺的工具谁装 | 命令 | 失败意味着 |
| --- | --- | --- | --- | --- |
| engine tests | `python:3.12` | `engine-tests.sh` 自己装 uv | `bash .ci/engine-tests.sh` | lock 与 `engine/pyproject.toml` 不一致,`contracts/openapi.json` 过期,迁移不是一条链(头不止一个、父版本指不到、revision 重复),`engine/plugin_manager/grpc_proto/` 与 `proto/` 不一致,或 `tests/` 有红 |
| web checks | `node:22` | `.cnb.yml` 里 `corepack prepare pnpm@10.15.0` | `bash .ci/web-checks.sh` | 前端构建失败,或 `vue-tsc` 报类型错 |

两段各用各的现成镜像,不现建校验镜像。`engine-tests.sh` 自带 uv 的安装(版本由
`UV_VERSION` 决定,默认 0.13.8),脚本因此能在干净的 `python:3.12` 里原样跑;
本地已有 uv 时跳过安装。uv 钉版本的理由和 lock 一样:解析规则一变,lock 可能整份重写。

装 uv 那一下带 curl 重试:这一段只有一次出网请求,构建节点到 astral.sh 的 TLS 偶发
中断,单发失败会让整阶段红,而重跑同一提交就绿。这类红与代码无关,因此不值得去看 diff。

`engine-tests.sh` 在 lock 与装依赖之后调 `.ci/engine-tests.py`:先比 `contracts/openapi.json`
是否与 `app.openapi()` 一致、再查迁移是不是一条链、再比 gRPC 桩,最后跑 `pytest tests/`。
比对是 `tests/test_integration/test_openapi_contract.py` 同一件事的重复断言;单拎出来
是因为跑静态检查只要一份装好的依赖,几十毫秒就能红,不必等整轮测试跑完。

两个脚本都能在本地原样跑,工作目录是仓库根:

```bash
bash .ci/engine-tests.sh
bash .ci/web-checks.sh
```

只查静态的三件(依赖已装好时):

```bash
python .ci/engine-tests.py --no-tests
```

前端要先 `pnpm install` 过一遍,否则 `bash .ci/web-checks.sh` 会在 `pnpm build:selfhost` 前重新装依赖。
uv 不在脚本里装,本地没有时先按 installer 装一份(见下方「复现 CI 环境」)。

## 接口契约也要一致

`contracts/openapi.json` 是前端类型的唯一来源,过期就意味着前端拿旧形状。
`.ci/engine-tests.py` 按 `scripts/dump_openapi.py` 同样的序列化逐字节比一次:

```bash
python scripts/dump_openapi.py                      # 改完响应模型就重跑
pnpm --filter @gwei/core gen:api                    # 前端类型跟着重生成
```

## 一人多工作区的审计清单

拆表之后,"同一个邮箱挂在两个工作区"这件事的结论在 `deploy/identity-merge.json`。
清单本身可以随时重跑:

```bash
python scripts/identity_audit.py            # 打出清单,待判定的在最前
python scripts/identity_audit.py --check    # 有没结论的就非零退出
```

`--check` **不接进 CI**:它依赖一份特定的库,而且判据是"人看过没有",不是"代码对不对"。
接成门禁只会让每次构建多一个与改动无关的红。

## 迁移也得是一条链

`engine/migrations/versions/` 里每个文件写一个 `revision`,用 `down_revision` 指向上一个。
`.ci/engine-tests.py` 读这个目录自己走一遍,判据是 `upgrade` 从根走到头会怎样:头必须唯一,
每个 `down_revision` 都得指得到,`revision` 不能重。两个头升级不知走哪条,父版本拼错的分支
永远升不上去。

校验读源码的顶层赋值,不 import 迁移文件、也不调 alembic CLI。不调 `alembic heads` 的理由在输出格式:
默认打印 `009 (head)`,没有 `Rev:` 前缀(`--verbose` 才有),按 `Rev:` 过滤只会数出 0 个头,
于是仓库什么状态都判失败。

**表定义只有一处**:核心的表由迁移建,不由应用的 `ensure_schema` 建。`ensure_schema`
留着只是 checkfirst 兜底(单测用内存/SQLite,不跑迁移)。两边各建一份的话,干净库
上跑 `alembic upgrade head` 会挂在 `relation ... does not exist`——而 CI 只检查
"是不是一条链",不建库,这个错到部署时才炸。所以新增表时先写迁移。

## gRPC 桩也要跟着 proto

`proto/plugin.proto` 是进程外插件的 wire 契约,桩生成后提交进仓库(`engine/plugin_manager/grpc_proto/`)——
运行时不依赖 protoc,部署镜像里也不必装编译器。桩过期不会立刻报错:远端插件照样注册得上,
只是调用时字段对不上。

改了 proto 就重跑:

```bash
python scripts/gen_grpc_stubs.py
```

判据由生成脚本自己给(`--check`):重新生成一份、逐字节比。

## Python 依赖是锁住的

`engine/uv.lock` 是 Python 依赖的唯一事实来源,CI 用 `uv sync --frozen` 按它装。

改了 `engine/pyproject.toml` 就必须重跑一次:

```bash
cd engine && uv lock
```

不跑会红。理由:`uv sync --frozen` 只按 lock 装包,**不比对** pyproject 与 lock,
不额外跑一次 `uv lock --check` 的话,漏锁的改动会用旧依赖测新代码,而且一路绿。

## 有一批用例默认跳过

`GWEI_TEST_DATABASE_URL` 为空时,需要真实 Postgres 的用例显式 skip。CI 不设这个变量,
所以日志里那句 `N skipped` 是设计的一部分,不是配置漏了。要跑它们:

```bash
GWEI_TEST_DATABASE_URL=postgresql+psycopg://... bash .ci/engine-tests.sh
```

## 复现 CI 环境

两段都是"现成镜像 + 一个脚本",本地等价于:

```bash
docker run --rm -v "$PWD":/workspace -w /workspace python:3.12 bash .ci/engine-tests.sh

docker run --rm -v "$PWD":/workspace -w /workspace node:22 \
  bash -c 'corepack enable && corepack prepare pnpm@10.15.0 --activate && bash .ci/web-checks.sh'
```

`engine-tests.sh` 自己装 uv,pnpm 由前面的 corepack 步骤备好——缺的工具都在命令里,
不用另记一步。

不现建校验镜像,是因为 `docker.build` 的 context 里只有 Dockerfile 本身:`COPY engine/...`
一律 `not found`,而报错只写 `failed to calculate checksum ... not found`,看不出是 context 的问题。
两段的工具链本来就不一样,分开反而更短。

一个本地差异:

- 本地宿主的全局 git 配置会带进来。开了 `commit.gpgsign` 又没有签名程序时,
  harness 工作区那批用例会挂在 `gpg failed to sign the data`。
  `test_workspace.py` / `test_sandbox.py` 的 `unsigned_git` fixture 已把签名关掉,
  所以只有 fixture 覆盖不到的地方才需要 `-e GIT_CONFIG_GLOBAL=/dev/null`。

## `.ci/Dockerfile` 这条路径不再使用

校验镜像已删,`.ci/Dockerfile`、`.ci/Dockerfile.dockerignore` 与仓库根的 `.dockerignore` 一并移除:
它们只服务 CI 里跑不通的 `docker.build` 目标。历史与原因见 `git log -- .ci/`,不在本文重述。
