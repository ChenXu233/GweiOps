# scripts/gen_grpc_stubs.py
"""从 proto/plugin.proto 生成 Python 桩。

生成物提交进仓库(engine/plugin_manager/grpc_proto/),理由和 contracts/openapi.json
一样:运行时不依赖 protoc,部署镜像里也不必装编译器。改了 proto 就必须重跑:

    python scripts/gen_grpc_stubs.py

protoc 生成的 `_grpc.py` 里写的是 `import plugin_pb2`,那是"平铺进 sys.path"的假设。
桩放在包内,必须改成相对导入,否则 `import engine.plugin_manager.grpc_proto...` 起不来。
桩生成在开发期执行,不在安装时执行。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "engine" / "plugin_manager" / "grpc_proto"
PROTOS = ("plugin.proto",)


def generate(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={out_dir}",
            f"--grpc_python_out={out_dir}",
            *[str(PROTO_DIR / name) for name in PROTOS],
        ],
        check=True,
    )
    return sorted(out_dir.glob("*.py"))


def patch_imports(out_dir: Path) -> None:
    """把 `import xxx_pb2` 改成 `from . import xxx_pb2`。"""
    for path in out_dir.glob("*_grpc.py"):
        text = path.read_text(encoding="utf-8")
        patched = re.sub(
            r"^import (\w+_pb2) as (\w+)$",
            r"from . import \1 as \2",
            text,
            flags=re.MULTILINE,
        )
        if patched != text:
            path.write_text(patched, encoding="utf-8")


def main(argv: list[str]) -> int:
    # --check:与仓库内已提交的生成物逐字节比对,用来在 CI 里抓"改了 proto 没重生成"
    check = "--check" in argv[1:]
    if check:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / "grpc_proto"
            generate(tmp_dir)
            patch_imports(tmp_dir)
            stale = [
                name.name
                for name in tmp_dir.glob("*.py")
                if not (OUT_DIR / name.name).exists()
                or (OUT_DIR / name.name).read_bytes() != name.read_bytes()
            ]
        if stale:
            print(f"::error::gRPC 桩与 proto 不一致:{', '.join(sorted(stale))}")
            print("   运行 python scripts/gen_grpc_stubs.py 后重新提交")
            return 1
        return 0

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    files = generate(OUT_DIR)
    patch_imports(OUT_DIR)
    (OUT_DIR / "__init__.py").write_text(
        '# engine/plugin_manager/grpc_proto\n'
        '"""protoc 生成的桩,不要手改。改动见 scripts/gen_grpc_stubs.py。"""\n',
        encoding="utf-8",
    )
    print(f"wrote {len(files)} file(s) into {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
