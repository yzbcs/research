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


STYLES = r"""
    @font-face{font-family:'Fraunces';font-style:normal;font-weight:100 900;font-display:swap;src:url('fonts/fraunces-latin.woff2') format('woff2')}
    @font-face{font-family:'Fraunces';font-style:normal;font-weight:100 900;font-display:swap;src:url('fonts/fraunces-latin-ext.woff2') format('woff2');unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF}
    :root{
      --paper:#f4efe3; --paper-2:#ece4d2; --card:#fbf7ee; --card-2:#fffdf7;
      --ink:#211c15; --ink-2:#3b3327; --muted:#877964; --muted-2:#a89a83;
      --line:#e1d8c4; --line-2:#d3c7ad;
      --accent:#0e5a54; --accent-d:#0a423d; --accent-soft:#e4eeeb;
      --sienna:#9a3412; --sienna-soft:#fbf0e7; --gold:#9a6d0f;
      --shadow-sm:0 1px 0 rgba(40,30,12,.04),0 6px 18px -10px rgba(40,30,12,.18);
      --shadow:0 18px 42px -24px rgba(40,30,12,.34);
      --tool-h:60px; --side-w:252px;
      --ff-display:'Fraunces','Songti SC','STSong','Source Han Serif SC','Noto Serif SC',Georgia,serif;
      --ff-body:'PingFang SC','Hiragino Sans GB','Microsoft YaHei',system-ui,-apple-system,'Segoe UI',sans-serif;
      --ff-mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html{scroll-behavior:smooth;scroll-padding-top:calc(var(--tool-h) + 16px)}
    body{font-family:var(--ff-body);background:var(--paper);color:var(--ink);line-height:1.65;font-size:15px;-webkit-font-smoothing:antialiased;position:relative;min-height:100vh}
    body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");opacity:.05;mix-blend-mode:multiply}
    .wrap{max-width:1200px;margin:0 auto;padding:0 22px;position:relative;z-index:1}

    /* MASTHEAD */
    .masthead{position:relative;overflow:hidden;margin:30px 0 0;border-radius:10px;background:linear-gradient(135deg,#0a332f 0%,#0e5a54 50%,#136864 100%);color:#f4efe3;padding:46px 46px 38px;border:1px solid #082a27;box-shadow:var(--shadow)}
    .masthead::after{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(720px 320px at 86% -12%,rgba(255,224,150,.18),transparent 60%)}
    .masthead .watermark{position:absolute;right:-8px;bottom:-58px;font-family:var(--ff-display);font-weight:900;font-size:240px;line-height:1;color:rgba(255,255,255,.05);letter-spacing:-.04em;pointer-events:none;user-select:none}
    .masthead .eyebrow{position:relative;font-family:var(--ff-mono);font-size:11px;letter-spacing:.32em;text-transform:uppercase;color:#a6dbd3;margin-bottom:18px}
    .masthead h1{position:relative;font-family:var(--ff-display);font-weight:900;font-size:clamp(31px,4.8vw,52px);line-height:1.04;letter-spacing:-.02em;font-optical-sizing:auto}
    .masthead .lede{position:relative;color:#cfe3df;margin-top:14px;max-width:64ch;font-size:15px;line-height:1.7}
    .masthead .lede strong{color:#ffe6a8;font-weight:600}
    .stat-row{position:relative;display:flex;flex-wrap:wrap;gap:0;margin-top:28px;border-top:1px solid rgba(255,255,255,.16);padding-top:20px}
    .stat{padding-right:30px;margin-right:26px;border-right:1px solid rgba(255,255,255,.14)}
    .stat:last-child{border-right:0;margin-right:0}
    .stat .k{font-family:var(--ff-display);font-weight:700;font-size:28px;color:#fff;line-height:1;font-optical-sizing:auto}
    .stat .k .unit{font-size:13px;color:#a6dbd3;margin-left:4px;font-weight:500}
    .stat .l{font-family:var(--ff-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#8fbab4;margin-top:7px}
    .month-line{position:relative;margin-top:18px;font-family:var(--ff-mono);font-size:11.5px;color:#a6dbd3;letter-spacing:.03em}
    .src-note{position:relative;margin:16px 0 0;font-size:12.5px;color:#bcd3ce;max-width:96ch;line-height:1.65}
    .src-note a{color:#ffe6a8;text-decoration:none;border-bottom:1px dotted rgba(255,230,168,.45)}

    /* TOOLBAR */
    .toolbar{position:sticky;top:0;z-index:50;margin:20px 0 0;background:rgba(244,239,227,.88);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid var(--line-2);border-radius:10px;padding:10px 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;box-shadow:var(--shadow-sm)}
    .search{position:relative;flex:1 1 300px;min-width:190px;display:flex;align-items:center}
    .search input{width:100%;border:1px solid var(--line-2);background:var(--card);border-radius:6px;padding:9px 12px 9px 34px;font-family:inherit;font-size:14px;color:var(--ink)}
    .search input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
    .search .ico{position:absolute;left:11px;color:var(--muted);pointer-events:none}
    .tagbar{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
    .chip{font-family:inherit;font-size:11.5px;font-weight:600;border:1px solid var(--line-2);background:var(--card);color:var(--ink-2);border-radius:999px;padding:5px 11px;cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:5px}
    .chip .cn{font-family:var(--ff-mono);font-size:10px;color:var(--muted-2);font-weight:600}
    .chip:hover{border-color:var(--accent);color:var(--accent)}
    .chip:hover .cn{color:var(--accent)}
    .chip.active{background:var(--accent);border-color:var(--accent);color:#fff}
    .chip.active .cn{color:rgba(255,255,255,.8)}
    .toggle-new{font-family:inherit;font-size:11.5px;font-weight:700;border:1px solid var(--sienna);color:var(--sienna);background:transparent;border-radius:999px;padding:5px 12px;cursor:pointer;display:inline-flex;align-items:center;gap:7px;transition:.15s}
    .toggle-new:hover{background:var(--sienna-soft)}
    .toggle-new .dot{width:7px;height:7px;border-radius:50%;background:var(--sienna)}
    .toggle-new.active{background:var(--sienna);color:#fff}
    .toggle-new.active .dot{background:#fff}
    .result-count{font-family:var(--ff-mono);font-size:11.5px;color:var(--muted);margin-left:auto;white-space:nowrap}

    /* LAYOUT */
    .layout{display:grid;grid-template-columns:var(--side-w) 1fr;gap:32px;margin-top:26px;align-items:start}
    .toc{position:sticky;top:calc(var(--tool-h) + 20px);max-height:calc(100vh - var(--tool-h) - 40px);overflow:auto;padding-right:6px}
    .toc h3{font-family:var(--ff-mono);font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
    .toc-list{list-style:none;display:flex;flex-direction:column;gap:3px}
    .toc-item{display:block;text-decoration:none;color:var(--ink-2);border:1px solid transparent;border-radius:6px;padding:8px 10px;position:relative;transition:.15s}
    .toc-item .tn{font-size:12.5px;font-weight:600;line-height:1.25;display:block;padding-right:30px}
    .toc-item .tc{position:absolute;top:8px;right:10px;font-family:var(--ff-mono);font-size:10.5px;color:var(--muted-2);font-weight:600}
    .toc-item .bar{height:3px;background:var(--line);border-radius:2px;margin-top:7px;overflow:hidden}
    .toc-item .bar i{display:block;height:100%;background:var(--muted-2);border-radius:2px;transition:background .15s}
    .toc-item:hover{background:var(--card);border-color:var(--line)}
    .toc-item.active{background:var(--accent-soft);border-color:#bcd3cd}
    .toc-item.active .tn{color:var(--accent-d)}
    .toc-item.active .tc{color:var(--accent)}
    .toc-item.active .bar i{background:var(--accent)}

    /* CATEGORY */
    .cat{background:var(--card);border:1px solid var(--line);border-radius:8px;margin-bottom:22px;overflow:hidden;scroll-margin-top:calc(var(--tool-h) + 20px)}
    .js .cat{opacity:0;transform:translateY(12px)}
    .js .cat.in{opacity:1;transform:none;transition:opacity .55s ease,transform .55s ease}
    .cat-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:22px 26px 14px;border-bottom:1px solid var(--line)}
    .cat-head>div:first-child{flex:1;min-width:0}
    .cat-num{display:block;font-family:var(--ff-mono);font-size:10.5px;color:var(--muted-2);letter-spacing:.08em;text-transform:uppercase}
    .cat-head h2{font-family:var(--ff-display);font-weight:800;font-size:23px;letter-spacing:-.01em;line-height:1.18;margin-top:6px;font-optical-sizing:auto}
    .cat-count{font-family:var(--ff-display);font-weight:700;font-size:22px;color:var(--accent);white-space:nowrap;line-height:1;text-align:right}
    .cat-count .u{font-size:12px;color:var(--muted);font-weight:500;margin-left:2px}
    .cat-new{display:block;margin-top:6px;font-family:var(--ff-mono);font-size:10.5px;font-weight:700;color:var(--sienna);letter-spacing:.04em}
    .cat-summary{margin:14px 26px;background:linear-gradient(180deg,#fdfaf2,#f5f0e3);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:0 6px 6px 0;padding:13px 16px}
    .cat-summary .lab{font-family:var(--ff-mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin-bottom:7px}
    .cat-summary p{font-size:13.5px;color:var(--ink-2);line-height:1.72}
    .papers{display:grid;grid-template-columns:repeat(auto-fill,minmax(336px,1fr));gap:12px;padding:14px 26px 24px}

    /* CARD */
    .paper{position:relative;border:1px solid var(--line);border-radius:6px;background:var(--card-2);padding:14px 15px;transition:transform .16s,box-shadow .16s,border-color .16s;scroll-margin-top:calc(var(--tool-h) + 20px)}
    .paper:hover{border-color:var(--line-2);box-shadow:var(--shadow-sm);transform:translateY(-2px)}
    .paper.is-new{border-color:#e3c6ab;background:#fffaf1}
    .paper.is-new::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--sienna);border-radius:6px 0 0 6px}
    .paper-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;min-height:18px}
    .top-right{display:flex;align-items:center;gap:7px;flex-shrink:0}
    .tags{display:flex;gap:4px;flex-wrap:wrap}
    .tag{font-size:9.5px;font-weight:700;letter-spacing:.02em;padding:2px 7px;border-radius:3px;background:var(--paper-2);color:var(--ink-2);border:1px solid var(--line)}
    .new-flag{font-family:var(--ff-mono);font-size:9px;font-weight:700;letter-spacing:.08em;background:var(--sienna);color:#fff;padding:2px 6px;border-radius:3px}
    .digest-date{font-family:var(--ff-mono);font-size:10.5px;color:var(--muted-2);white-space:nowrap}
    .paper-title{font-family:var(--ff-display);font-weight:700;font-size:16px;line-height:1.32;margin-bottom:8px;letter-spacing:-.005em;font-optical-sizing:auto}
    .paper-title a{color:var(--ink);text-decoration:none}
    .paper-title a:hover{color:var(--accent)}
    .paper-meta{display:flex;flex-wrap:wrap;gap:6px 12px;font-size:11.5px;color:var(--muted);margin-bottom:9px;align-items:center}
    .arxiv-id a{font-family:var(--ff-mono);font-weight:600;color:var(--accent);text-decoration:none;font-size:11.5px}
    .arxiv-id a:hover{text-decoration:underline}
    .authors{color:var(--muted)}
    .one-line{font-family:var(--ff-display);font-size:14px;color:#2b251e;background:var(--accent-soft);border-left:3px solid var(--accent);padding:9px 13px;border-radius:0 5px 5px 0;margin-bottom:10px;line-height:1.72}
    .detail-wrap{margin-bottom:9px}
    .detail-wrap summary{cursor:pointer;font-size:12px;font-weight:600;color:var(--accent);list-style:none;display:inline-block}
    .detail-wrap summary::-webkit-details-marker{display:none}
    .detail-wrap summary::before{content:"\25B8 ";color:var(--muted-2)}
    .detail-wrap[open] summary::before{content:"\25BE "}
    .detail{font-family:var(--ff-display);font-size:13px;color:var(--muted);line-height:1.74;margin-top:8px;padding-top:8px;border-top:1px dashed var(--line)}
    .links{display:flex;gap:7px}
    .btn{font-size:11px;font-weight:700;text-decoration:none;padding:5px 11px;border-radius:4px;border:1px solid var(--accent);color:var(--accent);background:transparent;transition:.15s;cursor:pointer}
    .btn:hover{background:var(--accent);color:#fff}
    .btn-pdf{border-color:var(--gold);color:var(--gold)}
    .btn-pdf:hover{background:var(--gold);color:#fff}

    /* EMPTY / FOOTER / TOTOP */
    .empty{display:none;text-align:center;padding:64px 20px;color:var(--muted);font-family:var(--ff-display);font-size:18px}
    .empty.show{display:block}
    .footer{text-align:center;color:var(--muted-2);font-size:11.5px;margin:8px 0 44px;font-family:var(--ff-mono);letter-spacing:.05em}
    .totop{position:fixed;right:22px;bottom:22px;width:42px;height:42px;border-radius:50%;background:var(--accent);color:#fff;border:none;cursor:pointer;display:none;align-items:center;justify-content:center;box-shadow:var(--shadow);z-index:40;font-size:18px;line-height:1}
    .totop.show{display:flex}
    .totop:hover{background:var(--accent-d)}
    .cat.hidden,.paper.hidden{display:none!important}

    /* RESPONSIVE */
    @media (max-width:880px){
      :root{--side-w:0px}
      .layout{grid-template-columns:1fr;gap:0}
      .toc{position:static;max-height:none;overflow:visible;margin-bottom:6px}
      .toc h3{margin-bottom:8px}
      .toc-list{flex-direction:row;flex-wrap:wrap;gap:5px}
      .toc-item{flex:0 0 auto}
      .toc-item .tn{padding-right:0}
      .toc-item .bar{display:none}
      .masthead{padding:30px 22px 26px}
      .masthead .watermark{font-size:160px;bottom:-34px}
      .papers{grid-template-columns:1fr;padding:12px 18px 20px}
      .cat-head{padding-left:18px;padding-right:18px}
      .cat-summary{margin:12px 18px;padding-left:16px;padding-right:16px}
    }
    @media (prefers-reduced-motion:reduce){
      *{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}
      .js .cat{opacity:1!important;transform:none!important}
    }
"""

