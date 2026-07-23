#!/usr/bin/env python3
"""Build arxiv_daily_classified.html from yzbcs.github.io/study digests.

Pipeline:
1) Load local daily HTML files (or fetch from GitHub raw if --fetch).
2) Parse arXiv cards only (ignore 小红书).
3) Score-based topic classification + optional id overrides.
4) Write grounded per-category summaries from digest one-line/detail text.
5) Emit a self-contained root HTML with <!-- index: ... --> comment.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "arxiv_daily_classified.html"
STUDY_BASE = "https://raw.githubusercontent.com/yzbcs/yzbcs.github.io/master/study/"
PROXY = "http://127.0.0.1:7890"

# (category, [(pattern, weight, field)]) field: T=title O=one_line D=detail G=tags A=all
CATEGORY_RULES: list[tuple[str, list[tuple[str, int, str]]]] = [
    (
        "Agent 安全、对抗、隔离与对齐",
        [
            (r"security|safety|jailbreak|adversar|attack|poison|isolation|untrusted|guardrail|red.?team|mempoison|broken gates|safety sentry|toolalign|对齐冲突|权限滥用|越权|投毒|对抗|安全基准|防御", 10, "T"),
            (r"安全|攻击|防御|隔离|对抗|越权|投毒|jailbreak|对齐冲突|权限|threat|blind spot|漏洞", 6, "O"),
            (r"安全|攻击|防御|隔离|对抗|越权|滥用", 2, "D"),
        ],
    ),
    (
        "Agent 调试、可观测与错误恢复",
        [
            (r"debug|observab|error correction|failure|self-?repair|recover|agentdebug|trace|diagnos|故障|调试|纠错|可观测", 10, "T"),
            (r"调试|错误纠正|可观测|故障|恢复|根因|诊断", 6, "O"),
        ],
    ),
    (
        "评测基准、失效分析与可信评估",
        [
            (r"benchmark|bench\b|eval\b|evaluation|stocktake|devicesworld|claw-?eval|measuring|survey of|do not fail|context fails|complexity-aware|leaderboard|arena", 10, "T"),
            (r"基准|评测|评估|失败|失效|可信|leaderboard|benchmark", 6, "O"),
        ],
    ),
    (
        "多 Agent 协作、社会模拟与组织",
        [
            (r"multi-?agent|multi-?llm|swarm|society|social|coalition|collaborat|org(?:anization)?|team of|tour meeting|group travel|网络化社会|多Agent|多智能体", 10, "T"),
            (r"多Agent|多 LLM|多智能体|协作|社会模拟|联盟|团体|协商|编排", 6, "O"),
        ],
    ),
    (
        "工具调用、MCP、API 与环境交互",
        [
            (r"\bmcp\b|tool-?use|tool.?call|toolverse|function.?call|api\b|function calling|tool access|environment|world model.*tool", 10, "T"),
            (r"工具调用|MCP|API|大规模工具|工具协同|function call|tool use", 6, "O"),
        ],
    ),
    (
        "Skill 学习、检索、演化与生态",
        [
            (r"\bskill\b|skillcorpus|skill.?learn|skill.?retriev|skill.?evol|skill.?refin|open skill|技能", 10, "T"),
            (r"Skill|技能|skill 学习|skill 检索|skill 演化|技能库", 6, "O"),
            (r"skill", 4, "G"),
        ],
    ),
    (
        "记忆系统、经验库与长期上下文",
        [
            (r"memory|memori|experience bank|experience graph|long-?term|context management|RAG|retrieval.?augment|知识库|记忆", 10, "T"),
            (r"记忆|经验库|长期|上下文管理|检索增强|外部记忆|经验复用", 6, "O"),
        ],
    ),
    (
        "规划、推理、搜索与决策控制",
        [
            (r"plann|reason|search|tree|mcts|rollout|decision|latent control|workflow|reflect|自我反思|规划|推理|决策", 8, "T"),
            (r"规划|推理|搜索|决策|反思|CoT|树搜索|工作流", 5, "O"),
        ],
    ),
    (
        "强化学习、训练与自改进",
        [
            (r"\brl\b|reinforcement|reward|sft|fine-?tun|post-?train|self-?improv|self-?evolv|policy|训练|强化学习|自改进", 10, "T"),
            (r"强化学习|RL|奖励|微调|自改进|自演化|训练|post-train", 6, "O"),
        ],
    ),
    (
        "GUI / 浏览器 / 计算机操控 Agent",
        [
            (r"gui|browser|web agent|computer use|computer-?use|desktop|os-?world|webarena|playwright|selenium|点击|浏览器|电脑操控", 10, "T"),
            (r"GUI|浏览器|网页|计算机使用|桌面|点击|web agent|computer use", 6, "O"),
        ],
    ),
    (
        "代码、软件工程与 Dev Agent",
        [
            (r"code|coding|software|github|repo|program|debug.*code|swe-?bench|agent.*code|代码|软件工程|编程", 10, "T"),
            (r"代码|编程|软件工程|仓库|SWE|GitHub|程序合成", 6, "O"),
        ],
    ),
    (
        "多模态、视觉、视频与具身感知",
        [
            (r"multimodal|vision|visual|vlm|video|image|embodied|perception|audio|speech|多模态|视觉|视频|具身", 10, "T"),
            (r"多模态|视觉|视频|图像|具身|感知|VLM", 6, "O"),
            (r"visual|multimodal", 5, "G"),
        ],
    ),
    (
        "端侧、机器人与垂直领域应用",
        [
            (r"on-?device|mobile|phone|robot|drone|hpc|medical|finance|legal|scientific|chemistry|retrosynthesis|structural engineering|palmclaw|eflux|垂直|机器人|端侧", 10, "T"),
            (r"端侧|移动|机器人|医疗|金融|科学|化学|逆合成|结构工程|垂直领域|HPC", 6, "O"),
        ],
    ),
    (
        "行为、角色、叙事与可控性",
        [
            (r"behavior|persona|narrative|role|controllab|personality|story shapes|digital pantheon|set-shifting|行为|角色|叙事|人格|可控", 10, "T"),
            (r"行为|角色|叙事|人格|可控性|党派|偏好", 6, "O"),
        ],
    ),
    (
        "OpenClaw 与相关生态",
        [
            (r"openclaw|open.?claw|claw\b", 12, "T"),
            (r"OpenClaw|openclaw|Claw", 8, "O"),
            (r"openclaw", 10, "G"),
        ],
    ),
    (
        "Agent 系统框架、运行时与基础设施",
        [
            (r"framework|runtime|infrastruct|orchestr|platform|architecture|system design|myag|composable|harness|中间件|框架|运行时|基础设施|架构", 8, "T"),
            (r"框架|运行时|基础设施|架构|编排|平台|可组合|系统", 5, "O"),
        ],
    ),
]

CATEGORY_ORDER = [c for c, _ in CATEGORY_RULES] + ["其他 / 跨领域主题"]

# Explicit overrides for known ambiguous titles (arxiv_id -> category)
OVERRIDES: dict[str, str] = {
    "2607.18754": "Agent 调试、可观测与错误恢复",
    "2607.18566": "行为、角色、叙事与可控性",
    "2607.18485": "Agent 安全、对抗、隔离与对齐",
    "2607.13602": "规划、推理、搜索与决策控制",
    "2604.06132": "评测基准、失效分析与可信评估",
}


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def field_text(p: dict, field: str) -> str:
    if field == "T":
        return p.get("title") or ""
    if field == "O":
        return p.get("one_line") or ""
    if field == "D":
        return p.get("detail") or ""
    if field == "G":
        return " ".join(p.get("tags") or [])
    return " ".join(
        [
            p.get("title") or "",
            p.get("one_line") or "",
            p.get("detail") or "",
            " ".join(p.get("tags") or []),
        ]
    )


def parse_daily_html(path: Path, digest_date: str) -> list[dict]:
    """Parse arXiv cards from one daily digest HTML file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    papers: list[dict] = []
    for chunk in text.split('<div class="card">')[1:]:
        piece = chunk[:5000]
        if "arxiv.org" not in piece and "btn-arxiv" not in piece:
            continue
        title_m = re.search(r'class="card-title"[^>]*>\s*(?:<a[^>]*>)?([^<]+)', piece)
        tags = re.findall(r'class="tag"[^>]*>([^<]+)', piece)
        authors_m = re.search(r'class="card-byline"[^>]*>([^<]+)', piece)
        summary_m = re.search(r'class="summary"[^>]*>(.*?)</div>', piece, re.S)
        detail_m = re.search(r'class="detail-body"[^>]*>(.*?)</div>', piece, re.S)
        arxiv_m = re.search(r"https?://arxiv\.org/abs/([\d.]+(?:v\d+)?)", piece)
        if not title_m or not arxiv_m:
            continue
        arxiv_id = re.sub(r"v\d+$", "", arxiv_m.group(1))
        one = re.sub(
            r"^💡\s*一句话总结\s*",
            "",
            clean_text(summary_m.group(1) if summary_m else ""),
        ).strip()
        detail = re.sub(
            r"^论文解读\s*",
            "",
            clean_text(detail_m.group(1) if detail_m else ""),
        ).strip()
        papers.append(
            {
                "title": title_m.group(1).strip(),
                "authors": authors_m.group(1).strip() if authors_m else "",
                "tags": [t.strip() for t in tags],
                "one_line": one,
                "detail": detail,
                "arxiv_id": arxiv_id,
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "digest_date": digest_date,
            }
        )
    return papers


