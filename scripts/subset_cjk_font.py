# scripts/subset_cjk_font.py
"""把中文字体裁到"这个站点真的用得到的字",产出一个几十 KB 的 woff2。

为什么不用现成的中文 webfont:Noto Sans SC 全量 woff2 约 4.6MB,
按 unicode-range 分片上站也要几百 KB。这个仓库的中文文案是静态的,
把源码里出现过的字抽出来单独子集化,通常只有几十 KB。

用法:

    python scripts/subset_cjk_font.py --source var/fonts/NotoSansSC.ttf

- --source 指向 Noto Sans SC 的可变字体(或任意 OFL 中文字体)。
  它不进仓库(17MB);产物进仓库,所以日常构建不需要它。
- 改了页面文案之后重跑一次,提交新的 woff2。
- 运行环境需要 fonttools + brotli:pip install fonttools brotli
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIRS = [
    ROOT / "frontend" / "apps" / "selfhost",
    ROOT / "frontend" / "packages" / "core",
]
OUT = ROOT / "frontend" / "apps" / "selfhost" / "public" / "fonts" / "gwei-sans-sc.woff2"

# 只收中文(含中文标点、全角符号);拉丁字母交给 Inter
CJK = re.compile(r"[\u2e80-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

ALWAYS = "·—…“”‘’《》〈〉「」『』【】〔〕、。，；：？！（）％＋－×÷＝"


def gb2312_level1() -> set[str]:
    """GB2312 一级汉字,3755 个。

    运行期才会出现的中文(议题标题、引擎写的 reason)预先扫不到,
    用这张标准表兜住:日常技术/运营文案的用字绝大部分落在里面。
    由编码表直接算出来,不联网、不会过期。
    """
    chars: set[str] = set()
    for high in range(0xB0, 0xD8):
        for low in range(0xA1, 0xFF):
            try:
                chars.add(bytes([high, low]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


def collect(scope: str = "common") -> set[str]:
    chars: set[str] = set()
    patterns = ("*.vue", "*.ts", "*.js", "*.css")
    for base in SRC_DIRS:
        for pattern in patterns:
            for path in base.rglob(pattern):
                if "node_modules" in path.parts or ".nuxt" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                chars.update(CJK.findall(text))
    if scope == "common":
        chars.update(gb2312_level1())
    chars.update(ch for ch in ALWAYS if CJK.match(ch))
    return chars


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="源字体路径(.ttf/.otf,可变字体也行)")
    parser.add_argument(
        "--scope",
        choices=("common", "used"),
        default="common",
        help="common=站内用字 + GB2312 一级字(默认);used=只收站内用字",
    )
    parser.add_argument(
        "--axis",
        default="400:600",
        help="可变字重的收窄区间,默认 400:600(界面只用这三档),传空则保留原轴",
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        print(f"找不到源字体: {source}", file=sys.stderr)
        return 2

    chars = collect(scope=args.scope)
    print(f"字符数: {len(chars)}(scope={args.scope})")

    # 可变轴先收窄:Noto Sans SC 是 100-900,界面只用 400/500/600,
    # 收窄后 gvar 小一大圈(235KB → 211KB)
    if args.axis:
        narrowed = ROOT / "var" / "fonts" / "_axis-narrowed.ttf"
        narrowed.parent.mkdir(parents=True, exist_ok=True)
        instance = subprocess.run(
            [
                sys.executable,
                "-m",
                "fontTools.varLib.instancer",
                str(source),
                f"wght={args.axis}",
                "-o",
                str(narrowed),
            ],
            capture_output=True,
            text=True,
        )
        if instance.returncode != 0:
            print(instance.stdout, instance.stderr, file=sys.stderr)
            return instance.returncode
        source = narrowed

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "fontTools.subset",
        str(source),
        f"--text={''.join(sorted(chars))}",
        f"--output-file={OUT}",
        "--flavor=woff2",
        # 保留可变字重轴:一个文件同时给 400 / 500 / 600
        # 中文用不到连字/字距调整,清空布局特性表能再省一点
        "--layout-features=",
        "--no-glyph-names",
        "--no-legacy-cmap",
        "--no-hinting",
        "--drop-tables+=DSIG",
        "--name-IDs=1,2,3,4,5,6",
        "--recalc-bounds",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr, file=sys.stderr)
        return result.returncode

    size = OUT.stat().st_size
    print(f"写出 {OUT.relative_to(ROOT)}: {size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())