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

# 运行期才会出现的中文(议题标题、引擎返回的 reason)不在源码里,
# 所以补一批高频字兜底,减少同一条句子里两种字体的概率。
FALLBACK_TEXT = (
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经"
    "十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞"
    "待放行变更账本议题仓库插件设置控制室信号源执行记录指标观测节点集群滚动回滚阻断放量窗口观测验证撤消撤销重试失败成功等待超时"
    "秒分钟小时天周月年今日昨夜凌晨刚才最近全部加载中刷新读取错误警告提示说明注意暂无数据空状态"
)
ALWAYS = "·—…“”‘’《》〈〉「」『』【】〔〕、。，；：？！（）％＋－×÷＝"


def collect() -> set[str]:
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
    chars.update(CJK.findall(FALLBACK_TEXT))
    chars.update(ch for ch in ALWAYS if CJK.match(ch))
    return chars


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="源字体路径(.ttf/.otf,可变字体也行)")
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

    chars = collect()
    print(f"字符数: {len(chars)}")

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
        "--layout-features=kern",
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