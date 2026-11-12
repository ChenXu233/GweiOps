# 值班 harness

把一次事故交给跑在容器里的 agent:上面是 [oh-my-dsh-pack](https://github.com/ChenXu233/oh-my-dsh-pack) 的 `headless` 方向,平台这边只负责交进去、收回来。

## 它长什么样

```
GweiOps  ──写工作区、起容器──▶  容器: dsh --profile headless
    ▲                                   │
    │                                   │ 只能通过出口改世界
    └────────  GET/POST /api/agent/exits ┘
```

容器里没有生产凭据。它想改生产,只能调出口,而出口每一次调用都会经过平台的窗口判定与记账。

## 准备一次

镜像里已经装好 dsh 与 git;模型凭据和会话存在 `dsh-home` 卷里,配一次就一直用。

```bash
# 1. 镜像(来自 oh-my-dsh-pack 的构建产物,或本地构建)
docker build -t gwei-harness:local /path/to/oh-my-dsh-pack

# 2. 卷:模型凭据与 dsh 家目录
docker volume create gwei-dsh-home

# 3. 先把凭据放进卷里(进一次容器,按 dsh 的方式配一次)
docker run --rm -it -v gwei-dsh-home:/data/dsh-home --entrypoint sh gwei-harness:local
```

### 凭据:由平台注入,不进卷

凭据存在 GweiOps 的业务库里,每次起容器时以大写环境变量注入 —— 不需要第二步那个交互式配置,换机器也不用重配。

```bash
curl -X PUT http://<平台>/api/settings/scopes/harness-env \
  -H "X-Gwei-Token: <operate 令牌>" -H "Content-Type: application/json" \
  -d '{"values": {"deepseek_api_key": "…", "dsh_model": "…"}}'
```

存进去的 `deepseek_api_key` 会变成引擎进程环境里的 `DEEPSEEK_API_KEY`,其余同理(键名大写),整份键值同时落在工作区的 `.harness-env`(0600)。

`docker run` 只转发被点名的变量,所以命令里用 `--env-file {workspace}/.harness-env` 一次带进去 —— 新加一个键不用改命令;要指名也可以用 `-e NAME`。

容器认不认这个变量名,是 harness 的事,平台不替它猜;平台只保证值从库里来、按大写注入、进得了容器、不进日志也不进报告。

## 接上平台

在 `.env` 里写一条命令就知道边界在哪:`{workspace}` 会替换成这一场事故的工作区。

```bash
HARNESS_COMMAND=docker run --rm -i \
  -v {workspace}:/data/workspace -w /data/workspace \
  -v gwei-dsh-home:/data/dsh-home \
  -v "$(pwd)/deploy/harness/plans:/opt/plans:ro" \
  -e DSH_PLAN=gwei \
  --env-file {workspace}/.harness-env \
  gwei-harness:local - < {workspace}/task.md
HARNESS_TOKEN=<从 API_TOKENS 里发一个给 harness 的令牌>
PLATFORM_BASE_URL=http://<平台地址>:8000
```

- `- < {workspace}/task.md`:任务从 stdin 进容器,避免把多行文本塞进命令行。
- `--env-file`:平台把这一场的环境变量(出口地址、令牌、`harness-env` 里的键)写在 `.harness-env` 里,一次带进容器。这个文件属于平台,不进工作区的改动。
- 想让它跑在别处,把 `docker run …` 换成 `ssh box …` 就行,平台那边一行不改。

## 验一下

```bash
# 手动跑一次,确认容器能起来、能读到任务
docker run --rm -i -v "$PWD/tmp-ws:/data/workspace" -w /data/workspace \
  -v "$PWD/deploy/harness/plans:/opt/plans:ro" -e DSH_PLAN=gwei \
  gwei-harness:local - <<'EOF'
用一句话说明你看到了什么,然后退出。
EOF
```

报告没写出来时平台不会装作成功:退出码与最后几行输出会进事故报告,超时的标 `exhausted`。

## 边界

这条命令决定隔离强度,平台不替你决定:

| 命令 | 边界 |
| --- | --- |
| `docker run --rm …` | 独立文件系统与进程空间,同内核;容器丢弃即无痕 |
| `docker run --rm --network none …` | 再加上断网(出口也就断了,一般不要) |
| `ssh box …` | 另一台机器;最接近"不和宿主机跑在一起" |

不管哪种,容器里都不该有生产凭据——它要改生产,只能走出口。