SCRIPT = r"""
    (function(){
      var cards=[].slice.call(document.querySelectorAll('.paper'));
      var cats=[].slice.call(document.querySelectorAll('.cat'));
      var search=document.getElementById('search');
      var countEl=document.getElementById('rcount');
      var newBtn=document.getElementById('toggleNew');
      var chips=[].slice.call(document.querySelectorAll('.chip'));
      var empty=document.getElementById('empty');
      var total=cards.length;
      var q='', activeTag=null, onlyNew=false;

      function visible(c){
        if(onlyNew && c.className.indexOf('is-new')===-1) return false;
        if(activeTag){ var t=(c.getAttribute('data-tags')||'').split('|'); if(t.indexOf(activeTag)===-1) return false; }
        if(q && (c.getAttribute('data-search')||'').indexOf(q)===-1) return false;
        return true;
      }
      function apply(){
        var vis=0, i, j;
        for(i=0;i<cards.length;i++){ var ok=visible(cards[i]); cards[i].classList.toggle('hidden',!ok); if(ok)vis++; }
        for(j=0;j<cats.length;j++){ var v=cats[j].querySelectorAll('.paper:not(.hidden)').length; cats[j].classList.toggle('hidden',v===0); if(v>0) cats[j].classList.add('in'); }
        countEl.textContent=vis+' / '+total+' 篇';
        empty.classList.toggle('show',vis===0);
      }
      search.addEventListener('input',function(e){q=e.target.value.trim().toLowerCase();apply();});
      search.addEventListener('keydown',function(e){if(e.key==='Escape'||e.keyCode===27){search.value='';q='';apply();}});
      newBtn.addEventListener('click',function(){onlyNew=!onlyNew;newBtn.classList.toggle('active',onlyNew);apply();});
      chips.forEach(function(ch){ch.addEventListener('click',function(){
        var t=ch.getAttribute('data-tag');
        if(activeTag===t){activeTag=null;ch.classList.remove('active');}
        else{activeTag=t;chips.forEach(function(c){c.classList.remove('active');});ch.classList.add('active');}
        apply();
      });});

      var links={};
      [].forEach.call(document.querySelectorAll('.toc-item'),function(a){links[a.getAttribute('href').slice(1)]=a;});
      if('IntersectionObserver' in window){
        var spy=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){var id=en.target.id;for(var k in links)links[k].classList.remove('active');if(links[id])links[id].classList.add('active');}});},{rootMargin:'-25% 0px -65% 0px'});
        cats.forEach(function(c){spy.observe(c);});
        var reveal=new IntersectionObserver(function(es){es.forEach(function(en){if(en.isIntersecting){en.target.classList.add('in');reveal.unobserve(en.target);}});},{rootMargin:'0px 0px -8% 0px'});
        cats.forEach(function(c){reveal.observe(c);});
      } else {
        cats.forEach(function(c){c.classList.add('in');});
      }

      var tt=document.getElementById('totop');
      window.addEventListener('scroll',function(){tt.classList.toggle('show',window.scrollY>640);},{passive:true});
      tt.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'});});
    })();
"""


