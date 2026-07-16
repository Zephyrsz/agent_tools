#!/usr/bin/env python3
"""
Analyze raw X/Twitter post Markdown files with an OpenAI-compatible LLM API.

Default output layout follows the current Obsidian organization:
  X Clips/{Author}/raw/{post}.md
  X Clips/{Author}/anlysis/{post}.analysis.md

Usage:
  python3 agent_obsidian/analyze_x_raw_posts.py \
    --author-dir "/Users/rgwei/Documents/Obsidian Vault/X Clips/Andrew Ng"
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """/no_think
你是一个面向个人知识管理的 X/Twitter post 文档质量评估器。你的任务不是评价作者名气，也不是因为作者重要就给高分；你要判断这条 raw post 本身是否是一份值得沉淀的知识文档。

请严格输出 JSON，不要输出 Markdown，不要输出解释文本。
"""


USER_PROMPT_TEMPLATE = """请分析下面这条从 Obsidian raw 目录读取的 X/Twitter post。

评估目标：
1. 主要区分“文档质量”，而非作者重要性、账号影响力或话题热度。
2. 判断这条 post 本身是否有足够内容可供后续阅读、总结、沉淀和复用。
3. 给出结构化评分，方便之后批量过滤。

重要评分原则：
- 作者身份只能轻微影响 credibility，不能显著抬高 overall_score。
- 特别短的推文如果只是立场、口号、引用或单句判断，应该降低 insight_density、evidence_quality、standalone_value 和 summarization_value。
- 如果短推没有论证、案例、框架或具体机制，overall_score 通常不应超过 65；只有短但高度原创、可行动、可复用的内容才可例外。
- 长文不自动高分；必须有清晰结构、具体洞察和可复用价值。
- 不要因为主题是 AI 就高分；主题相关性只是门槛，文档质量才是核心。

评分指标，每项 1-5 分：
- topic_fit: 与用户关注主题（AI、产品、工程、学习、决策、知识管理）的匹配程度。
- substance_depth: 是否有充分展开，而不是一句话口号或浅层观点。
- insight_density: 单位篇幅内的新信息、新框架、新判断密度。
- evidence_quality: 是否提供案例、机制、因果链、数据、上下文或具体论据。
- structure_clarity: 是否结构清晰，便于摘录、拆解、转写成笔记。
- actionability: 是否能转化为行动、实验、写作主题、工作流或决策。
- durability: 是否具有长期参考价值，而不是短期新闻噪声。
- standalone_value: 离开作者名气和原始上下文后，内容本身是否仍然有价值。
- summarization_value: 是否值得进一步总结成 evergreen note。

请计算：
- overall_score: 0-100 的综合分。
- priority: high / medium / low。
- should_keep: true / false。
- suggested_action: read_deeply / summarize / archive / ignore。

输出 JSON schema：
{
  "one_line_summary": "一句话总结",
  "core_points": ["要点1", "要点2"],
  "why_it_matters": "为什么值得关注",
  "use_cases": ["可用于什么"],
  "limitations": ["局限或风险"],
  "scores": {
    "topic_fit": 1,
    "substance_depth": 1,
    "insight_density": 1,
    "evidence_quality": 1,
    "structure_clarity": 1,
    "actionability": 1,
    "durability": 1,
    "standalone_value": 1,
    "summarization_value": 1
  },
  "quality_rationale": "解释为什么这个分数能区分文档质量，特别说明是否因为内容过短而扣分",
  "overall_score": 0,
  "priority": "low",
  "should_keep": false,
  "suggested_action": "ignore",
  "tags": ["#tag"],
  "follow_up_questions": ["后续问题"]
}

