# engine/workflows/release.py
"""合并即发布 —— PR 合入后把合并提交发布到下游。

发布和别的改动是同一种东西:一次效果 + 一条可撤销的承诺。平台不实现部署,
只把「发布哪个镜像」交给声明了 `compose.release` 的插件,把切换前的镜像记进
句柄,验证不过就部署回去。

触发只认一件事:PR 被合并。GitHub 上的 review/merge 是人做的审核;平台不替人
点合并,也不猜"什么时候算发布"。
"""

import json
import logging
import os
from string import Formatter

from dbos import DBOS

from engine.plugin_manager import registry
from engine.shared.config import config
from engine.workflows.pipeline import (
    apply_effects_on_binding_step,
    close_incident_step,
    declarative_report,
    open_incident_step,
    reply_binding,
    reply_on_topic_step,
)

logger = logging.getLogger(__name__)

RELEASE_CAPABILITY = "compose.release"

# 出厂默认:平台作者定的安全底线,随代码走。租户与仓库层只覆盖差异项。
FACTORY_DEFAULTS: dict[str, str] = {
    "mode": "off",  # 不配就不发布:发布是显式开启的能力,不是默认行为
    "project_dir": "",
    "service": "",
    "image_template": "",
    "binding": "local",
    "base_branch": "",
}

# mode 的词表:一条管道对应一个词。想加新形态,在这里登记并实现它,
# 不允许仓库配置里出现词表外的值——管道结构由平台定义,不由仓库拼装。
MODES = ("off", "compose")

# mode=compose 这条管道需要的参数。mode=off 时这些留空是合法状态。
_COMPOSE_REQUIRED = ("project_dir", "service", "image_template")

_ENV_NAMES = {
    "project_dir": "RELEASE_PROJECT_DIR",
    "service": "RELEASE_SERVICE",
    "image_template": "RELEASE_IMAGE_TEMPLATE",
    "binding": "RELEASE_BINDING",
    "base_branch": "RELEASE_BASE_BRANCH",
}

_RELEASE_SCOPE = "release"


def _env_layer() -> dict[str, str]:
    """部署默认:环境变量那一份,兼容今天的单项目形态。

    RELEASE_MODE 没显式配、但环境里出现了任一 compose 参数,就按 compose 算:
    已有部署升级到这份代码后行为不变;配了一半的部署报「缺哪几项」,
    而不是被出厂默认盖成一句「未开启发布」,让人以为配置没生效。
    """
    settings = config.settings
    values = {
        "project_dir": settings.release_project_dir,
        "service": settings.release_service,
        "image_template": settings.release_image_template,
        "binding": settings.release_binding,
        "base_branch": settings.release_base_branch,
    }
    mode = os.environ.get("RELEASE_MODE", "")
    if not mode and any(str(values[k]).strip() for k in _COMPOSE_REQUIRED):
        mode = "compose"
    return {"mode": mode, **values}


def _json_layer(tenant: str, key: str) -> dict[str, str]:
    """plugin_settings 里的一行:{租户, scope="release", key}。

    value 是一个 JSON 对象;解析失败按没配处理,报告里如实说,不让发布链崩掉。
    """
    raw = config.stored(_RELEASE_SCOPE, tenant).get(key, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): "" if v is None else str(v) for k, v in data.items()}


def resolve_release_config(tenant_slug: str = "", repo_full_name: str = "") -> dict:
    """按「出厂 → 部署环境 → 租户默认 → 仓库行」逐键合并出这个仓库的发布配置。

    高层覆盖低层;空串不算覆盖(留着低层的值),想让某键真正为空请显式写。
    """
    tenant_row = _json_layer(tenant_slug, "*") if tenant_slug else {}
    repo_row = _json_layer(tenant_slug, repo_full_name) if repo_full_name else {}
    env = _env_layer()

    merged = dict(FACTORY_DEFAULTS)
    for layer in (env, tenant_row, repo_row):
        merged.update({k: v for k, v in layer.items() if str(v).strip() != ""})
    return merged


def release_config(payload: dict | None = None) -> dict:
    """发布参数。缺项就是缺项,不拿默认值凑一个看似能用的部署。"""
    payload = payload or {}
    return resolve_release_config(
        tenant_slug=str(payload.get("tenant_slug") or ""),
        repo_full_name=str(payload.get("repo_full_name") or ""),
    )


def missing_release_config(values: dict) -> list[str]:
    """没配齐的发布参数,以环境变量名返回,方便照着补。"""
    if str(values.get("mode") or "") != "compose":
        return []
    return [
        _ENV_NAMES[key]
        for key in _COMPOSE_REQUIRED
        if not str(values.get(key, "")).strip()
    ]