def classify_paper(p: dict) -> str:
    """Score patterns across title/summary/tags; return best category."""
    if p["arxiv_id"] in OVERRIDES:
        return OVERRIDES[p["arxiv_id"]]
    scores: dict[str, float] = defaultdict(float)
    for cat, pats in CATEGORY_RULES:
        for pat, weight, field in pats:
            if re.search(pat, field_text(p, field), re.I):
                scores[cat] += weight
    if not scores:
        return "其他 / 跨领域主题"
    # Prefer security when security-heavy titles also match "benchmark"
    if scores.get("Agent 安全、对抗、隔离与对齐", 0) >= 10 and re.search(
        r"security|safety|attack|poison|isolation", p["title"], re.I
    ):
        return "Agent 安全、对抗、隔离与对齐"
    return max(scores.items(), key=lambda x: x[1])[0]


def write_category_summary(cat: str, items: list[dict]) -> str:
    """Write a short Chinese summary grounded in this group's digest texts."""
    n = len(items)
    ones = [p["one_line"] for p in items if p.get("one_line")]
    # sample distinctive phrases
    sample = "；".join(ones[:5]) if ones else "；".join(p["title"] for p in items[:4])

    templates = {
        "Agent 安全、对抗、隔离与对齐": (
            f"本组共 {n} 篇，围绕 Agent 的安全边界、对抗攻击、权限隔离与对齐冲突。"
            f"常见议题包括凭证/工具权限滥用、内存投毒、Web Bot 防御失效、跨会话攻击归因、"
            f"人机干预路由，以及把隔离作为系统一等公民原则。"
            f"代表要点：{sample}。"
        ),
        "Agent 调试、可观测与错误恢复": (
            f"本组共 {n} 篇，关注故障观测、根因归因、错误纠正与恢复闭环。"
            f"核心痛点是表面出错步骤常非真正根因，因而需要结构化诊断、轨迹可观测与可复用纠错记忆。"
            f"代表要点：{sample}。"
        ),
        "评测基准、失效分析与可信评估": (
            f"本组共 {n} 篇，建设或批判 Agent 评测：轨迹透明评分、安全维度、感知-行动差距、"
            f"跨设备/动态工具环境，以及“上下文先失败”等失效解剖。"
            f"目标是把“Agent 不行”拆成可定位的子系统问题。代表要点：{sample}。"
        ),
        "多 Agent 协作、社会模拟与组织": (
            f"本组共 {n} 篇，研究多 Agent 角色分工、协商编排、群体决策与社会/组织模拟。"
            f"应用从旅行规划、集体问题解决到政治联盟与递归自改进架构。代表要点：{sample}。"
        ),
        "工具调用、MCP、API 与环境交互": (
            f"本组共 {n} 篇，聚焦 Agent 与外部工具/API/MCP/环境的接口层："
            f"大规模工具接入、动态服务器演化、兼容性与可扩展管理。代表要点：{sample}。"
        ),
        "Skill 学习、检索、演化与生态": (
            f"本组共 {n} 篇，讨论可复用 Skill 的学习、检索、精炼与开源生态评测，"
            f"把一次性工具脚本推进为可组合、可演化的技能资产。代表要点：{sample}。"
        ),
        "记忆系统、经验库与长期上下文": (
            f"本组共 {n} 篇，研究外部记忆、经验库、长期上下文与检索增强，"
            f"使 Agent 能跨任务复用历史并控制记忆写入/淘汰。代表要点：{sample}。"
        ),
        "规划、推理、搜索与决策控制": (
            f"本组共 {n} 篇，覆盖规划、搜索（树/图）、反思式推理与统一决策接口，"
            f"以及类比深度研究等需要多步推理的任务形态。代表要点：{sample}。"
        ),
        "强化学习、训练与自改进": (
            f"本组共 {n} 篇，关注训练信号与演化机制：多轮 RL、过程奖励、harness 自动优化、"
            f"评估指标与技能协同演化等。代表要点：{sample}。"
        ),
        "GUI / 浏览器 / 计算机操控 Agent": (
            f"本组共 {n} 篇，面向 GUI、浏览器与计算机使用场景的感知-操作闭环，"
            f"包括网页导航、桌面自动化与相关环境基准。代表要点：{sample}。"
        ),
        "代码、软件工程与 Dev Agent": (
            f"本组共 {n} 篇，围绕代码生成、仓库级软件工程、程序修复与开发工作流 Agent。"
            f"代表要点：{sample}。"
        ),
        "多模态、视觉、视频与具身感知": (
            f"本组共 {n} 篇，将 Agent 能力扩展到视觉、视频、语音等多模态输入，"
            f"以及具身/主动感知设定。代表要点：{sample}。"
        ),
        "端侧、机器人与垂直领域应用": (
            f"本组共 {n} 篇，把 Agent 放入强约束载体或专业领域：手机端侧、机器人编队、"
            f"科学发现、医疗/化学/结构工程、HPC 等。代表要点：{sample}。"
        ),
        "行为、角色、叙事与可控性": (
            f"本组共 {n} 篇，从行为科学与可控性角度审视 Agent：叙事先验、角色/人格、"
            f"组件（Reflection/Memory）对行为的影响，以及政治/社会偏好审计。代表要点：{sample}。"
        ),
        "OpenClaw 与相关生态": (
            f"本组共 {n} 篇，与 OpenClaw/Claw 生态相关的评测、能力或系统讨论。"
            f"代表要点：{sample}。"
        ),
        "Agent 系统框架、运行时与基础设施": (
            f"本组共 {n} 篇，提供可组合系统设计、运行时、编排与基础设施抽象，"
            f"服务复杂 Agent 系统的搭建与分析。代表要点：{sample}。"
        ),
        "其他 / 跨领域主题": (
            f"本组共 {n} 篇，主题分散或同时跨越多个方向，未强行并入以上主类。"
            f"涵盖：{sample}。"
        ),
    }
    return templates.get(cat, f"本组共 {n} 篇。涵盖：{sample}。")