Raw Markdown:
---
__RAW_MARKDOWN__
---
"""


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def call_llm(
    base_url: str,
    model: str,
    raw_markdown: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.replace("__RAW_MARKDOWN__", raw_markdown),
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API HTTP {exc.code}: {body}") from exc

    content = response_data["choices"][0]["message"].get("content", "")
    if not content:
        reasoning = response_data["choices"][0]["message"].get("reasoning_content", "")
        raise RuntimeError(f"LLM response content is empty. reasoning_content={reasoning[:500]}")
    return extract_json(content)


def score_value(score: Any) -> str:
    return str(score if score is not None else "")


def clamp_score(value: Any, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return maximum
    return min(numeric, maximum)


def extract_quoted_body(raw_markdown: str) -> str:
    lines: list[str] = []
    for line in raw_markdown.splitlines():
        if line.startswith("> "):
            lines.append(line[2:])
        elif line == ">":
            lines.append("")
    return "\n".join(lines).strip()


def apply_document_quality_adjustments(
    analysis: dict[str, Any],
    raw_markdown: str,
) -> dict[str, Any]:
    """Apply deterministic caps so very short posts are not over-scored."""
    body = extract_quoted_body(raw_markdown)
    word_count = len(re.findall(r"[A-Za-z0-9_]+", body))
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", body))
    substantive_units = word_count + cjk_count

    if substantive_units >= 90:
        return analysis

    scores = analysis.setdefault("scores", {})
    if substantive_units < 45:
        cap = 58
        depth_cap = 2
        evidence_cap = 2
        summary_cap = 3
        reason = (
            "Deterministic short-post adjustment: 正文很短，缺少充分展开；"
            "即使作者或主题重要，也按文档质量限制综合分。"
        )
    else:
        cap = 65
        depth_cap = 3
        evidence_cap = 3
        summary_cap = 3
        reason = (
            "Deterministic short-post adjustment: 正文偏短，论证与可摘录结构有限；"
            "综合分按短文档质量上限处理。"
        )

    analysis["overall_score"] = clamp_score(analysis.get("overall_score"), cap)
    if analysis["overall_score"] < 70 and analysis.get("priority") == "high":
        analysis["priority"] = "medium"
    if analysis["overall_score"] < 60:
        analysis["priority"] = "low"
        if analysis.get("suggested_action") == "summarize":
            analysis["suggested_action"] = "archive"

    for key, maximum in (
        ("substance_depth", depth_cap),
        ("evidence_quality", evidence_cap),
        ("standalone_value", 3),
        ("summarization_value", summary_cap),
    ):
        scores[key] = clamp_score(scores.get(key), maximum)

    existing = str(analysis.get("quality_rationale", "")).strip()
    analysis["quality_rationale"] = f"{existing}\n\n{reason}".strip()
    return analysis


def render_analysis_markdown(
    analysis: dict[str, Any],
    raw_path: Path,
    analysis_path: Path,
    model: str,
) -> str:
    raw_relative = Path("..") / "raw" / raw_path.name
    raw_link = raw_relative.as_posix()
    scores = analysis.get("scores", {})

    lines = [
        "---",
        f"source_raw: {raw_link}",
        f"llm_model: {model}",
        f"overall_score: {analysis.get('overall_score', '')}",
        f"priority: {analysis.get('priority', '')}",
        f"should_keep: {str(analysis.get('should_keep', '')).lower()}",
        f"suggested_action: {analysis.get('suggested_action', '')}",
        "---",
        "",
        f"# Analysis - {raw_path.stem}",
        "",
        f"Raw: [{raw_path.name}]({raw_link})",
        "",
        "## Verdict",
        "",
        f"- Overall score: {analysis.get('overall_score', '')}/100",
        f"- Priority: {analysis.get('priority', '')}",
        f"- Should keep: {analysis.get('should_keep', '')}",
        f"- Suggested action: {analysis.get('suggested_action', '')}",
        "",
        "## One Line Summary",
        "",
        str(analysis.get("one_line_summary", "")).strip(),
        "",
        "## Scores",
        "",
        "| Metric | Score |",
        "|---|---:|",
    ]

    for key in (
        "topic_fit",
        "substance_depth",
        "insight_density",
        "evidence_quality",
        "structure_clarity",
        "actionability",
        "durability",
        "standalone_value",
        "summarization_value",
    ):
        lines.append(f"| {key} | {score_value(scores.get(key))} |")

    lines.extend(
        [
            "",
            "## Quality Rationale",
            "",
            str(analysis.get("quality_rationale", "")).strip(),
        ]
    )

    sections = [
        ("Core Points", analysis.get("core_points", [])),
        ("Use Cases", analysis.get("use_cases", [])),
        ("Limitations", analysis.get("limitations", [])),
        ("Follow Up Questions", analysis.get("follow_up_questions", [])),
        ("Tags", analysis.get("tags", [])),
    ]

    lines.extend(["", "## Why It Matters", "", str(analysis.get("why_it_matters", "")).strip()])

    for title, items in sections:
        lines.extend(["", f"## {title}", ""])
        if isinstance(items, list):
            lines.extend(f"- {item}" for item in items)
        elif items:
            lines.append(str(items))

    lines.extend(
        [
            "",
            "## Raw Link",
            "",
            f"- Markdown link: [{raw_path.name}]({raw_link})",
            f"- Analysis file: `{analysis_path.name}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def analyze_author_dir(args: argparse.Namespace) -> list[Path]:
    author_dir = args.author_dir.expanduser().resolve()
    raw_dir = author_dir / "raw"
    if not raw_dir.is_dir():
        raise SystemExit(f"Raw directory does not exist: {raw_dir}")

    analysis_dir = author_dir / args.analysis_dir_name
    analysis_dir.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(raw_dir.glob("*.md"), reverse=args.newest_first)
    if args.limit:
        raw_files = raw_files[: args.limit]

    written: list[Path] = []
    for raw_path in raw_files:
        analysis_path = analysis_dir / f"{raw_path.stem}.analysis.md"
        if analysis_path.exists() and not args.overwrite:
            continue

        raw_markdown = raw_path.read_text(encoding="utf-8")
        analysis = call_llm(
            args.base_url,
            args.model,
            raw_markdown,
            args.temperature,
            args.max_tokens,
        )
        analysis = apply_document_quality_adjustments(analysis, raw_markdown)
        analysis_path.write_text(
            render_analysis_markdown(analysis, raw_path, analysis_path, args.model),
            encoding="utf-8",
        )
        written.append(analysis_path)
        print(analysis_path)

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze raw X posts into Obsidian markdown.")
    parser.add_argument("--author-dir", required=True, type=Path, help="Author directory containing raw/.")
    parser.add_argument("--base-url", default="http://thor:8000/", help="OpenAI-compatible API base URL.")
    parser.add_argument("--model", default="qwen35b", help="Model name.")
    parser.add_argument("--analysis-dir-name", default="anlysis", help="Analysis directory name.")
    parser.add_argument("--limit", type=int, help="Analyze at most this many raw files.")
    parser.add_argument("--newest-first", action="store_true", help="Analyze newer filenames first.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing analysis files.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1600)
    return parser.parse_args()


def main() -> int:
    analyze_author_dir(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
