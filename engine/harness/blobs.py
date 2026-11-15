# engine/harness/blobs.py
"""把一次事故的工作区打包带走、再带回来。

远端沙箱里没有平台的文件系统:代码进去、改动出来都得走"一串字节"。这里只做
这一件事——把工作区压成 tar.gz,或者从 tar.gz 里挑出改动过的文件。谁搬这些
字节(平台直连 / 第三方存储 / 等等)是提供者的事。

为什么不是"两边各挂一份代码":沙箱里的那份才是这一场的事实。让远端自己 clone
一次,平台读回改动时对着的是另一个基线,"它到底改了什么"就没有答案了。
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from . import workspace as ws

# 一份代码的小时级上限。超过它的仓库不该走"整包搬来搬去"这条路——
# 那不是慢一点的问题,是每一场事故都要搬一遍。
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024

ARCHIVE_NAME = "workspace.tar.gz"
# 改动包的名字与 CNB 沙箱里那个键同名:一张包,两边都认。
CHANGES_ARCHIVE = "changes.tar.gz"


def pack(workspace: str | Path) -> bytes:
    """把工作区压成一个 tar.gz。解包方拿到的是解开后的树,不带顶层目录。"""

    root = Path(workspace)
    if not root.exists():
        raise ws.WorkspaceError(f"工作区不存在:{root}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for entry in sorted(root.iterdir()):
            # 平台自己的文件(任务书、报告、凭据)由提供者按需单独交进去,
            # 不跟着代码走一遍——否则换一个通道,凭据就又散了一次。
            if entry.name in ws.IGNORED_NAMES:
                continue
            tar.add(entry, arcname=entry.name, recursive=True)
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ws.WorkspaceError(
            f"这一场的代码有 {len(data) // 1024 // 1024} MB,超过整包搬运的上限 "
            f"{MAX_ARCHIVE_BYTES // 1024 // 1024} MB;这个仓库不适合整包进沙箱"
        )
    return data


def _extract_all(tar: tarfile.TarFile, root: Path) -> None:
    """解开一份包。`filter="data"` 是 3.12 起才有的默认值:更老的解释器要显式给。"""

    try:
        tar.extractall(root, filter="data")
    except TypeError:  # Python < 3.12
        tar.extractall(root)


def unpack(data: bytes, workspace: str | Path) -> Path:
    """在空目录里解开一份代码。只认相对路径:包来自别处,解包前不该相信它。"""

    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        _extract_all(tar, root)
    ws.open_up(root)
    return root


async def changes_archive(
    checkout_repo: Path, workspace: str | Path, paths: list[str] | None = None
) -> bytes:
    """只把改动过的文件打包带回。

    名单由平台对着基线算,不由沙箱自报:它说改过哪些文件是一句话,平台能算的
    是一份对照。读不动的文件(非 UTF-8、超大)也一起带上——那是"这里可能有问题"
    的线索,不是静默丢掉它的理由。
    """

    files = await ws.collect(checkout_repo, Path(workspace), paths)
    root = Path(workspace)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for item in files:
            path = str(item.get("path") or "")
            if not path:
                continue
            if item.get("delete"):
                # 删除用一个空条目标出来:字节流里没有"文件不存在"这种东西,
                # 没有这一条,解包方会把"删了"误读成"没动过"。
                info = tarfile.TarInfo(name=path)
                info.size = 0
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(b""))
                continue
            target = root / path
            if not target.is_file():
                continue
            tar.add(target, arcname=path, recursive=False)
    return buffer.getvalue()


def read_changes(data: bytes) -> list[dict[str, object]]:
    """把带回来的包读成提交能用的形状。空文件按删除算 —— 与 collect 同一个口径。"""

    out: list[dict[str, object]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            raw = handle.read()
            if not raw:
                out.append({"path": member.name, "delete": True})
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise ws.WorkspaceError(
                    f"{member.name} 不是 UTF-8 文本,这个出口只提交文本文件"
                ) from None
            if len(raw) > ws.MAX_FILE_BYTES:
                raise ws.WorkspaceError(
                    f"{member.name} 有 {len(raw) // 1024} KB,超过单文件上限 "
                    f"{ws.MAX_FILE_BYTES // 1024} KB;这种体积的改动该由人来做"
                )
            out.append({"path": member.name, "content": text})
    return out


__all__ = [
    "ARCHIVE_NAME",
    "CHANGES_ARCHIVE",
    "MAX_ARCHIVE_BYTES",
    "changes_archive",
    "pack",
    "read_changes",
    "unpack",
]
