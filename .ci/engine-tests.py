# .ci/engine-tests.py
"""引擎校验的判据:契约与迁移各再比一次,然后跑测试。

两件静态检查和 pytest 都跑在同一份已装好的依赖里,合进一条命令省一次
uv run 的启动开销。真的红了各自给出人话,不用退出码去猜是哪一件。

    python .ci/engine-tests.py              # 静态检查 + pytest
    python .ci/engine-tests.py --no-tests   # 只查静态的两件

`contracts/openapi.json` 单独再比一次,哪怕测试已红:测试红的时候人需要知道
契约是不是也漂了,否则修完测试还要再跑一轮才看见第二处。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dump_openapi import OUT, build

REGEN = "python scripts/dump_openapi.py"


def check_contract() -> bool:
    """仓库里的契约必须与 app 当前生成的逐字节一致。

    前端类型是从这个文件生成的,过期就等于前端拿到旧形状。比对口径必须与
    dump 的 serialization 一致,否则改一处响应模型会看到整份文件在 diff。
    """
    expected = json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if OUT.read_text(encoding="utf-8") == expected:
        return True

    print(f"::error::{OUT.relative_to(ROOT)} 与当前接口不一致")
    print(f"   运行 {REGEN} 后重新提交")
    return False


def check_migrations() -> bool:
    """迁移链必须是一条:一个 head,没有断成两支。

    alembic 的 heads 命令只在数据库连得上时才诚实(env.py 会去读配置),
    CI 里没有 Postgres。`ScriptDirectory` 读的是磁盘上的脚本,纯本地判断。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "engine" / "alembic.ini")))
    heads = script.get_heads()
    if len(heads) == 1:
        return True

    print(f"::error::迁移链的 head 不是一个: {heads or '(空)'}")
    return False


def main() -> int:
    checks = [("契约", check_contract), ("迁移", check_migrations)]
    failed = [name for name, fn in checks if not fn()]

    if "--no-tests" in sys.argv[1:]:
        return 1 if failed else 0

    tests = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=ROOT).returncode
    if tests != 0:
        failed.append("pytest")

    if failed:
        print(f"::error::校验没过: {'、'.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