def _template_fields(template: str) -> set[str]:
    """模板里用到的占位符名。写错了不等到 format 时才炸。"""
    return {
        field
        for _, field, _, _ in Formatter().parse(template)
        if field
    }


def release_skip_reason(payload: dict) -> str:
    """这次合并不该发布的原因;空串表示该发。

    返回原因而不是抛异常:配置写错也是这一场的结论,写进报告比让工作流崩掉好。
    """
    values = release_config(payload)
    where = str(payload.get("repo_full_name") or "") or "未指明仓库"

    mode = str(values.get("mode") or "")
    if mode not in MODES:
        return f"{where} 的发布模式 {mode!r} 不在支持列表 {MODES} 里,这次合并没有发布"
    if mode == "off":
        return f"{where} 未开启发布(mode=off),这次合并只记报告"

    missing = missing_release_config(values)
    if missing:
        return f"{where} 发布目标未配置,这次合并没有发布;缺:" + "、".join(missing)

    template = str(values["image_template"])
    try:
        fields = _template_fields(template)
    except ValueError:
        return f"{where} 的镜像模板不是合法模板,这次合并没有发布"
    unknown = fields - {"repo", "sha", "number"}
    if unknown:
        return (
            f"{where} 的镜像模板含不认识的占位符:"
            + "、".join(sorted(unknown))
            + ";这次合并没有发布"
        )

    base = str(payload.get("base_ref") or "")
    if values["base_branch"] and base != values["base_branch"]:
        return (
            f"合入基线是 {base or '?'},不是发布基线 {values['base_branch']};"
            "这次合并没有发布"
        )

    repo = str(payload.get("repo_full_name") or "")
    sha = str(payload.get("merge_sha") or "")
    if not repo or not sha:
        return "合并载荷缺少仓库或合并提交,这次合并没有发布"
    return ""


def build_release_intent(payload: dict) -> dict | None:
    """把一次合并翻译成发布意图。

    返回 None 表示这次不该发布(配置不全、模板写错、或合入的不是发布分支)——
    那不是错误,是这一场没有要做的改变。调用方据此如实写报告,而不是编一个效果出来。
    """
    if release_skip_reason(payload):
        return None

    values = release_config(payload)
    repo = str(payload.get("repo_full_name") or "")
    sha = str(payload.get("merge_sha") or "")
    number = payload.get("issue_number")

    # 镜像怎么由代码变成镜像,是下游 CI 的事;模板只负责把这次提交填进去。
    image = str(values["image_template"]).format(repo=repo, sha=sha, number=number)
    return {
        "version": 1,
        "summary": f"发布 {repo}#{number} 的合并提交 {sha[:12]}",
        "evidence": [{"kind": "pull_request", "ref": f"{repo}#{number}"}],
        "effects": [
            {
                "capability": RELEASE_CAPABILITY,
                "args": {
                    "project_dir": values["project_dir"],
                    "service": values["service"],
                    "image": image,
                },
            }
        ],
        "rationale": (
            "PR 已合并:把合并提交对应的镜像发布到下游;"
            "切换前的镜像记在句柄里,验证不过就部署回去。"
        ),
    }


def _can_reply(payload: dict) -> bool:
    """这个来源有没有声明 comment.create 的提供者。

    没有就不假装回话:把 GitLab 的仓库名发给 GitHub 适配器,要么 404 要么
    留到别的仓库上,两种都比不回更糟。
    """
    try:
        registry.effect_decl(
            "comment.create",
            tenant=str(payload.get("tenant_slug") or ""),
            binding=reply_binding(payload),
        )
    except LookupError:
        return False
    return True


def _nothing_to_do_report(payload: dict) -> dict:
    return {
        "source": "declarative",
        "summary": release_skip_reason(payload),
        "steps": [],
        "counts": {},
        "exhausted": False,
    }


async def _release_impl(payload: dict) -> dict:
    """工作流主体;抽出来是为了不启动 DBOS 也能测顺序与绑定。"""
    await open_incident_step(payload)

    intent = build_release_intent(payload)
    if intent is None:
        report = _nothing_to_do_report(payload)
        await close_incident_step(payload, report)
        return report

    values = release_config(payload)
    applied = await apply_effects_on_binding_step(intent, payload, values["binding"])
    report = declarative_report(intent, applied)
    await close_incident_step(payload, report)
    if _can_reply(payload):
        await reply_on_topic_step(payload, report, reply_binding(payload))
    return report


@DBOS.workflow()
async def release_workflow(payload: dict) -> dict:
    """PR 合并 → 发布效果 → 记账 → 在原 PR 上回一句结果。"""
    return await _release_impl(payload)