def render_html(papers: list[dict], generated: str | None = None) -> str:
    """Render the full classification HTML.

    Layout = editorial "Archive" masthead + sticky toolbar (search / tag chips /
    only-new toggle) + sticky sidebar TOC (scroll-spy with proportional bars) +
    category sections of paper cards. Papers from the latest 5 digests are flagged
    ``is-new`` (sienna rail + NEW badge) to surface the most recent push.
    """
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
    all_dates = sorted({p["digest_date"] for p in papers})
    date_range = f"{all_dates[0]} ~ {all_dates[-1]}" if all_dates else ""
    day_count = len(all_dates)
    new_dates = set(all_dates[-5:]) if all_dates else set()
    new_count = sum(1 for p in papers if p["digest_date"] in new_dates)
    max_cat = max((len(by_cat[c]) for c in cat_order), default=1)

    # tag chips: most common non-generic tags
    tag_counter: Counter = Counter()
    for p in papers:
        for t in (p.get("tags") or []):
            if t and t.lower() not in {"arxiv", "小红书", "daily digest"}:
                tag_counter[t] += 1
    top_tags = tag_counter.most_common(14)
    chip_html = "".join(
        f'<button class="chip" data-tag="{esc(t)}" type="button">{esc(t)} '
        f'<span class="cn">{cnt}</span></button>'
        for t, cnt in top_tags
    )

    # sidebar TOC with proportional bars
    toc_items = []
    for i, c in enumerate(cat_order):
        n = len(by_cat[c])
        pct = round(n * 100 / max_cat)
        toc_items.append(
            f'<a class="toc-item" href="#cat-{i}"><span class="tn">{esc(c)}</span>'
            f'<span class="tc">{n}</span><span class="bar"><i style="width:{pct}%"></i></span></a>'
        )

    def card_html(p: dict) -> str:
        tags = p.get("tags") or ["arxiv"]
        tag_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags)
        is_new = p["digest_date"] in new_dates
        new_cls = " is-new" if is_new else ""
        new_flag = (
            '<span class="new-flag" title="近 5 期 Digest 新增">NEW</span>'
            if is_new else ""
        )
        search_idx = esc(
            " ".join([p.get("title", ""), p.get("one_line", ""), " ".join(tags),
                      p.get("arxiv_id", ""), p.get("authors", "")]).lower()
        )
        data_tags = esc("|".join(tags))
        authors_html = f'<span class="authors">{esc(p["authors"])}</span>' if p.get("authors") else ""
        one_html = f'<p class="one-line">{esc(p["one_line"])}</p>' if p.get("one_line") else ""
        detail_html = (
            f'<details class="detail-wrap"><summary>digest 详解</summary>'
            f'<p class="detail">{esc(p["detail"])}</p></details>'
            if p.get("detail") else ""
        )
        return (
            f'<article class="paper{new_cls}" data-search="{search_idx}" data-tags="{data_tags}" '
            f'data-date="{esc(p["digest_date"])}">'
            f'<div class="paper-top"><div class="tags">{tag_html}</div>'
            f'<div class="top-right">{new_flag}<span class="digest-date">{esc(p["digest_date"])}</span></div></div>'
            f'<h3 class="paper-title"><a href="{esc(p["arxiv_url"])}" target="_blank" rel="noopener">{esc(p["title"])}</a></h3>'
            f'<div class="paper-meta"><span class="arxiv-id"><a href="{esc(p["arxiv_url"])}" target="_blank" rel="noopener">arXiv:{esc(p["arxiv_id"])}</a></span>{authors_html}</div>'
            f'{one_html}{detail_html}'
            f'<div class="links"><a class="btn" href="{esc(p["arxiv_url"])}" target="_blank" rel="noopener">Abstract</a>'
            f'<a class="btn btn-pdf" href="{esc(p["pdf_url"])}" target="_blank" rel="noopener">PDF</a></div>'
            f'</article>'
        )

    sections = []
    for i, c in enumerate(cat_order):
        items = sorted(by_cat[c], key=lambda x: (x["digest_date"], x["title"]), reverse=True)
        cards = "".join(card_html(p) for p in items)
        new_in_cat = sum(1 for p in items if p["digest_date"] in new_dates)
        new_bit = f'<span class="cat-new">+{new_in_cat} 近期新增</span>' if new_in_cat else ""
        sections.append(
            f'<section class="cat" id="cat-{i}">'
            f'<div class="cat-head"><div><span class="cat-num">§ {i + 1:02d} · {len(items)} entries</span>'
            f'<h2>{esc(c)}</h2></div>'
            f'<div class="cat-count">{len(items)}<span class="u">篇</span>{new_bit}</div></div>'
            f'<div class="cat-summary"><div class="lab">类别综述</div><p>{esc(summaries[c])}</p></div>'
            f'<div class="papers">{cards}</div>'
            f'</section>'
        )

    month_c = Counter(p["digest_date"][:7] for p in papers)
    month_bits = " · ".join(f"{m}: {month_c[m]}" for m in sorted(month_c))

    stat_row = (
        '<div class="stat-row">'
        f'<div class="stat"><div class="k">{len(papers)}<span class="unit">篇</span></div><div class="l">论文总数</div></div>'
        f'<div class="stat"><div class="k">{len(cat_order)}<span class="unit">类</span></div><div class="l">主题类别</div></div>'
        f'<div class="stat"><div class="k">{day_count}<span class="unit">期</span></div><div class="l">Digest 期数</div></div>'
        f'<div class="stat"><div class="k">+{new_count}<span class="unit">新</span></div><div class="l">近 5 期新增</div></div>'
        '</div>'
    )

    return f"""<!-- index: arXiv 每日论文全量分类整理 | {generated} | 对 yzbcs.github.io/study 全部 Daily Digest 中的 arXiv 论文按主题分类并撰写类别综述 -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="对 yzbcs.github.io/study 全部 Daily Digest 中的 arXiv 论文按主题分类并撰写类别综述（{date_range}，{len(papers)} 篇）">
  <title>arXiv 每日论文全量分类整理 · {esc(date_range)}</title>
  <!-- Fraunces self-hosted in fonts/ (China-safe: same origin as the page, no Google Fonts dependency); CJK / body / mono use high-quality system stacks -->
  <style>
{STYLES}
  </style>
</head>
<body>
  <script>document.documentElement.classList.add('js')</script>
  <div class="wrap">
    <header class="masthead">
      <div class="watermark" aria-hidden="true">arxiv</div>
      <div class="eyebrow">Daily Digest · Full Archive Classification</div>
      <h1>arXiv 每日论文<br>全量分类整理</h1>
      <p class="lede">从来源 <strong>yzbcs.github.io/study</strong> 的<strong>全部</strong> Daily Digest 中提取 arXiv 论文（不含小红书笔记），按 {len(cat_order)} 个主题归类，并为每一类撰写内容综述。</p>
      {stat_row}
      <div class="month-line">按月篇数 · {esc(month_bits)}　|　时间窗 {esc(date_range)}</div>
      <p class="src-note">数据来源 <a href="https://yzbcs.github.io/study/" target="_blank" rel="noopener">yzbcs.github.io/study</a> · 索引 <a href="https://raw.githubusercontent.com/yzbcs/yzbcs.github.io/master/study/data.json" target="_blank" rel="noopener">study/data.json</a> · 分类依据为 digest 卡片 tags、标题与中文一句话/详解（未读 PDF 全文）。详解默认折叠；同一 arXiv id 多日出现时保留最近一次记录。</p>
    </header>

    <div class="toolbar">
      <label class="search">
        <svg class="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="search" type="search" placeholder="搜索 标题 / 一句话 / arXiv id / 作者 …" autocomplete="off" aria-label="搜索论文">
      </label>
      <div class="tagbar">{chip_html}</div>
      <button class="toggle-new" id="toggleNew" type="button"><span class="dot"></span>仅看新增</button>
      <span class="result-count" id="rcount">{len(papers)} / {len(papers)} 篇</span>
    </div>

    <div class="layout">
      <aside class="toc" aria-label="类别目录">
        <h3>类别目录</h3>
        <div class="toc-list">{''.join(toc_items)}</div>
      </aside>
      <main class="main">
        {''.join(sections)}
        <div class="empty" id="empty">没有匹配的论文 — 试试其他关键词，或清除筛选条件。</div>
      </main>
    </div>

    <p class="footer">Full archive from live digests · arXiv only · {len(papers)} papers across {day_count} digests · yzbcs.github.io/research</p>
  </div>
  <button class="totop" id="totop" type="button" aria-label="回到顶部">↑</button>
  <script>
{SCRIPT}
  </script>
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
