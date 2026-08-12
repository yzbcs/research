#!/usr/bin/env python3
"""Refresh arxiv_idea_atlas.html from the cached study digest archive.

The visual shell, category research frames, and curated category assignments
are preserved from the existing atlas. Paper records, counts, recent signals,
summaries, date metadata, and the current curated Idea Lab bridge bundle are
rebuilt from the live archive cache produced by
build_arxiv_daily_classified.py --fetch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import build_arxiv_daily_classified as classified


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATLAS = ROOT / "arxiv_idea_atlas.html"
DEFAULT_DAILY_DIR = ROOT / "assets" / "input" / "study_digests" / "daily_html_all"
DATA_RE = re.compile(
    r'(<script type="application/json" id="arxivIdeaAtlasData">)(.*?)(</script>)',
    re.S,
)


CURATED_BRIDGES = [
    {
        "cats": [5, 0],
        "title": "把技能复用从文档规范推进到运行时契约",
        "thesis": "将大规模技能文件中暴露的可复用性缺口转成运行时前置条件、后置条件与失败诊断，让技能被检索后仍需通过可执行契约。",
        "test": "从 138K 技能语料抽取高频缺陷，在跨任务技能复用基准上比较纯文本检索、静态规范检查与运行时保障，报告成功率、误拒率和修复成本。",
        "risk": "技能语料中的格式缺陷未必导致真实执行失败，需要用可运行任务建立缺陷到失效的因果对应。",
        "papers": ["2608.08453", "2608.09253", "2608.05695"],
    },
    {
        "cats": [2, 6],
        "title": "用轨迹归因决定长时记忆何时写入",
        "thesis": "把长时轨迹中的关键决策归因转成情景记忆的写入权重，只保留对最终成败有可验证贡献的计划与经验。",
        "test": "在软件问题解决任务中比较全量记忆、相似度记忆与归因加权记忆，测量长程成功率、污染率、检索开销和错误恢复时间。",
        "risk": "离线归因可能利用终局信息，在线版本必须单独报告可用信号和性能差距。",
        "papers": ["2608.06663", "2608.06811", "2608.06909"],
    },
    {
        "cats": [2, 5],
        "title": "用执行效用而非相关性决定技能调用",
        "thesis": "把预算、技能执行成功概率与预期收益联合进门控器，使 Agent 在技能相关但不值得执行时主动跳过。",
        "test": "在固定时间和调用成本下比较相关性检索、奖励感知门控与预言机门控，报告任务效用、技能浪费率及评审器一致性。",
        "risk": "训练奖励可能只拟合特定评审器，需要跨 judge 与人工样本复核执行效用。",
        "papers": ["2608.05519", "2608.09168", "2608.05573"],
    },
    {
        "cats": [0, 4],
        "title": "把 MCP 身份边界接入风险感知执行模型",
        "thesis": "认证网关先给出主体与委托链，风险世界模型再依据动作后果决定放行，从身份正确扩展到执行安全。",
        "test": "构造用户、服务账号与委托身份混合的 MCP 任务，对比仅认证、仅运行时护栏和联合方案的完成率、越权率与额外延迟。",
        "risk": "红队覆盖不足会夸大联合方案效果，需要按身份错误、工具误用和环境后果分层报告。",
        "papers": ["2608.10760", "2608.05695", "2608.10669"],
    },
    {
        "cats": [6, 8],
        "title": "把经验树更新变成因果可回退的自进化",
        "thesis": "用因果修复证据约束经验树和文本梯度更新，只有能稳定改善后续任务的经验才进入长期层级。",
        "test": "注入误导反馈与分布转移，比较无门控经验树、相似度门控和因果门控，测量持续收益、负迁移与回退成功率。",
        "risk": "因果判断本身可能依赖昂贵反事实执行，应同时报告额外样本与工具成本。",
        "papers": ["2608.09044", "2608.05906", "2608.07449"],
    },
    {
        "cats": [3, 13],
        "title": "组织分工何时掩盖偏见与治理失败",
        "thesis": "将层级角色、审计容量和情绪状态视为同一组织控制面，定位多 Agent 分工是在纠偏还是把偏见分散到不可见环节。",
        "test": "在资源分配与谈判任务中控制层级、通信图和审计预算，报告群体效用、偏见、责任可定位性与从众错误。",
        "risk": "提示诱发情绪只代表可观测语言状态，结论应限制在行为与组织结果层。",
        "papers": ["2608.06949", "2608.09574", "2608.06922"],
    },
    {
        "cats": [1, 4],
        "title": "从工具选择诊断闭环到离线 API 自探索",
        "thesis": "用 canary 工具定位选择推理缺陷，再把根因反馈给离线 API 探索器，形成无需在线试错的工具能力修复闭环。",
        "test": "在 API 变体与微服务故障任务中比较直接重试、根因图诊断和诊断驱动自探索，测量定位准确率、恢复率与危险调用数。",
        "risk": "canary 可能改变候选工具分布，需要验证移除 canary 后修复是否仍然保持。",
        "papers": ["2608.04719", "2608.08968", "2608.07925"],
    },
    {
        "cats": [11, 2],
        "title": "把医学影像证据反思迁移到多模态偏差评测",
        "thesis": "让多模态 Agent 显式判断工具是否必要、证据是否可靠，再用模式完成偏差与隐式语义标注任务检验反思是否真正依赖视觉证据。",
        "test": "对比无反思、自我反思和外部证据校验，在诊断与视觉代码任务上报告准确率、无效工具调用、证据忠实度和模式偏差。",
        "risk": "医学工具链的先验结构可能无法迁移，应把领域知识收益与通用证据反思收益分开。",
        "papers": ["2608.10827", "2608.03691", "2608.10875"],
    },
]


def load_atlas(path: Path) -> tuple[str, dict]:
    html = path.read_text(encoding="utf-8")
    match = DATA_RE.search(html)
    if not match:
        raise SystemExit(f"Missing arxivIdeaAtlasData in {path}")
    return html, json.loads(match.group(2))


def strip_count_prefix(summary: str) -> str:
    return re.sub(r"^本组共\s*\d+\s*篇，", "", summary).strip()


def build_data(previous: dict, daily_dir: Path, as_of: str) -> dict:
    papers = classified.load_papers_from_dir(daily_dir)
    if not papers:
        raise SystemExit(f"No arXiv papers parsed from {daily_dir}")

    previous_category = {paper["id"]: paper["category"] for paper in previous["papers"]}
    category_id = {name: idx for idx, name in enumerate(classified.CATEGORY_ORDER)}
    paper_rows = []
    grouped: dict[int, list[dict]] = defaultdict(list)

    for paper in papers:
        category = previous_category.get(
            paper["arxiv_id"], category_id[classified.classify_paper(paper)]
        )
        row = {
            "id": paper["arxiv_id"],
            "title": paper["title"],
            "url": paper["arxiv_url"],
            "pdf": paper["pdf_url"],
            "authors": paper["authors"],
            "summary": paper["one_line"],
            "detail": paper["detail"],
            "date": paper["paper_date"],
            "tags": paper["tags"],
            "category": category,
        }
        paper_rows.append(row)
        grouped[category].append(paper)

    paper_rows.sort(key=lambda paper: (paper["date"], paper["title"]), reverse=True)
    paper_to = max(paper["date"] for paper in paper_rows)
    recent_cutoff = (date.fromisoformat(paper_to) - timedelta(days=6)).isoformat()
    digest_dates = [paper["digest_date"] for paper in papers]

    previous_categories = {category["id"]: category for category in previous["categories"]}
    categories = []
    for idx, name in enumerate(classified.CATEGORY_ORDER):
        items = grouped[idx]
        old = previous_categories[idx]
        categories.append(
            {
                "id": idx,
                "name": name,
                "summary": strip_count_prefix(classified.write_category_summary(name, items)),
                "count": len(items),
                "recent": sum(paper["paper_date"] >= recent_cutoff for paper in items),
                "frame": old["frame"],
            }
        )

    return {
        "meta": {
            "title": "arXiv 论文灵感图谱",
            "as_of": as_of,
            "from": min(digest_dates),
            "to": max(digest_dates),
            "paper_to": paper_to,
            "papers": len(paper_rows),
            "categories": len(categories),
            "recent_cutoff": recent_cutoff,
            "source": "https://yzbcs.github.io/study/",
            "reference": "https://yzbcs.github.io/research/arxiv_daily_classified.html",
        },
        "categories": categories,
        "papers": paper_rows,
        "bridges": CURATED_BRIDGES,
    }


def render(html: str, data: dict) -> str:
    meta = data["meta"]
    index_comment = (
        f"<!-- index: arXiv 论文灵感图谱 | {meta['as_of']} | "
        f"整理 {meta['papers']} 篇每日推送论文的 {meta['categories']} 类主题图谱，"
        "支持检索、收藏、近期信号与跨主题 Idea Lab。 -->"
    )
    html = re.sub(r"\A<!-- index:.*?-->", index_comment, html, count=1, flags=re.S)
    html = re.sub(
        r"<div class=\"atlas-section-head\"><div><h2>近期可做的桥</h2><p>.*?</p></div></div>",
        '<div class="atlas-section-head"><div><h2>近期可做的桥</h2><p>由最近 7 日新增论文触发。</p></div></div>',
        html,
        count=1,
        flags=re.S,
    )
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = DATA_RE.sub(lambda match: match.group(1) + payload + match.group(3), html, count=1)
    return html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-dir", type=Path, default=DEFAULT_DAILY_DIR)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--as-of", help="Atlas snapshot date; defaults to latest digest date")
    args = parser.parse_args(argv)

    html, previous = load_atlas(args.atlas)
    if args.as_of:
        as_of = args.as_of
    else:
        source = classified.load_papers_from_dir(args.daily_dir)
        as_of = max(paper["digest_date"] for paper in source)
    data = build_data(previous, args.daily_dir, as_of)
    args.atlas.write_text(render(html, data), encoding="utf-8")
    print(
        json.dumps(
            {
                "papers": data["meta"]["papers"],
                "categories": data["meta"]["categories"],
                "from": data["meta"]["from"],
                "to": data["meta"]["to"],
                "paper_to": data["meta"]["paper_to"],
                "recent_cutoff": data["meta"]["recent_cutoff"],
                "bridges": len(data["bridges"]),
                "out": str(args.atlas),
                "bytes": args.atlas.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
