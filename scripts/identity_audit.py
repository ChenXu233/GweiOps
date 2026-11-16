#!/usr/bin/env python3
"""一人多工作区:迁移审计清单。

    python scripts/identity_audit.py                 # 打出清单,待判定的在最前
    python scripts/identity_audit.py --json          # 同一份,机器读
    python scripts/identity_audit.py --check         # 有没结论的就非零退出

结论写在 `deploy/identity-merge.json`(不存在的文件 = 一条结论都没有):

    {
      "decisions": {
        "ops@example.com": {"verdict": "merged", "note": "同一人,两个团队都请了他"},
        "hr@example.com":  {"verdict": "kept",   "note": "两个部门的公共邮箱,已把 beta 那条改成 hr-beta@"}
      }
    }

判据只有一条:**每一组都有结论**(`merged` 或 `kept`)。可复跑:同一个库跑两遍
输出一样,结论也在里面。

这条命令连的是 `DATABASE_URL` 那一份库;读不到库时如实说读不到,不假装清单是空的
—— "空清单"与"没查"在验收上差得很远。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.identity import (  # noqa: E402
    apply_decisions,
    load_decisions,
    render_report,
    report,
)


async def _build(decisions_path: str) -> tuple[dict, str]:
    found = await report()
    plans = apply_decisions(found, load_decisions(decisions_path))
    return (
        {
            "groups": [row.to_dict() for row in plans.rows],
            "pending": [row.email for row in plans.pending],
            "complete": plans.complete,
        },
        render_report(plans),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同一邮箱撞两个工作区的那份清单")
    parser.add_argument("--decisions", default="deploy/identity-merge.json", help="结论文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--check", action="store_true", help="有没结论的就非零退出")
    args = parser.parse_args(argv)

    try:
        data, text = asyncio.run(_build(args.decisions))
    except Exception as exc:  # noqa: BLE001 - 连不上库是最常见的一种,要说人话
        print(f"读不到库,清单没有生成:{exc}", file=sys.stderr)
        return 2

    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else text)
    if args.check and not data["complete"]:
        print(f"\n还有 {len(data['pending'])} 组没有结论", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
