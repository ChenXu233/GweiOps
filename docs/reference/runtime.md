# 运行时参考

> 状态:现行 | 日期:2026-11-16
> 读者:后端、运维
> 口径:基于当前代码;阈值与 TTL 为代码常量,改动时同步本文。

## 服务与端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| engine | 8000 | FastAPI;健康检查 `/api/health` |
| web | 3000 | Nuxt 3;开发时经 Nitro 同源代理 `/api/**` → engine |
| postgres | 5432 | pgvector/pgvector:pg16;业务表 + DBOS schema |
| redis | 6379 | 只承载可丢失的临时状态 |

## 工作流

| 工作流 | 触发 | 链路 |
| --- | --- | --- |
| `issue_triage_workflow` | issues opened/edited | Sensor 分析 → 落库 → `issue.triaged` Hook → `intent.propose` → 效果单元(回评,可撤销) |
| `fix_suggestion_workflow` | 评论含来源声明的触发词(GitHub 是 `@gwei`,CNB 是 `@CodeBuddy`) | 落库 → 配了 `HARNESS_COMMAND` 就整场交给 harness(它改工作区里的代码,效果仍从出口落成,通常是 `pr.open`),收口后在原话题上回一句结果;没配才退回 补丁建议 → `patch.generated` transform → `intent.propose` → 回评 |
| `release_workflow` | 任何来源的合并事件(GitHub PR / GitLab MR / CNB PR) | 合并提交 → 发布意图(`compose.release`)→ 指定下游的变更单元 → 来源支持回评时回帖 |
| `alert_triage_workflow` | 监控告警 firing | 归化信号 → 有 `incident.handle` 提供者就整场交给 agent,否则 `intent.propose` → 效果单元(没有补丁、没有回评) |
| `scheduled_scan_workflow` | 清单里声明的周期(DBOS 调度器) | 跑到点的能力 → 有结果就转成 `source=scan` 的信号交给 `alert_triage_workflow`;没结果就什么都不做 |