def load_papers_from_dir(daily_dir: Path) -> list[dict]:
    all_papers: list[dict] = []
    for f in sorted(daily_dir.glob("*.html")):
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", f.name)
        digest_date = m.group(1) if m else f.stem
        all_papers.extend(parse_daily_html(f, digest_date))
    # dedupe by arxiv_id, keep latest digest appearance
    seen: dict[str, dict] = {}
    for p in sorted(all_papers, key=lambda x: x["digest_date"], reverse=True):
        seen.setdefault(p["arxiv_id"], p)
    return list(seen.values())


def fetch_all_digests(cache_dir: Path) -> Path:
    """Fetch study/data.json and all daily HTML into cache_dir; return cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy)

    def fetch(url: str) -> bytes:
        try:
            with opener.open(url, timeout=45) as r:
                return r.read()
        except Exception:
            with urllib.request.urlopen(url, timeout=45) as r:
                return r.read()

    raw = fetch(STUDY_BASE + "data.json")
    (cache_dir / "data.json").write_bytes(raw)
    notes = json.loads(raw)["notes"]
    daily_dir = cache_dir / "daily_html_all"
    daily_dir.mkdir(exist_ok=True)
    for n in notes:
        out = daily_dir / n["path"].replace("/", "_")
        if out.exists() and out.stat().st_size > 500:
            continue
        out.write_bytes(fetch(STUDY_BASE + n["path"]))
    return daily_dir


def esc(s: str) -> str:
    return html_lib.escape(s or "", quote=True)


def render_html(papers: list[dict], generated: str | None = None) -> str:
    generated = generated or date.today().isoformat()
    for p in papers:
        p["category"] = classify_paper(p)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in papers:
        by_cat[p["category"]].append(p)

    cat_order = [c for c in CATEGORY_ORDER if by_cat.get(c)]
    for c in sorted(by_cat.keys()):
        if c not in cat_order:
            cat_order.append(c)

    summaries = {c: write_category_summary(c, by_cat[c]) for c in cat_order}
    digest_dates = sorted({p["digest_date"] for p in papers})
    date_range = f"{digest_dates[0]} ~ {digest_dates[-1]}" if digest_dates else ""
    day_count = len(digest_dates)

    toc_items = []
    for i, c in enumerate(cat_order):
        toc_items.append(
            f'<a class="toc-item" href="#cat-{i}"><span class="toc-name">{esc(c)}</span>'
            f'<span class="toc-count">{len(by_cat[c])}</span></a>'
        )

    sections = []
    for i, c in enumerate(cat_order):
        items = sorted(
            by_cat[c], key=lambda x: (x["digest_date"], x["title"]), reverse=True
        )
        cards = []
        for p in items:
            tag_html = "".join(
                f'<span class="tag">{esc(t)}</span>' for t in (p["tags"] or ["arxiv"])
            )
            cards.append(
                f"""
        <article class="paper">
          <div class="paper-top">
            <div class="tags">{tag_html}</div>
            <span class="digest-date">Digest {esc(p['digest_date'])}</span>
          </div>
          <h3 class="paper-title"><a href="{esc(p['arxiv_url'])}" target="_blank" rel="noopener">{esc(p['title'])}</a></h3>
          <div class="paper-meta">
            <span class="arxiv-id"><a href="{esc(p['arxiv_url'])}" target="_blank" rel="noopener">arXiv:{esc(p['arxiv_id'])}</a></span>
            {f"<span class='authors'>{esc(p['authors'])}</span>" if p.get('authors') else ""}
          </div>
          {f"<p class='one-line'>{esc(p['one_line'])}</p>" if p.get('one_line') else ""}
          {f"<details class='detail-wrap'><summary>digest 详解</summary><p class='detail'>{esc(p['detail'])}</p></details>" if p.get('detail') else ""}
          <div class="links">
            <a class="btn" href="{esc(p['arxiv_url'])}" target="_blank" rel="noopener">Abstract</a>
            <a class="btn btn-pdf" href="{esc(p['pdf_url'])}" target="_blank" rel="noopener">PDF</a>
          </div>
        </article>"""
            )
        sections.append(
            f"""
    <section class="category" id="cat-{i}">
      <header class="cat-header">
        <h2>{esc(c)}</h2>
        <span class="badge">{len(items)} 篇</span>
      </header>
      <div class="cat-summary">
        <div class="summary-label">类别综述</div>
        <p>{esc(summaries[c])}</p>
      </div>
      <div class="papers">{''.join(cards)}</div>
    </section>"""
        )

    # monthly breakdown for hero
    month_c = Counter(p["digest_date"][:7] for p in papers)
    month_bits = " · ".join(f"{m}:{month_c[m]}" for m in sorted(month_c))

    return f"""<!-- index: arXiv 每日论文全量分类整理 | {generated} | 对 yzbcs.github.io/study 全部 Daily Digest 中的 arXiv 论文按主题分类并撰写类别综述 -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="对 yzbcs.github.io/study 全部 Daily Digest 中的 arXiv 论文按主题分类并撰写类别综述（{date_range}，{len(papers)} 篇）">
  <title>arXiv 每日论文全量分类整理 · {esc(date_range)}</title>
  <style>
    :root {{
      --bg: #f0f2f7; --card: #fff; --ink: #1a1d26; --muted: #5c6578; --line: #e2e6ef;
      --accent: #3b5bdb; --accent-soft: #eef2ff; --shadow: 0 8px 28px rgba(15,23,42,.07); --radius: 14px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(1200px 500px at 10% -10%, #dbeafe 0%, transparent 55%),
                  radial-gradient(900px 400px at 100% 0%, #ccfbf1 0%, transparent 50%), var(--bg);
      color: var(--ink); line-height: 1.7; padding: 36px 18px 64px;
    }}
    .wrap {{ max-width: 1040px; margin: 0 auto; }}
    .hero {{
      background: linear-gradient(135deg, #0f2027 0%, #203a43 48%, #2c5364 100%);
      color: #fff; border-radius: 18px; padding: 32px 30px 28px; box-shadow: var(--shadow); margin-bottom: 22px;
    }}
    .hero .eyebrow {{ font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase; color: #7ecfff; margin-bottom: 10px; }}
    .hero h1 {{ font-size: 28px; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.02em; }}
    .hero .sub {{ color: #b8c9d6; font-size: 14px; margin-bottom: 16px; max-width: 820px; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .stat {{ background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.16); border-radius: 999px; padding: 5px 14px; font-size: 12px; color: #d7e8f5; }}
    .stat b {{ color: #7ecfff; }}
    .source-note {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 18px; margin-bottom: 18px; color: var(--muted); font-size: 13px; }}
    .source-note a {{ color: var(--accent); text-decoration: none; }}
    .source-note a:hover {{ text-decoration: underline; }}
    .toc {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px 10px; margin-bottom: 24px; box-shadow: var(--shadow); }}
    .toc h2 {{ font-size: 15px; margin-bottom: 10px; }}
    .toc-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }}
    .toc-item {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); background: #f8fafc; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; font-size: 13px; }}
    .toc-item:hover {{ border-color: #a5b4fc; background: var(--accent-soft); }}
    .toc-name {{ font-weight: 600; }}
    .toc-count {{ background: var(--accent); color: #fff; border-radius: 999px; font-size: 11px; font-weight: 700; min-width: 22px; text-align: center; padding: 1px 7px; }}
    .category {{ background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 22px 22px 10px; margin-bottom: 20px; box-shadow: var(--shadow); }}
    .cat-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 2px solid var(--accent); }}
    .cat-header h2 {{ font-size: 20px; font-weight: 800; }}
    .badge {{ background: var(--accent-soft); color: var(--accent); border-radius: 999px; font-size: 12px; font-weight: 700; padding: 4px 12px; white-space: nowrap; }}
    .cat-summary {{ background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); border: 1px solid #e0e7ff; border-left: 4px solid var(--accent); border-radius: 0 12px 12px 0; padding: 14px 16px; margin-bottom: 18px; }}
    .summary-label {{ font-size: 11px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }}
    .cat-summary p {{ font-size: 14px; color: #334155; }}
    .papers {{ display: grid; gap: 12px; padding-bottom: 12px; }}
    .paper {{ border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: #fff; }}
    .paper-top {{ display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; margin-bottom: 8px; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 5px; }}
    .tag {{ font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 5px; background: #f1f5f9; color: #475569; }}
    .digest-date {{ font-size: 11px; color: #94a3b8; white-space: nowrap; }}
    .paper-title {{ font-size: 15px; font-weight: 700; line-height: 1.45; margin-bottom: 6px; }}
    .paper-title a {{ color: inherit; text-decoration: none; }}
    .paper-title a:hover {{ color: var(--accent); text-decoration: underline; }}
    .paper-meta {{ display: flex; flex-wrap: wrap; gap: 8px 14px; font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
    .arxiv-id a {{ color: var(--accent); font-weight: 700; text-decoration: none; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .one-line {{ background: var(--accent-soft); border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; padding: 8px 12px; font-size: 13px; color: #1e293b; margin-bottom: 8px; }}
    .detail-wrap {{ margin-bottom: 10px; font-size: 13px; color: #475569; }}
    .detail-wrap summary {{ cursor: pointer; color: var(--accent); font-weight: 600; margin-bottom: 4px; }}
    .detail {{ margin-top: 6px; }}
    .links {{ display: flex; gap: 8px; }}
    .btn {{ display: inline-block; font-size: 12px; font-weight: 700; text-decoration: none; padding: 5px 12px; border-radius: 8px; background: var(--accent); color: #fff; }}
    .btn-pdf {{ background: #0f766e; }}
    .footer {{ text-align: center; color: #94a3b8; font-size: 12px; margin-top: 8px; }}
    .month-line {{ margin-top: 12px; font-size: 12px; color: #9db4c4; }}
    @media (max-width: 640px) {{
      body {{ padding: 18px 12px 40px; }}
      .hero {{ padding: 22px 18px; }}
      .hero h1 {{ font-size: 22px; }}
      .category {{ padding: 16px 14px 8px; }}
      .paper-top {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <div class="eyebrow">Daily Digest · Full Archive Classification</div>
      <h1>arXiv 每日论文全量分类整理</h1>
      <p class="sub">
        从来源 <strong>yzbcs.github.io/study</strong> 的<strong>全部</strong> Daily Digest 中提取 arXiv 论文
        （不含小红书笔记），按主题归类并为每一类撰写内容综述。
      </p>
      <div class="stats">
        <span class="stat">论文 <b>{len(papers)}</b> 篇</span>
        <span class="stat">类别 <b>{len(cat_order)}</b> 个</span>
        <span class="stat">有文 digest 日 <b>{day_count}</b></span>
        <span class="stat">日期窗口 <b>{esc(date_range)}</b></span>
        <span class="stat">生成日 <b>{esc(generated)}</b></span>
      </div>
      <div class="month-line">按月篇数：{esc(month_bits)}</div>
    </header>
    <div class="source-note">
      数据来源：
      <a href="https://yzbcs.github.io/study/" target="_blank" rel="noopener">https://yzbcs.github.io/study/</a>
      · 索引
      <a href="https://raw.githubusercontent.com/yzbcs/yzbcs.github.io/master/study/data.json" target="_blank" rel="noopener">study/data.json</a>
      · 分类依据为 digest 卡片 tags、标题与中文一句话/详解（未读 PDF 全文）。
      详解默认折叠，可展开查看。同一 arXiv id 若多日出现，保留最近一次 digest 记录。
    </div>
    <nav class="toc" aria-label="类别目录">
      <h2>类别目录（点击跳转）</h2>
      <div class="toc-grid">{''.join(toc_items)}</div>
    </nav>
    {''.join(sections)}
    <p class="footer">Full archive from live digests · arXiv only · yzbcs.github.io/research</p>
  </div>
</body>
</html>
"""


def build(daily_dir: Path, out_path: Path, generated: str | None = None) -> dict:
    papers = load_papers_from_dir(daily_dir)
    if not papers:
        raise SystemExit(f"No arXiv papers parsed from {daily_dir}")
    html = render_html(papers, generated=generated)
    out_path.write_text(html, encoding="utf-8")
    by_cat: Counter[str] = Counter(classify_paper(p) for p in papers)
    meta = {
        "paper_count": len(papers),
        "categories": dict(by_cat.most_common()),
        "date_min": min(p["digest_date"] for p in papers),
        "date_max": max(p["digest_date"] for p in papers),
        "out": str(out_path),
        "bytes": out_path.stat().st_size,
    }
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--daily-dir",
        type=Path,
        help="Directory of daily_*.html files (default: fetch or use --cache-dir)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=ROOT / "assets" / "input" / "study_digests",
        help="Cache dir for fetched digests when --fetch is set",
    )
    parser.add_argument("--fetch", action="store_true", help="Fetch all digests into cache-dir")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--generated-date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    if args.daily_dir:
        daily_dir = args.daily_dir
    elif args.fetch:
        print(f"Fetching digests into {args.cache_dir} ...")
        daily_dir = fetch_all_digests(args.cache_dir)
    else:
        # prefer explicit daily-dir; else cache
        cand = args.cache_dir / "daily_html_all"
        if cand.exists():
            daily_dir = cand
        else:
            raise SystemExit("Provide --daily-dir or --fetch")

    meta = build(daily_dir, args.output, generated=args.generated_date)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
