# .ci/engine-tests.py
"""引擎校验的判据:契约、迁移、gRPC 桩各再比一次,然后跑测试。

两件静态检查和 pytest 都跑在同一份已装好的依赖里,合进一条命令省一次
uv run 的启动开销。真的红了各自给出人话,不用退出码去猜是哪一件。

    python .ci/engine-tests.py            # 静态检查 + pytest
    python .ci/engine-tests.py --no-tests # 只查静态的两件

迁移那条判据读的是 engine/migrations/versions/ 目录,不是 alembic 的搜索结果,
所以这条命令不启动 alembic:不需要 DSN,也不受迁移文件 import 什么影响。

`contracts/openapi.json` 单独再比一次,哪怕测试已红:测试红的时候人需要知道
契约是不是也漂了,否则修完测试还要再跑一轮才看见第二处。
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "engine" / "migrations" / "versions"

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


def check_grpc_stubs() -> bool:
    """仓库里的 gRPC 桩必须与 proto/ 当前内容一致。

    桩是提交进仓库的(运行时不依赖 protoc),所以它和 openapi.json 一样会过期。
    过期不会立刻报错:远端插件照样注册得上,只是调用时字段对不上——那是最难查的
    一类。这里用生成脚本自己的 --check,不另写一份判据。
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_grpc_stubs.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    print(result.stdout.strip() or "::error::gRPC 桩与 proto 不一致")
    return False


def read_revision(path: Path) -> tuple[str, tuple[str, ...]]:
    """取一个迁移文件的 (revision, down_revision)。

    只解析顶层赋值,不 import:迁移文件里的 `import sqlalchemy as sa` 会拉进整套
    依赖,而这件检查要能在报错信息里活下来。赋值可能带注解(`revision: str = "001"`),
    两种写法都读。
    """
    revision = ""
    down: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign):  # revision: str = "001"
            if node.value is None:
                continue
            node = ast.Assign(targets=[node.target], value=node.value)
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = getattr(node.targets[0], "id", "")
        if target == "revision" and isinstance(node.value, ast.Constant):
            revision = str(node.value.value)
        elif target == "down_revision":
            value = node.value
            if isinstance(value, ast.Constant):
                down = [str(value.value)] if value.value else []
            elif isinstance(value, (ast.Tuple, ast.List)):
                down = [str(e.value) for e in value.elts if isinstance(e, ast.Constant)]
    return revision, tuple(down)


def check_migrations() -> bool:
    """迁移得是一条链:头唯一,每个 down_revision 都指得到。

    判据是 upgrade 从根走到头会怎样:两个头升级不知走哪条,父节点拼错的那条永远
    升不上去,两份写同一个 revision 则谁盖谁看文件名。所以这里读目录自己走一遍,
    不靠 `alembic heads` 的输出格式。
    """
    revisions: dict[str, tuple[str, ...]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        revision, down = read_revision(path)
        if not revision:  # 文件缺 revision 时也得红,但要说清是缺这个字段
            print(f"::error::{path.name} 里读不出 revision")
            return False
        if revision in revisions:
            print(f"::error::revision {revision} 出现了两次")
            return False
        revisions[revision] = down

    parents = {parent for down in revisions.values() for parent in down}
    heads = sorted(rev for rev in revisions if rev not in parents)
    dangling = sorted(f"{rev} → {p}" for rev, down in revisions.items() for p in down if p not in revisions)
    if len(heads) == 1 and not dangling:
        return True

    print("::error::alembic 迁移头不是一个")
    print(f"   heads: {', '.join(heads) if heads else '无'}")
    if dangling:
        print(f"   down_revision 指向不存在的版本: {', '.join(dangling)}")
    return False


def main() -> int:
    checks = [
        ("契约", check_contract),
        ("迁移", check_migrations),
        ("gRPC 桩", check_grpc_stubs),
    ]
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