- 持久化:DBOS 状态在 Postgres 的 `dbos` schema;重启后未完成工作流从断点恢复。
- 队列:`gwei-agents`,`partition_concurrency=4`;入队必须带 `queue_partition_key=tenant_slug`(缺 key 会静默入队,幂等由 `SetWorkflowID` 兜底)。
- 事件与 Hook 调用放在 DBOS step 内,恢复重放不会重复执行。
- 周期巡检走 DBOS 自己的调度器,不在 `gwei-agents` 队列上:入队的定时执行不带分区键,调度与幂等由系统库里的 `sched-<调度名>-<点火时刻>` 保证。发现与校验规则见[插件系统](plugin-system.md#周期巡检)。
- 所有来源走同一个入口 `/webhook/<source>`,由各自的适配器验签并翻译:代码托管产事件,监控与巡检产信号。没有一家专用入口,也没有"默认来源"——没装适配器就是 503。
- 信号只说"哪里出了什么事",动作归 `intent.propose`;没有提供者时 effects 为空,不编动作。
- 回评往哪回、工作区里的代码从哪来,都按这条投递的 `source_adapter` 解析:CNB 的议题进来就回 CNB、拉 CNB 的仓库。载荷缺来源直接报错,不拿 GitHub 顶上。
- 效果执行以 `workflow_id:effects:effect:<n>` 为幂等键:重放只复用账本结论,不二次外呼。
- PR 上的评论与 issue 上的评论是同一种事件(`issue_comment`)。平台按话题 `owner/repo#number` 把它们串起来:同一个话题上已有打开的 PR 时,新改动追加到那个分支——`pr.open` 复用该 PR,不新开一个;分支上的 PR 已关闭则当场拒绝。

## 发布(合并即发布)

审核发生在来源侧:人看 PR/MR、合并。平台不替人点合并,只认来源适配器归一化出的 `kind="merge"`。GitHub 的 `pull_request`、GitLab 的 `merge_request`、CNB 的 `PullRequestEvent` 都在各自适配器里翻译,核心不认这些字段名。

- 每个仓库的发布配置按「出厂默认 → 部署环境变量 → 租户默认 → 仓库行」四层逐键合并,高层覆盖低层,空值不算覆盖。前两层是全局一份,后两层存在 plugin_settings(`scope="release"`):租户默认的 key 是 `*`,仓库行的 key 是 `owner/repo`,value 是一个 JSON 对象,形如:

  ```json
  {"mode": "compose", "binding": "prod-cluster", "project_dir": "/srv/api", "service": "api", "image_template": "ghcr.io/{repo}:{sha}", "base_branch": "main"}
  ```

- `mode` 是发布管道的选择,词表是 `off` / `compose`,只允许用平台定义过的模式,不允许仓库拼装自己的管道结构。`off` = 合并即终点,只记事故报告不发布(开源基础库形态);`compose` = 现有的 compose 发布管道。
- 环境层兼容旧部署:`RELEASE_MODE` 未显式配置、但环境里出现任一 compose 参数时按 `compose` 算;仓库行显式写 `mode: "off"` 可以关掉单个仓库的发布。
- `compose` 模式下三项配置缺一就不发布,不猜部署参数:`RELEASE_PROJECT_DIR`(compose 项目目录)、`RELEASE_SERVICE`(服务名)、`RELEASE_IMAGE_TEMPLATE`(支持 `{repo}` / `{sha}` / `{number}`)。缺项时这一场只写事故报告说明缺什么,不产生变更单元。
- `RELEASE_BASE_BRANCH` / `base_branch` 非空时只发布合入该基线的 PR;空 = 任意基线。
- 效果是 `compose.release`:把服务切到合并提交对应的镜像。compose 文件用 `${GWEI_RELEASE_IMAGE}` 取这次的目标镜像;插件先 `pull`,再 `up -d --no-deps`。**读当前镜像的 `compose ps` 也要带上这个变量**:不带 compose 连项目都解析不出来,报的是"没有 image"而不是"没在跑"。
- 撤销是把切换前的镜像部署回去。切换前镜像记在句柄里,读不到就不发布(没有撤销承诺的发布不进第一类路径);窗口是 `unbounded`,项目在就一直能撤。因此第一次发布之前,服务必须已经由 compose 跑起来一次——没有"切换前镜像",就没有可兑现的撤销。
- 验证读服务当前镜像:容器在跑、镜像与目标一致才算成;不一致走回滚。
- 发布效果打到的下游是 `binding` 参数(出厂默认 `local`,按层覆盖),不是部署默认的 `DEFAULT_BINDING`;两者要分别配。配置写法与层次语义见上。
- 租户默认与仓库行在控制台的「设置 → 发布配置」页面读写(`GET/PUT/DELETE /api/settings/release` 及其子路径);页面展示四层合并后的生效值兜底,留空不产生覆盖。也可以 API/SQL 直写 plugin_settings。
- 这不是金丝雀:一次发布就是一个单元、一步切换。分阶段发布见[工作分解](../plan/wbs.md)的「发布形态」。
- 来源适配器与新增来源的方式见[插件系统](plugin-system.md#webhook-适配器);回评只在来源适配器声明了 `comment.create` 时发生,没有就只写事故报告,不拿 GitHub 去回 GitLab 的仓库。
- 当前默认只启用 GitHub 适配器,合并触发因此只有 GitHub PR;GitLab MR 与 CNB 的适配器是预留位(`default_enabled: false`),打开后走同一条链路。

## MCP

别人的 agent(Claude Code、Cursor、dsh)用 MCP 说话;这台机器用出口改世界。两者要的是同一件事,所以 `/mcp` 不是第二套接口,是出口的另一种传输:

- `tools/list` 直接来自 `tool_specs(registry)` —— 插件声明过的效果就是工具,名字以 `.read` 结尾的能力是只读工具。没有第二份清单要维护。
- `tools/call` 走 `run_tool`,和沙箱里的 agent 完全一条路:读窗口、判定、执行、验证、记账。所以从 MCP 点一下,和从出口点一下,账本里长得一模一样。
- 一次调用可以带 `_summary` / `_incident_id` / `_topic` / `_binding` 这几个保留参数,它们只影响这一行账怎么写,不传给下游。

接入方式:URL 填 `https://<平台>/mcp`,请求头带 `X-Gwei-Token`,值是[密钥](#密钥)的明文。平台自己的只读口(账本、事故、话题)由内置插件 `platform-mcp` 声明,装上就出现在工具清单里。

### 工具按凭据暴露

同一个 `/mcp`,不同凭据看到的工具不一样。`tools/list` 列的是**这条凭据够得着**的工具,`tools/call` 也只放行那些:知道了名字不等于够得着。

一道凭据要过三关才看得见一个工具:**权限**够、**资源**够、自己的**工具白名单**没把它排除。

资源就是下游目标(`binding`):`local` 那台机器、`github` 那个组织。权限说"能不能改世界",资源说"能改哪一个"——一把只签了 `local` 的钥匙,`remote` 上的工具不在它的清单里。资源名由插件实例自己声明,平台不认识全集,所以密钥上的资源是"允许哪些出现过的",不是一份固定目录。密钥没写资源(空)就是不限,老密钥的行为不因这一栏改变;只读口说不出自己在哪个目标上,资源这一关对它不适用。

工具到权限的翻译只有一处(`engine/auth/keys.py` 的 `permission_for_tool`),判据按顺序取第一条:

| 工具 | 需要的权限 |
| --- | --- |
| `changes.read` / `incidents.read` / `topic.read` | `changes.read` |
| 其余的 `*.read` | `changes.read` |
| 其余的一切(声明过效果的能力) | `changes.execute` |

凭据分三种,各按各的说法筛:

| 凭据 | 谁在用 | 看到什么 |
| --- | --- | --- |
| 密钥(`gwei_` 前缀) | 外界的 agent | 它的权限集 ∩ 它自己的工具白名单(`tools`) |
| 静态令牌 | harness、alertmanager | `operate` 看全部,`read` 只看只读工具 |
| 会话 cookie | 浏览器里的人 | 角色算出来的权限 |
| 没有凭据 | 没配任何凭据的部署 | 不筛(单机自用) |

同一套判据也用在出口(`GET /api/agent/exits` 与 `POST /api/agent/exits/{name}`):清单同样收窄,调越界的工具是 403。

## 控制台助手

界面右下角那个悬浮窗里的助手。它不和 MCP 重复:同一个出口、同一本账,只是换成浏览器里的一句话,并且把"改世界"这一步摆到人面前。

```mermaid
flowchart LR
  UI["悬浮窗 AgentDock"] -->|"POST /api/console/session"| S["会话(进程内)"]
  UI -->|"POST …/turn (SSE)"| L["bub.core.Agent"]
  L -->|"工具调用"| C["engine/agent/console.py"]
  C -->|"只读口"| R["registry.run_capability"]
  C -->|"改世界:先问人"| P["待批调用"]
  P -->|"允许"| T["run_tool → 闸门 → 账本"]
```

- **循环交给 bub**:`bub.core.Agent` 负责推一版、执行工具、再看结果;`engine/agent/loop.py` 只把它的模型接口翻到 litellm,因此助手沿用引擎已有的 `LLM_*` 配置。
- **工具清单只有一份**:来自 `tool_specs(registry)`,与 `/mcp` 的 `tools/list` 同源;按会话身份过 `tool_visible` 三关后再由会话白名单收窄。
- **会话只能越用越窄**:开会话时给出去的权限不超过这个人手上的;改会话时同样。
- **允许**只对改世界的能力生效。一次对话的改动次数由 `MAX_ACTIONS` 收口,与租户级的出口小时上限(`AGENT_MAX_EXITS_PER_HOUR`)是两件事。

> 会话是进程内的对象:引擎重启或闲置 `SESSION_TTL_SECONDS` 之后,这一段对话就散了。它不是账本,不落库。

`/api/console/tools` 给的是这个身份**能授予**的工具全集,`POST /api/console/session` 里挑的就是它。

## 变更账本

- 后端:`CHANGE_LEDGER_BACKEND`。`db`(默认)写业务库 `change_events` 表,启动时 checkfirst 建表;`file` 写 `CHANGE_LEDGER_PATH`(默认 `var/change-ledger.jsonl`)的单文件 JSONL,仅用于演示与离线调试——并发追加与租户隔离都靠不住。
- 一行一个事件,只追加、不改写。顺序看自增主键,不看时间戳(机器时钟会回拨)。
- 一个单元判定、执行、放行、撤销各写一行,`unit_id` 相同;当前状态取 id 最大的那行。
- 查询按 `tenant` 收窄(`GET /api/changes?tenant=`)。配置了令牌时它由令牌决定,不是调用方说了算;未配置时它只是查询范围,见下节。
- 阻断的单元有两个出口,各写一行账:放行(`approve`)与否决(`veto`)。放行只表示"此刻有人在场",执行后照样读窗口、照样验证,真正不可逆的如实记成 `irreversible`。
- 撤销前置条件:最新行为已执行、有句柄,且窗口未过期。已撤销返回 409,未执行返回 400,提供者不可用返回 503;窗口过期或读不到窗口的撤销会被拒绝。窗口以写入时记下的值为准(对称撤销不会过期)。
- 响应里每行带 `undoable` / `undo_reason` / `undo_expires_at`:撤销承诺会到期,这个判断在读取时算,不落库。历史行按它自己那一刻算——它就是那一刻的当前状态。
- 放行前置条件:最新行为 `blocked`,否则 409。否决前置条件:最新行未执行,已执行的只能撤销。
- 幂等:同一 `idempotency_key` 重放只复用账本结论,不二次外呼。

## 权限目录

`engine/auth/__init__.py` 的 `PERMISSIONS` 是全部权限的唯一定义,角色、用户、密钥都从这里取。`is_write_permission` 判"这条会不会改世界",判据是一份只读白名单(`READ_PERMISSIONS`):新增只读权限要显式加进去,漏加的后果是被当成可写(保守那一侧),而不是悄悄放行。

| 权限 | 说明 |
| --- | --- |
| `changes.read` | 看变更账本、事故、话题 |
| `changes.execute` | 通过出口改世界(每次调用落成一个变更单元) |
| `changes.approve` | 放行被阻断的变更 |
| `changes.rollback` | 撤销已执行的变更 |
| `settings.read` / `settings.write` | 看配置 / 改配置与密钥 |
| `users.read` / `users.manage` | 看用户 / 增删用户、分配角色 |
| `roles.manage` | 增删角色、改角色权限 |
| `audit.read` | 看审计日志 |
| `plugins.read` | 看插件与能力 |
| `keys.read` / `keys.manage` | 看密钥清单 / 签发与吊销 |

预设角色 `owner` 拿全量;`operator` 能看账本、放行与撤销变更、读配置,并且能签发与吊销 MCP 密钥(`keys.read` + `keys.manage`),但拿不到管人、管角色的那两条;`viewer` 只有读,连密钥清单都看不到。三者权限都可以改,`is_system` 只保证删不掉。

`operator` 带 `keys.manage` 是有意的:运维要接一个 agent 时不该先去找所有者。越权的出口仍然关着 —— 签出去的权限不能超过自己手上那一份,所以运维能签的最多是他自己那一套。

## 控制台鉴权

`API_TOKENS` 留空 = 不鉴权:`by` 与 `tenant` 由调用方自报,只适合单机自用。每个响应都带 `X-Gwei-Auth: on|off`,把这个状态说出来——静默降级的安全开关不叫开关。

配置后按 `token:tenant:actor:scope` 签发,逗号分隔多条:

- `tenant` 写 `*` 表示不限租户(运维令牌);`scope` 取 `read` 或 `operate`(后者才能放行、否决、撤销)。
- 请求带 `X-Gwei-Token` 头。`/api/health` 与 `/webhook/*` 不走这套:前者是存活探测,后者各自带共享密钥。同一个头也接受[密钥](#密钥):先查库里的密钥,查不到再回落到静态令牌。
- 租户只能看到自己的账;请求里写别的租户是 403,不属于自己的单元是 404。
- `by` 以令牌为准,请求里的值不再被采信;放行的 `authorized_by`、否决的 `vetoed_by`、撤销的 `rolled_back_by` 都进账本。
- 令牌写错(段数不对、scope 非法、重复)拒绝启动:写错的令牌不能静默降级成"不鉴权"。

## 密钥

给外界的 agent 的凭据。与控制台令牌的区别是"是不是库里的对象":静态令牌写在 `API_TOKENS` 里,改一次要重启,一个部署就几条;密钥一把一个客户端,单独签发、单独吊销、各自带权限。

- 明文形如 `gwei_...`,只在**签发那一次**的响应里出现;库里只有 sha256 与 `hint`(前 9 位…后 4 位),列表永远不回显明文。
- 吊销立即生效:这把密钥的下一个请求就是 401,记录留着(谁签的、什么时候用过还看得见)。
- 权限是[权限目录](#权限目录)里的原子字符串,空白名单是"什么都没有",不是"全都有"。
- `tools` 是可选的白名单,在权限之上再收窄一层:权限够但这里没点名的工具不出现。
- `bindings` 是资源白名单:这把密钥能在哪些下游目标上动手。空 = 不限(与"权限为空"不同,那是"什么都不行")。
- `expires_at` 非空就按时失效;读不懂的到期时间在签发时就是 422,不存进去等运行期猜。
- 请求带一个看起来像密钥(`gwei_` 前缀)却查不到的串,当场 401——它不能落到"没配凭据就不鉴权"那一侧,否则吊销只是装饰。

密钥的资源从哪儿来:插件实例自己声明的 `binding`(`plugins/builtin/actions/docker-compose` 是 `local`,GitHub 适配器是 `github`)。平台不认识全集,所以页面上的资源是"这个部署里出现过哪些",不是一张允许清单。

密钥在控制台上:侧边导航「接入 → MCP 接入」(`/mcp`)。那一页按做这件事的顺序排:客户端填什么(地址与请求头,附一份可复制的客户端配置)、签一把(勾资源 × 勾权限 × 收窄工具,签发前就能看见对方会拿到哪些工具)、清单(谁签过、够得着什么、停不停,已吊销的折在下面)。权限、资源、工具三份清单全部来自引擎 —— 页面上显示的就是 `tools/list` 会给对方的。

密钥不进环境变量:签发自 `/api/keys`,存在业务库 `api_keys` 表(`CHANGE_LEDGER_BACKEND=file` 时落在 `var/api-keys.json`,只配演示与离线调试)。
密钥本身不是"鉴权开关":一个既没有 `API_TOKENS` 也没有用户的部署仍然是不鉴权的(单机自用),密钥只是让拿它的人成为某个身份。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/keys` | 密钥清单,需要 `keys.read`;不含明文,含明文永不回显的 `hint` 与 `status` |
| GET | `/api/keys/resources` | 这个部署里的资源(下游目标)与各目标上的能力,需要 `keys.read` |
| GET | `/api/keys/tools` | 可授予的工具:要什么权限、能作用在哪些资源上,需要 `keys.read` |
| POST | `/api/keys` | 签发,需要 `keys.manage`;响应里带一次明文 |
| DELETE | `/api/keys/{id}` | 吊销,需要 `keys.manage`;记录留着 |

两条红线在代码里,不靠界面提示:签出去的权限不能超过自己手上的(没有 `settings.write` 的人签不出 `settings.write`);密钥的租户取自签发人,调用时盖过工具参数里的 `tenant`。

## 出口

沙箱里的 agent 唯一能改变外部世界的地方。两件事:问清单,走一次。

- 清单来自各插件声明过的效果;名字以 `.read` 结尾的能力是只读口,其余不能调。
- **每次改世界的调用都是一个变更单元**:读窗口、判定、执行、验证、记账,和人工操作走同一条闸门。只读调用不落账。
- 参数 `call_id` 带上时,同一次调用重发只复用账本里的结论,不二次外呼;不带就当两次调用,老实做两次。
- 参数 `binding` 缺省取 `default_binding`。绑错目标不是结论,是配置错误:拒绝执行,不留账本行。
- 参数 `incident_id` 把这次事故的所有变更串在一起,早上可以用 `GET /api/changes?incident=` 一次捞出来。`call_id` 只在同一次事故里有意义:换一次事故,同样的编号就是另一件事。
- `actor` 取自[控制台令牌](#控制台鉴权),写进单元的 `intent.by` 与 `intent.via=exit`。
- 声明里带 `files` 的效果(`pr.open`),`files` 可以不由 agent 给:平台按 `incident_id` 找到这一场的工作区,把 agent 改过的文件读成 `[{path, content}]`,删掉的给 `{path, delete: true}`。`paths` 只用来收窄到其中几个路径。读不出来(没有仓库副本、非 UTF-8、单文件超过 512 KB、改动超过 100 个文件)时这次调用直接失败并说明原因,不拿空改动去开 PR。
- 次数上限 `AGENT_MAX_EXITS_PER_HOUR`(默认 20,0 = 不限)按租户统计最近一小时的出口变更。循环搬进沙箱后平台看不到"它在想第几步",只数得清"它已经点了几次"——超了返回 429,由人接手。

## Harness

外部 agent 在**自己的沙箱**里处理一次事故,平台只负责交进去、收回来。

- `HARNESS_COMMAND` 是启动命令,`{workspace}` 会替换成沙箱里这一场的目录。留空 = 不用外部 harness,回落到进程内的 `operator`,再回落到声明式路径。
- `SANDBOX` 决定它**在哪跑**,三选一,换地方不改上面那条命令:

  | 值 | 边界 | 代码怎么进去 |
  | --- | --- | --- |
  | `local`(默认) | 本机进程;隔离靠命令自己(`docker run` / `ssh box`) | 直接写进工作区 |
  | `cnb` | CNB 托管执行面,一次 `api_trigger` 构建 | 整包交上去,改动只带回来 |
  | `ssh` | 一个常开的会话(例如云原生开发环境) | `scp` 上去 |

- **工作区里有代码**:载荷带仓库时,平台用 App 安装令牌取一份快照——走 API 的 tarball 端点(`api.github.com`),不走 `git clone`:`github.com` 在有些网络里连不上,API 通常还行,而且这条路不在命令行里带凭据。快照解开后在 `.repos/<incident_id>` 里变成一个本地提交,再把文件铺进工作区并放开到其他用户可写(引擎与 harness 镜像的 uid 不同)。容器看到的没有 `.git`:提交、分支、PR 由平台做,容器里没有可用的 git 凭据。拉不到代码时这一场不开工,报告直接写原因。
- 交进去:工作区里的 `task.md`(信号、仓库与基线分支、出口地址**与认证方式**、报告路径),以及环境变量 `GWEI_EXIT_URL`、`GWEI_TOKEN`、`GWEI_INCIDENT_ID`、`GWEI_REPORT`、`GWEI_TENANT`、`GWEI_BINDING`。
- **凭据由平台注入**:存进 `harness-env` scope 的每个键(`PUT /api/settings/scopes/harness-env`)都以大写形式进入引擎进程的环境变量,并额外写成沙箱里的 `.harness-env`(0600,不进工作区改动)。`docker run` 只转发被点名的变量,所以命令里要么逐个 `-e NAME`,要么 `--env-file {workspace}/.harness-env` 一次带进去 —— 用后者,新加的键才不用改命令。已知键(`deepseek_api_key`、`deepseek_base_url`、`model`)在模型里声明了类型与形状,写错在写入时就是 422;控制台「设置 → 接入与密钥」写的就是这个 scope,密钥永不回显。
- 收回来:沙箱里的 `report.json`(`summary` / `steps` / `counts` / `exhausted`),写进[事故](#事故)报告。没交报告也算有报告——退出码与最后几行输出带回去;超时的标 `exhausted`。
- **改了什么由平台数**:工作区对着基线比一遍,结果写进报告里的 `diff`;沙箱自报的改动不进 PR。
- 报告里带 `sandbox`:`{provider, id, url}` 就是这一场跑在哪。`cnb` 给的是构建号与构建页地址;`local` 给的是进程号。
- 它改世界仍然只能走[出口](#出口),所以变更、账本、可撤销性和进程内 agent 完全一样。
- `dsh` 这类 harness 自带一次任务一次退出的入口(`dsh --profile headless "<task>"`);平台不认识它,只认那条命令。可直接用的那条命令与对应镜像见 [deploy/harness](../../deploy/harness/README.md)。

## 事故

一次事故 = 一个 `incident_id`(取工作流 id)+ 一行报告。告警工作流开始写一行 `open`,收尾改写同一行。

- `status` 停在 `open` 说明那一场开了没收口——它卡住了,不是"什么都没发生"。
- 报告形状:`summary` / `steps` / `counts` / `exhausted` / `source`(`agent` 或 `declarative`)。外部 harness 回来照同一形状交。
- 变更与事故分开存:账本说哪几处被改了,事故说整场怎么了。两者用 `GET /api/changes?incident=` 串起来。
- 后端与账本同一个开关:`file` 时报告落在账本文件同目录的 `incidents.jsonl`。

## 租户

- webhook payload 顶层携带 `tenant_slug`;当前取 `settings.default_tenant_slug`(默认 `default`)。
- `projects` 唯一约束 `(tenant_id, github_id)`;`issues` 唯一约束 `(project_id, github_id)`。
- 每租户的凭据、队列分区、模型用量都按 `tenant_slug` 归属。

## Redis

- 只承载可丢失状态;Redis 故障时降级放行,不阻塞主链路。
- webhook 去重:`gwei:{tenant_slug}:webhook-dedup:{delivery_id}`,TTL 6 小时。信号按 `ref + occurrence` 去重(Alertmanager 就是 `fingerprint + startsAt`),键 `gwei:{tenant_slug}:signal-dedup:{...}`。
- LLM 分析缓存:内容哈希键(前缀 `gwei:`),TTL 24 小时;失败文案不写缓存。
- 幂等兜底始终是 DBOS workflow ID,不是 Redis。

## LLM 与计量

- `engine/llm/client.py` 经 LiteLLM 调用;重试 3 次,指数退避。
- 指标:`gwei_llm_calls_total{model}`、`gwei_llm_tokens_total{model}`、`gwei_llm_call_duration_seconds{model}`。
- AgentSession 的 state 记录 `llm_tokens`,作为计费聚合源。

## 部署模式

- 前端档位:`NUXT_PUBLIC_DEPLOYMENT_MODE`,取值 `selfhost`(默认)或 `saas`。
- 页面用 `definePageMeta({ modes: [...] })` 声明可见档位;`middleware/mode.global.ts` 对不匹配的路由重定向 `/dashboard`;布局按 `modes` 过滤导航。
- 后端 `Settings.deployment_mode` 默认 `saas`,与前端档位目前是两个独立字段,没有强制校验对齐。部署时分别设置。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/board` | 议题板:三段(等我 / 在跑 / 落了)与三个数,首页就是它 |
| GET | `/api/issues/{id}/timeline` | 议题时间线:三个状态 + 各轮次的分段证据(见下) |
| POST | `/api/issues/{id}/continue` | 接着这条线再改一轮:与 `@gwei` 评论同一条工作流,分支沿用、PR 不新开 |
| GET | `/api/repos` | 仓库列表 |
| GET | `/api/settings` | 设置(脱敏) |
| GET | `/api/settings/scopes` | 插件声明的配置项:要填什么、填了没有、缺什么(不回显值) |
| PUT | `/api/settings/scopes/{scope}` | 写一组配置值,存业务库并立即生效 |
| DELETE | `/api/settings/scopes/{scope}/{key}` | 删掉一个键;删的是调用方租户那一份,读的时候落回公共值 |
| GET | `/api/plugins`、`/api/plugins/widgets` | 插件清单 / 插槽声明 |
| GET | `/api/metrics` | 指标快照 |
| GET | `/api/changes` | 变更账本当前状态(按单元折叠,可按 verdict / binding / incident 过滤) |
| GET | `/api/changes/{id}` | 单个单元的全部事件(执行与撤销) |
| POST | `/api/changes/{id}/rollback` | 撤销已执行的单元,并追加一行审计 |
| POST | `/api/changes/{id}/approve` | 放行一个阻断的单元,执行后照样读窗口与验证 |
| POST | `/api/changes/{id}/veto` | 不做这次变更,追加一行否决 |
| GET | `/api/incidents`、`/api/incidents/{id}` | 事故列表 / 单场事故的经过与结论 |
| GET | `/api/agent/exits` | 出口清单:沙箱里的 agent 能改什么、每个动作的参数名 |
| POST | `/api/agent/exits/{name}` | 走一次出口;改世界的调用落成一个变更单元 |
| GET | `/api/plugins/{name}/ui/{path}` | 插件 iframe 资产 |
| POST | `/mcp` | MCP(streamable HTTP):`tools/list` 是按凭据收窄的出口清单,`tools/call` 就是走一次出口;需令牌或密钥 |
| GET | `/mcp` | 这个端点是什么、这条凭据看得到哪些工具、它是什么身份 |
| GET | `/api/keys` | 密钥清单(不含明文),需 `keys.read` |
| POST | `/api/console/session` | 开一个助手会话;权限与资源不超过调用者自己的,需 `changes.read` |
| GET | `/api/console/session/{id}` | 会话此刻的形状:手上的权限、已用改动次数、看得见的工具 |
| PATCH | `/api/console/session/{id}` | 收窄权限 / 资源 / 工具白名单,或开关"改世界先问我" |
| DELETE | `/api/console/session/{id}` | 关掉这个会话(进程内的对象随之消失) |
| GET | `/api/console/session/{id}/tools` | 这个会话此刻看得见的工具 |
| GET | `/api/console/session/{id}/pending` | 正在等允许的那一次改世界调用,没有就是 `null` |
| POST | `/api/console/session/{id}/pending/{call_id}` | 点允许或不允许,需 `changes.execute` |
| POST | `/api/console/session/{id}/turn` | 说一句话,拿回 `text/event-stream`(delta / tool / tool_result / error / done) |
| GET | `/api/console/tools` | 这个身份能给助手用的工具全集(开面板时挑的就是它) |
| POST | `/api/keys` | 签发密钥,明文只在这里出现一次,需 `keys.manage` |
| DELETE | `/api/keys/{key_id}` | 吊销:记录留着,之后每个请求都是 401 |
| POST | `/webhook/{source}` | 任何来源的投递:按 `source` 找声明了 `webhook.receive` 的适配器,由它验签并翻译;没装适配器或适配器没配密钥返回 503 |
| POST | `/webhook/github/comment` | GitHub 评论事件的专用别名 |

### 议题时间线

`GET /api/issues/{id}/timeline` 把一个议题的全部证据排成一条线:信号、诊断、意图、
变更、验证、结论;一轮就是一次执行。聚合在 `engine/change_unit/timeline.py` 里做
(纯函数,喂字典就能测),接口只取数。设计与界面约定见[议题工作台](../explanation/issue-workspace.md)。

- **三个状态**(`state`):`waiting` / `running` / `landed`。七种结论的原词只留在
  账本页,这里不再出现。优先级就是"谁在拦着":`blocked` 或 `unknown` 是等人;
  事故开着没收口也算等人——它可能卡住了,而卡住不是"在跑";没有任何变更时才看
  issue 自己的状态,因为平台从不改 `issues.status`,它一直是 OPEN。
- **一段两层**:`summary` 一句人话,`detail` 是工程决策要点(理由、候选、参数、
  能不能撤),常驻不折叠;`evidence` 是存下来的原文,默认收起。原文不加工,
  截断了 `truncated` 为真。
- **轮次带 diff**:`rounds[].diff` 是这一轮改了哪些文件、各增删多少行。行数由
  平台在 harness 收工后从工作区数(`workspace.diff_stat`),不是 agent 自报——
  自报的东西没法核。跨轮合并由读的人按路径累加。
- **为什么没做、查了什么**:`intent.detail.not_executed` 带理由(工作流在建单元
  之前写进 `intent.skipped`,那一刻才知道有没有提供者、有没有被扩展点拦下);
  `verify.detail.rules` 是插件声明里的 `{query, expect}`,随单元落账。
- **一个候选都没落下的一轮**:没有单元可读,意图记在事故的 `intent` 上,时间线
  据此给一段"本打算做什么、为什么都没做",而不是只剩信号与诊断。
- **一个变更属于哪个议题**:`intent.topic`(agent 从出口进来的变更自己记),
  或者 `incident_id` 落在该议题某次执行上。两条路都认。
- **没有变更也返回**:`rounds` 为空数组,不是 404——"还没发生"与"查不到"要分得开。
- 账本与事故各只扫最近的 `LEDGER_SCAN` / `INCIDENT_SCAN` 条,超了把 `truncated`
  置真,不假装全看过了。
- 同一条判定也服务 `GET /api/board`(首页那张列表):列表说"在跑"、点进去说
  "落了"是最难查的一类 bug,所以两处共用 `normalize_state`,不各写一份。
- **继续改**是 `POST /api/issues/{id}/continue`(`{"instruction": "..."}`,≤500 字):
  它把人的一句话排成一轮 `fix_suggestion_workflow`——和人在 GitHub 上 `@gwei`
  走同一条路,所以"接着哪个分支改"由同一个 `_thread_for` 决定,不在这里另判。
  人说的话进 signal,事故把它记下来,于是它就是时间线上的一个新轮次。
  权限借用 `changes.approve`:两件事是一类——此刻有人在场,允许平台再动一次手。

### 接口契约

响应模型写在 `engine/api/schemas.py`,FastAPI 据此生成 OpenAPI;前端类型不手抄,从这个文件生成。

| 步骤 | 命令 | 产物 |
| --- | --- | --- |
| 导出契约 | `python scripts/dump_openapi.py` | `contracts/openapi.json` |
| 生成前端类型 | `pnpm --filter @gwei/core gen:api` | `frontend/packages/core/api/schema.d.ts` |

- 前端调用点统一走 `frontend/packages/core/api/typed.ts`:路径、路径参数、响应体都由 `paths` 推出,新增端点不用再写一遍泛型。
- `frontend/packages/core/types/*` 是 schema 里 DTO 的别名,字段与后端同源;类型名对不上时 `vue-tsc` 直接报错。
- 改响应模型后两个命令都要重跑;`tests/test_integration/test_openapi_contract.py` 会在 `contracts/openapi.json` 过期时报错(不需要 Postgres)。

## 插件

清单、注册表、事件总线、Hook、UI 插槽与配置见 [插件系统](plugin-system.md)。