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

### 凭据从哪来

两条路,选一条:

1. **配在卷里**(上面第 3 步):dsh 自己管,平台不参与。换镜像也还在,但换机器要重配。
2. **从平台的环境里透传**:把同名变量设在 GweiOps 的 `.env`,命令里加 `-e NAME`。平台把整个进程环境交给那条命令,容器里就能读到。

第 2 条能不能生效取决于 dsh 认不认环境变量——这一点本仓库没有验证过,也不替它猜。凡是"某个下游怎么收凭据"的问题,答案在该下游自己的文档里,不在平台的配置里。

平台这一侧只保证一件事:凭据不进仓库、不进日志、不进事故报告。

## 接上平台

在 `.env` 里写一条命令就知道边界在哪:`{workspace}` 会替换成这一场事故的工作区。

```bash
HARNESS_COMMAND=docker run --rm -i \
  -v {workspace}:/data/workspace -w /data/workspace \
  -v gwei-dsh-home:/data/dsh-home \
  -v "$(pwd)/deploy/harness/plans:/opt/plans:ro" \
  -e DSH_PLAN=gwei \
  -e GWEI_EXIT_URL -e GWEI_TOKEN -e GWEI_REPORT -e GWEI_INCIDENT_ID -e GWEI_TENANT -e GWEI_BINDING \
  gwei-harness:local - < {workspace}/task.md
HARNESS_TOKEN=<从 API_TOKENS 里发一个给 harness 的令牌>
PLATFORM_BASE_URL=http://<平台地址>:8000
```

- `- < {workspace}/task.md`:任务从 stdin 进容器,避免把多行文本塞进命令行。
- `-e NAME` 不带值:把宿主环境里的同名变量透传进去,平台已经设好了。
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
