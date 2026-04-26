#!/usr/bin/env python3
"""
Reddit Monitor Starter Kit
===========================
Scrapes Reddit for any keywords, optionally analyzes with Claude AI,
and sends a daily HTML email digest to yourself and your team.

Before running: fill in the CONFIG block below (lines 37-44).

Quickstart:
  1. pip install -r requirements.txt
  2. cp .env.example .env  and fill in your values
  3. python reddit_monitor.py              # run + preview email in browser
  4. python reddit_monitor.py --send       # run + actually send email
  5. Add to cron for daily runs (see README.md)
"""

import argparse
import gzip
import json
import logging
import logging.handlers
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Logger — writes to both stdout AND output/reddit_monitor.log so cron failures
# are always captured even when you're not watching the terminal.
def _setup_logger(output_dir: str = "output") -> logging.Logger:
    Path(output_dir).mkdir(exist_ok=True)
    log = logging.getLogger("reddit_monitor")
    if log.handlers:
        return log  # already configured (e.g. called twice in tests)
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    # File handler — DEBUG and above
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(output_dir, "reddit_monitor.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB per file
        backupCount=3,              # keep .log, .log.1, .log.2, .log.3
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)
    # Console handler — INFO and above (keeps terminal readable)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    return log

log = _setup_logger()

# ═══════════════════════════════════════════════════════════════════════════════
#  ★ CONFIGURE THESE — the only block you need to edit ★
# ═══════════════════════════════════════════════════════════════════════════════

TOPIC       = "YOUR TOPIC HERE"           # e.g. "Swiggy complaints", "UPI issues"
KEYWORDS    = ["keyword 1", "keyword 2"]  # what to search for (OR logic)
SUBREDDITS  = ["subreddit1", "subreddit2"]  # e.g. ["india", "bangalore", "mumbai"]
LIMIT       = 25                          # max posts per subreddit (25 is a good default)
TIME_FILTER = "week"                      # how far back: day | week | month | year | all
OUTPUT_DIR  = "output"                    # folder where previews + JSON are saved

# AI model — Haiku is the right default for daily digests: fast, cheap, capable.
# Upgrade if you need deeper analysis across hundreds of posts.
#   claude-haiku-4-5-20251001 → default — fast, ~20x cheaper than Opus
#   claude-sonnet-4-6         → stronger reasoning, ~4x cheaper than Opus
#   claude-opus-4-6           → most capable, use for complex multi-topic analysis
MODEL = "claude-haiku-4-5-20251001"

# ═══════════════════════════════════════════════════════════════════════════════
# Examples:
#
# Swiggy brand monitoring:
#   TOPIC      = "Swiggy mentions"
#   KEYWORDS   = ["Swiggy", "swiggy app", "swiggy delivery"]
#   SUBREDDITS = ["india", "bangalore", "mumbai", "delhi"]
#
# Competitor tracking:
#   TOPIC      = "Zomato pulse"
#   KEYWORDS   = ["Zomato", "food delivery app"]
#   SUBREDDITS = ["india", "bangalore"]
#
# Quick commerce:
#   TOPIC      = "quick commerce"
#   KEYWORDS   = ["Blinkit", "Zepto", "Swiggy Instamart", "quick commerce"]
#   SUBREDDITS = ["india", "bangalore", "mumbai"]
#
# UPI / payments:
#   TOPIC      = "UPI issues"
#   KEYWORDS   = ["UPI failed", "UPI down", "payment failed"]
#   SUBREDDITS = ["india", "IndiaInvestments", "personalfinanceindia"]
# ═══════════════════════════════════════════════════════════════════════════════

_PLACEHOLDER_TOPIC    = "YOUR TOPIC HERE"
_PLACEHOLDER_KEYWORDS = ["keyword 1", "keyword 2"]
_PLACEHOLDER_SUBS     = ["subreddit1", "subreddit2"]


# ───────────────────────────────────────────────────────────────────────────────
#  REDDIT SCRAPER
# ───────────────────────────────────────────────────────────────────────────────

# Proper Reddit-style User-Agent — generic Mozilla strings get flagged faster
_HEADERS = {
    "User-Agent": "pc:reddit_intelligence_digest:v1.0 (by /u/reddit_monitor_bot)",
    "Accept-Encoding": "gzip",
    "Accept": "application/json",
}
_DELAY = 1.5  # seconds between requests

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class Post:
    id:           str
    title:        str
    body:         str
    url:          str
    subreddit:    str
    author:       str
    score:        int
    num_comments: int
    created_utc:  float
    top_comments: list[str] = field(default_factory=list)

    @property
    def date(self) -> str:
        return datetime.fromtimestamp(self.created_utc).strftime("%Y-%m-%d")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "body": self.body[:400], "url": self.url,
            "subreddit": self.subreddit, "author": self.author,
            "score": self.score, "num_comments": self.num_comments,
            "date": self.date, "top_comments": self.top_comments,
        }


def _get(url: str, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
                raw = resp.read()
                # Handle gzip-compressed responses
                if resp.info().get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 10 * (attempt + 1)
                log.warning(f"Rate limited (429) — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _fetch_comments(subreddit: str, post_id: str, n: int = 3) -> list[str]:
    comments = []
    try:
        url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?limit={n}"
        data = _get(url)
        time.sleep(_DELAY)
        if len(data) >= 2:
            for child in data[1]["data"]["children"][:n]:
                body = child["data"].get("body", "")
                if body and body not in ("[deleted]", "[removed]"):
                    comments.append(body[:300])
    except Exception:
        pass
    return comments


def scrape(subreddits: list[str], keywords: list[str], limit: int, time_filter: str) -> list[Post]:
    all_posts, seen = [], set()

    for sub in subreddits:
        query = " OR ".join(f'"{kw}"' for kw in keywords)
        params = urllib.parse.urlencode({
            "q": query, "sort": "relevance", "t": time_filter,
            "limit": min(limit, 100), "restrict_sr": "true",
        })
        url = f"https://www.reddit.com/r/{sub}/search.json?{params}"
        try:
            data = _get(url)
            time.sleep(_DELAY)
        except Exception as e:
            log.warning(f"Skipping r/{sub}: {e}")
            continue

        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            pid = p.get("id", "")
            if pid in seen:
                continue
            seen.add(pid)
            comments = _fetch_comments(sub, pid)
            all_posts.append(Post(
                id=pid, title=p.get("title", ""),
                body=p.get("selftext", "") or "",
                url=f"https://reddit.com{p.get('permalink', '')}",
                subreddit=sub, author=p.get("author", "[deleted]"),
                score=p.get("score", 0), num_comments=p.get("num_comments", 0),
                created_utc=p.get("created_utc", 0), top_comments=comments,
            ))

    all_posts.sort(key=lambda p: p.score, reverse=True)
    return all_posts


# ───────────────────────────────────────────────────────────────────────────────
#  HISTORY — tracks sentiment + themes across runs for trending and recurrence
# ───────────────────────────────────────────────────────────────────────────────

def _load_history(output_dir: str) -> list[dict]:
    path = os.path.join(output_dir, "history.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save_history(analysis: dict, post_count: int, output_dir: str) -> None:
    history = _load_history(output_dir)
    history.append({
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "time":      datetime.now().strftime("%H:%M"),
        "sentiment": analysis.get("overall_sentiment", "unknown"),
        "score":     analysis.get("sentiment_score", 0),
        "themes":    [t["theme"] for t in analysis.get("key_themes", [])],
        "posts":     post_count,
    })
    history = history[-90:]  # keep last 90 runs
    Path(output_dir).mkdir(exist_ok=True)
    with open(os.path.join(output_dir, "history.json"), "w") as f:
        json.dump(history, f, indent=2)


def get_trend(output_dir: str) -> dict:
    """Compare today's sentiment against the previous run and surface recurring themes.

    Always called BEFORE _save_history(), so history contains only past runs.
    history[-1] is therefore the most recent previous run.
    """
    history = _load_history(output_dir)
    if not history:
        return {"delta": None, "previous_score": None, "previous_date": None, "recurring_themes": set()}

    prev       = history[-1]  # most recent past run
    all_themes = [t for run in history[-8:] for t in run.get("themes", [])]  # last 8 runs

    # A theme is RECURRING if it appeared in at least 2 of the last 8 runs
    from collections import Counter
    counts    = Counter(all_themes)
    recurring = {theme for theme, n in counts.items() if n >= 2}

    return {
        "delta":           None,  # populated after current run's score is known
        "previous_score":  prev.get("score"),
        "previous_date":   prev.get("date"),
        "recurring_themes": recurring,
    }


# ───────────────────────────────────────────────────────────────────────────────
#  SEEN IDs — filters posts already sent in a previous run
# ───────────────────────────────────────────────────────────────────────────────

def _load_seen_ids(output_dir: str) -> set[str]:
    path = os.path.join(output_dir, "seen_ids.txt")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {line.strip() for line in f if line.strip()}


def _save_seen_ids(post_ids: list[str], output_dir: str) -> None:
    Path(output_dir).mkdir(exist_ok=True)
    path = os.path.join(output_dir, "seen_ids.txt")
    existing = _load_seen_ids(output_dir)
    all_ids = existing | set(post_ids)
    # Keep last 5000 IDs to prevent the file growing forever
    with open(path, "w") as f:
        f.write("\n".join(list(all_ids)[-5000:]))


def filter_new_posts(posts: list[Post], output_dir: str) -> tuple[list[Post], int]:
    """Remove posts already seen in previous runs. Returns (new_posts, skipped_count)."""
    seen = _load_seen_ids(output_dir)
    new_posts = [p for p in posts if p.id not in seen]
    return new_posts, len(posts) - len(new_posts)


# ───────────────────────────────────────────────────────────────────────────────
#  CLAUDE ANALYSIS  (optional — skipped gracefully if no API key)
# ───────────────────────────────────────────────────────────────────────────────

def _robust_json_parse(text: str) -> dict | None:
    """Extract JSON from Claude's response even if there's preamble or trailing text."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Slice between first { and last }
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None


def analyze_with_claude(
    posts: list[Post],
    keywords: list[str],
    topic: str,
    known_themes: list[str] | None = None,
) -> dict | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.info("No ANTHROPIC_API_KEY — skipping AI analysis (raw digest only)")
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic package not installed — skipping AI analysis")
        return None

    client = Anthropic(api_key=api_key)

    posts_text = "\n".join(
        f"[POST {i}] r/{p.subreddit} | Score:{p.score}\n"
        f"Title: {p.title}\n"
        f"Body: {p.body[:300]}\n"
        f"Top comment: {p.top_comments[0][:200] if p.top_comments else 'none'}\n"
        for i, p in enumerate(posts[:40], 1)
    )

    # Inject vocabulary from recent runs so Claude reuses existing theme names.
    # This prevents RECURRING badge drift (e.g. "Login Issues" vs "Auth Problems").
    known_themes_block = ""
    if known_themes:
        theme_list = ", ".join(f'"{t}"' for t in known_themes[:20])
        known_themes_block = f"""
<known_themes>
These theme names appeared in recent runs. If the same issue is present today, reuse the exact name rather than inventing a new label:
{theme_list}
</known_themes>
"""

    # XML tags keep instructions cleanly separated from messy Reddit data.
    # Few-shot example anchors the format for recommended_actions specifically
    # so Claude returns specific actions, not generic advice.
    prompt = f"""You are a Senior Market Analyst. Analyze the following Reddit posts about "{topic}".

<instructions>
1. Evaluate the overall tone and sentiment of the discussion.
2. Identify recurring themes — surface what people are actually talking about, not generic categories.
3. For recommended_actions, be specific and actionable — not "monitor the situation" but "do X because Y".
4. Extract real quotes from the posts for notable_quotes.
5. Output ONLY valid JSON — no preamble, no explanation.
</instructions>
{known_themes_block}

<example_output>
{{
  "summary": "Users are reporting widespread checkout failures on the Android app, primarily affecting UPI payments. Frustration is high with several mentions of switching to competitors.",
  "overall_sentiment": "negative",
  "sentiment_score": -0.75,
  "key_themes": [
    {{"theme": "Checkout failures", "description": "UPI payments timing out at the final step", "frequency": "high"}},
    {{"theme": "Competitor switching", "description": "Users threatening to move to Zomato", "frequency": "medium"}}
  ],
  "top_concerns": ["Payment failures with no refund clarity", "No in-app error messaging when UPI fails"],
  "notable_quotes": ["Tried 3 times, money deducted but order not placed"],
  "recommended_actions": ["Audit the UPI payment gateway timeout settings — posts suggest failures spike after 11 PM", "Add a real-time order status page so users don't need to call support"]
}}
</example_output>

<posts>
{posts_text}
</posts>

Return ONLY valid JSON matching the structure above."""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _robust_json_parse(resp.content[0].text)
        if result is None:
            log.error("Claude returned unparseable response — skipping analysis")
        return result
    except Exception as e:
        log.error(f"Claude analysis failed: {e}")
        return None


# ───────────────────────────────────────────────────────────────────────────────
#  EMAIL BUILDER
# ───────────────────────────────────────────────────────────────────────────────

def build_email(
    posts: list[Post],
    analysis: dict | None,
    topic: str,
    subreddits: list[str],
    trend: dict | None = None,
) -> tuple[str, str, str]:
    """Returns (subject, html, plain_text)."""
    date_str = datetime.now().strftime("%d %b %Y")
    subject  = f"[Reddit Monitor] {topic} digest — {date_str} ({len(posts)} posts)"

    analysis_html = ""
    plain_sections = []
    recurring_themes = (trend or {}).get("recurring_themes", set())

    if analysis:
        score     = analysis.get("sentiment_score", 0)
        bar_pct   = int((score + 1) / 2 * 100)
        bar_color = "#EF4444" if score < -0.3 else ("#F59E0B" if score < 0.3 else "#22C55E")
        overall   = analysis.get("overall_sentiment", "N/A").upper()

        # Trend delta badge
        trend_html = ""
        if trend and trend.get("previous_score") is not None:
            delta     = score - trend["previous_score"]
            direction = "↑ Improving" if delta > 0.05 else ("↓ Worsening" if delta < -0.05 else "→ Stable")
            dt_color  = "#22C55E" if delta > 0.05 else ("#EF4444" if delta < -0.05 else "#6B7280")
            trend_html = (
                f'<div style="margin-top:10px;font-size:13px;color:{dt_color};font-weight:600">'
                f'{direction} vs last run ({trend["previous_date"]}) &nbsp;'
                f'<span style="font-weight:400;color:#6B7280">({delta:+.2f})</span></div>'
            )
            plain_sections.append(f"TREND: {direction} vs {trend['previous_date']} ({delta:+.2f})")

        themes_html = "".join(
            f'<tr><td style="padding:10px;font-weight:600">{t["theme"]}'
            # NEW/RECURRING badge next to theme name
            + (
                '<span style="margin-left:8px;background:#FEF3C7;color:#92400E;'
                'padding:2px 6px;border-radius:8px;font-size:10px;font-weight:700">RECURRING</span>'
                if t["theme"] in recurring_themes else
                '<span style="margin-left:8px;background:#EFF6FF;color:#1D4ED8;'
                'padding:2px 6px;border-radius:8px;font-size:10px;font-weight:700">NEW</span>'
            )
            + f'</td>'
            f'<td style="padding:10px;color:#4B5563">{t["description"]}</td>'
            f'<td style="padding:10px;text-align:center">'
            f'<span style="background:{"#EF4444" if t["frequency"]=="high" else "#F59E0B" if t["frequency"]=="medium" else "#22C55E"};'
            f'color:white;padding:3px 8px;border-radius:10px;font-size:11px">{t["frequency"].upper()}</span>'
            f'</td></tr>'
            for t in analysis.get("key_themes", [])
        )
        concerns_html = "".join(
            f'<li style="margin-bottom:8px;color:#374151">{c}</li>'
            for c in analysis.get("top_concerns", [])
        )
        actions_html = "".join(
            f'<li style="margin-bottom:8px;color:#374151">{a}</li>'
            for a in analysis.get("recommended_actions", [])
        )
        quotes_html = "".join(
            f'<blockquote style="background:#F9FAFB;border-left:3px solid #6B7280;'
            f'padding:10px 14px;margin:8px 0;font-size:13px;color:#374151;font-style:italic">{q}</blockquote>'
            for q in analysis.get("notable_quotes", [])
        )

        analysis_html = f"""
        <div style="background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
          <h2 style="margin:0 0 12px;color:#111827;font-size:16px">📋 AI Summary</h2>
          <p style="margin:0;color:#374151;line-height:1.7;font-size:14px">{analysis.get("summary","")}</p>
        </div>

        <div style="background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
          <h2 style="margin:0 0 16px;color:#111827;font-size:16px">💬 Sentiment: {overall}</h2>
          <div style="background:#F3F4F6;border-radius:8px;height:14px;overflow:hidden">
            <div style="background:{bar_color};height:100%;width:{bar_pct}%;border-radius:8px"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:11px;color:#9CA3AF;margin-top:4px">
            <span>Very Negative</span><span>Neutral</span><span>Very Positive</span>
          </div>
          {trend_html}
        </div>

        <div style="background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
          <h2 style="margin:0 0 16px;color:#111827;font-size:16px">🔍 Key Themes</h2>
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead><tr style="background:#F9FAFB">
              <th style="padding:10px;text-align:left;color:#6B7280">Theme</th>
              <th style="padding:10px;text-align:left;color:#6B7280">Description</th>
              <th style="padding:10px;text-align:center;color:#6B7280">Level</th>
            </tr></thead>
            <tbody>{themes_html}</tbody>
          </table>
        </div>

        <div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:12px;padding:20px;margin-bottom:20px">
          <h2 style="margin:0 0 12px;color:#C2410C;font-size:16px">⚡ Top Concerns</h2>
          <ul style="margin:0;padding-left:20px">{concerns_html}</ul>
        </div>

        <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;padding:20px;margin-bottom:20px">
          <h2 style="margin:0 0 12px;color:#15803D;font-size:16px">✅ Recommended Actions</h2>
          <ol style="margin:0;padding-left:20px">{actions_html}</ol>
        </div>

        {'<div style="background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)"><h2 style="margin:0 0 12px;color:#111827;font-size:16px">💬 Notable Quotes</h2>' + quotes_html + '</div>' if quotes_html else ''}
        """

        # Plain-text sections for spam filter fallback
        plain_sections += [
            f"SUMMARY\n{analysis.get('summary', '')}",
            f"SENTIMENT: {overall} ({score:+.2f})",
            "TOP CONCERNS:\n" + "\n".join(f"• {c}" for c in analysis.get("top_concerns", [])),
            "RECOMMENDED ACTIONS:\n" + "\n".join(f"{i}. {a}" for i, a in enumerate(analysis.get("recommended_actions", []), 1)),
        ]

    post_rows = "".join(
        f'<tr style="border-bottom:1px solid #F3F4F6">'
        f'<td style="padding:10px;color:#6B7280;font-size:12px">r/{p.subreddit}</td>'
        f'<td style="padding:10px"><a href="{p.url}" style="color:#F97316;text-decoration:none;font-size:13px">{p.title[:80]}</a></td>'
        f'<td style="padding:10px;text-align:center;font-size:13px;color:#374151">{p.score}</td>'
        f'<td style="padding:10px;text-align:center;font-size:12px;color:#6B7280">{p.date}</td>'
        f'</tr>'
        for p in posts[:30]
    )

    plain_post_list = "\n".join(
        f"[{p.score}] {p.title[:80]} — {p.url}" for p in posts[:20]
    )
    plain_sections.append(f"TOP POSTS:\n{plain_post_list}")

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F9FAFB">
<div style="max-width:680px;margin:0 auto;padding:24px">

  <div style="background:linear-gradient(135deg,#1E3A5F,#2563EB);border-radius:16px;padding:28px;margin-bottom:20px;text-align:center">
    <div style="color:white;font-size:22px;font-weight:800">Reddit Intelligence Digest</div>
    <div style="color:rgba(255,255,255,0.8);font-size:14px;margin-top:6px">
      {topic} · {date_str} · {len(posts)} posts from r/{", r/".join(subreddits[:3])}{"..." if len(subreddits) > 3 else ""}
    </div>
  </div>

  {analysis_html}

  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
    <h2 style="margin:0 0 16px;color:#111827;font-size:16px">📄 All Posts ({len(posts)} found)</h2>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#F9FAFB">
          <th style="padding:10px;text-align:left;font-size:12px;color:#6B7280">Subreddit</th>
          <th style="padding:10px;text-align:left;font-size:12px;color:#6B7280">Title</th>
          <th style="padding:10px;text-align:center;font-size:12px;color:#6B7280">Score</th>
          <th style="padding:10px;text-align:center;font-size:12px;color:#6B7280">Date</th>
        </tr>
      </thead>
      <tbody>{post_rows}</tbody>
    </table>
  </div>

  <div style="text-align:center;padding:16px;color:#9CA3AF;font-size:12px">
    Generated by Reddit Monitor · {date_str}<br>
    <span style="color:#D1D5DB">Powered by Reddit + {"Claude AI" if analysis else "Python"}</span>
  </div>

</div>
</body>
</html>"""

    plain_text = (
        f"Reddit Monitor — {topic}\n"
        f"{date_str} · {len(posts)} posts\n"
        f"{'='*50}\n\n"
        + "\n\n".join(plain_sections)
    )

    return subject, html, plain_text


# ───────────────────────────────────────────────────────────────────────────────
#  ALERT EMAIL — sent immediately when sentiment crosses the urgency threshold
# ───────────────────────────────────────────────────────────────────────────────

ALERT_THRESHOLD = -0.8  # sentiment score below this triggers an immediate alert

def build_alert_email(analysis: dict, topic: str, post_count: int) -> tuple[str, str, str]:
    """Returns (subject, html, plain_text) for the urgent alert email."""
    score   = analysis.get("sentiment_score", 0)
    date_str = datetime.now().strftime("%d %b %Y %H:%M")
    subject  = f"🚨 URGENT ALERT: {topic} sentiment critical — {date_str}"

    concerns = "".join(
        f'<li style="margin-bottom:8px;color:#991B1B">{c}</li>'
        for c in analysis.get("top_concerns", [])
    )
    actions = "".join(
        f'<li style="margin-bottom:8px;color:#374151">{a}</li>'
        for a in analysis.get("recommended_actions", [])
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#FEF2F2">
<div style="max-width:600px;margin:0 auto;padding:24px">
  <div style="background:#EF4444;border-radius:16px;padding:24px;text-align:center;margin-bottom:20px">
    <div style="font-size:40px">🚨</div>
    <div style="color:white;font-size:20px;font-weight:800;margin-top:8px">Sentiment Alert</div>
    <div style="color:rgba(255,255,255,0.85);font-size:14px;margin-top:4px">{topic} · {date_str}</div>
  </div>
  <div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px;border:2px solid #FCA5A5">
    <div style="font-size:28px;font-weight:800;color:#EF4444;text-align:center">{score:+.2f}</div>
    <div style="text-align:center;color:#6B7280;font-size:13px">Sentiment score (threshold: {ALERT_THRESHOLD})</div>
    <p style="margin:16px 0 0;color:#374151;font-size:14px;line-height:1.7">{analysis.get("summary","")}</p>
  </div>
  <div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:12px;padding:16px;margin-bottom:16px">
    <h3 style="margin:0 0 10px;color:#991B1B;font-size:14px">Top Concerns</h3>
    <ul style="margin:0;padding-left:20px">{concerns}</ul>
  </div>
  <div style="background:white;border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.08)">
    <h3 style="margin:0 0 10px;color:#15803D;font-size:14px">Recommended Actions</h3>
    <ol style="margin:0;padding-left:20px">{actions}</ol>
  </div>
  <div style="text-align:center;color:#9CA3AF;font-size:12px;padding:12px">
    Full digest will follow in today's scheduled email · {post_count} posts analyzed
  </div>
</div>
</body>
</html>"""

    plain_text = (
        f"🚨 URGENT ALERT: {topic}\n"
        f"Sentiment score: {score:+.2f} (threshold: {ALERT_THRESHOLD})\n\n"
        f"Summary: {analysis.get('summary','')}\n\n"
        f"Top concerns:\n" + "\n".join(f"• {c}" for c in analysis.get("top_concerns", [])) + "\n\n"
        f"Actions:\n" + "\n".join(f"{i}. {a}" for i, a in enumerate(analysis.get("recommended_actions", []), 1))
    )
    return subject, html, plain_text


# ───────────────────────────────────────────────────────────────────────────────
#  EMAIL SENDER
# ───────────────────────────────────────────────────────────────────────────────

def send_email(subject: str, html: str, plain_text: str) -> int:
    gmail_user     = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    recipients_raw = os.getenv("EMAIL_RECIPIENTS", "")

    if not gmail_user or not gmail_password:
        raise ValueError("Set GMAIL_USER and GMAIL_APP_PASSWORD in your .env file")
    if not recipients_raw:
        raise ValueError("Set EMAIL_RECIPIENTS in your .env file (comma-separated)")

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Reddit Monitor <{gmail_user}>"
    msg["To"]      = ", ".join(recipients)
    # plain must be attached first — email clients pick the last part they can render
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    return len(recipients)


# ───────────────────────────────────────────────────────────────────────────────
#  SAVE + PREVIEW
# ───────────────────────────────────────────────────────────────────────────────

def save_preview(html: str, plain_text: str, subject: str, output_dir: str) -> str:
    Path(output_dir).mkdir(exist_ok=True)
    preview_path = os.path.join(output_dir, "email_preview.html")
    subject_path = os.path.join(output_dir, "email_subject.txt")
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(subject_path, "w", encoding="utf-8") as f:
        f.write(subject)
    return preview_path


def save_raw(posts: list[Post], analysis: dict | None, keywords: list[str], subreddits: list[str], output_dir: str) -> str:
    Path(output_dir).mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"reddit_data_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": datetime.now().isoformat(),
            "keywords": keywords, "subreddits": subreddits,
            "total_posts": len(posts),
            "analysis": analysis,
            "posts": [p.to_dict() for p in posts],
        }, f, indent=2, ensure_ascii=False)
    return path


# ───────────────────────────────────────────────────────────────────────────────
#  MAIN
# ───────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reddit Monitor — scrape, analyze, and email a digest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python reddit_monitor.py                                   # preview in browser
  python reddit_monitor.py --send                            # send email
  python reddit_monitor.py --no-ai                           # skip Claude analysis
  python reddit_monitor.py --no-dedup                        # include already-seen posts
  python reddit_monitor.py --topic "UPI" --keywords "UPI" "NPCI" --subreddits india
        """,
    )
    parser.add_argument("--send",       action="store_true", help="Send email after building it")
    parser.add_argument("--no-ai",      action="store_true", help="Skip Claude AI analysis")
    parser.add_argument("--no-dedup",   action="store_true", help="Skip seen-ID filtering (include all posts)")
    parser.add_argument("--topic",      help="Override TOPIC from config")
    parser.add_argument("--keywords",   nargs="+", help="Override keywords from config")
    parser.add_argument("--subreddits", nargs="+", help="Override subreddits from config")
    parser.add_argument("--time",       default=TIME_FILTER, choices=["day","week","month","year","all"])
    parser.add_argument("--limit",      type=int, default=LIMIT)
    parser.add_argument("--output",     default=OUTPUT_DIR)
    args = parser.parse_args()

    # Resolve effective values (CLI overrides config block)
    topic      = args.topic      or TOPIC
    keywords   = args.keywords   or KEYWORDS
    subreddits = args.subreddits or SUBREDDITS

    # Guard: catch unconfigured placeholders before wasting time scraping
    if (topic == _PLACEHOLDER_TOPIC and not args.topic) \
            or keywords == _PLACEHOLDER_KEYWORDS \
            or subreddits == _PLACEHOLDER_SUBS:
        log.error("Script not configured — fill in TOPIC, KEYWORDS, SUBREDDITS in the config block")
        print("\n⚠  You haven't configured the script yet.")
        print("   Open reddit_monitor.py and fill in the CONFIG block at the top:")
        print('     TOPIC      = "your topic"')
        print('     KEYWORDS   = ["keyword1", "keyword2"]')
        print('     SUBREDDITS = ["india", "bangalore"]')
        print("\n   See the examples in the config block for inspiration.\n")
        return

    log.info(f"Starting — topic={topic!r} keywords={keywords} subreddits={subreddits} time={args.time} model={MODEL}")

    # Step 1: Scrape
    log.info("[1/5] Scraping Reddit...")
    posts = scrape(subreddits, keywords, args.limit, args.time)
    if not posts:
        log.warning("No posts found — try different keywords, subreddits, or a longer time range")
        return
    log.info(f"Found {len(posts)} unique posts")

    # Step 2: Deduplicate against previous runs
    if not args.no_dedup:
        posts, skipped = filter_new_posts(posts, args.output)
        log.info(f"{skipped} already seen — {len(posts)} new posts remaining")
        if not posts:
            log.info("Nothing new since last run. Use --no-dedup to include all posts.")
            return
    else:
        log.info("Deduplication skipped (--no-dedup)")

    # Load trend BEFORE analysis so get_trend sees only previous runs
    trend = get_trend(args.output)

    # Collect unique theme names from recent history to anchor Claude's vocabulary
    history = _load_history(args.output)
    recent_themes = list(dict.fromkeys(
        t for run in history[-8:] for t in run.get("themes", [])
    ))

    # Step 3: Claude analysis (optional)
    analysis = None
    if not args.no_ai:
        log.info(f"[3/5] Running Claude AI analysis (model={MODEL})...")
        analysis = analyze_with_claude(posts, keywords, topic, known_themes=recent_themes or None)
        if analysis:
            log.info(f"Analysis done — sentiment: {analysis.get('overall_sentiment','?')}")
            # Compute delta now that we have the current score
            score = analysis.get("sentiment_score", 0)
            if trend.get("previous_score") is not None:
                trend["delta"] = score - trend["previous_score"]
            # Persist this run to history (after get_trend so it only sees prior runs)
            _save_history(analysis, len(posts), args.output)
    else:
        log.info("[3/5] AI analysis skipped (--no-ai)")

    # Step 4: Save raw data
    raw_path = save_raw(posts, analysis, keywords, subreddits, args.output)
    log.info(f"[4/5] Raw data saved → {raw_path}")

    # Step 5: Build email + send or preview
    log.info("[5/5] Building email...")
    subject, html, plain_text = build_email(posts, analysis, topic, subreddits, trend=trend)
    preview_path = save_preview(html, plain_text, subject, args.output)
    log.info(f"Subject : {subject}")
    log.info(f"Preview → {preview_path}")

    if args.send:
        log.info("Sending email...")
        try:
            n = send_email(subject, html, plain_text)
            _save_seen_ids([p.id for p in posts], args.output)
            log.info(f"Sent to {n} recipients")
        except ValueError as e:
            log.error(f"Email config missing: {e} — add to .env")
        except Exception as e:
            log.error(f"Email failed: {e}")

        # Send urgent alert email if sentiment is critically negative
        if analysis and analysis.get("sentiment_score", 0) < ALERT_THRESHOLD:
            log.warning(f"Sentiment {analysis['sentiment_score']:.2f} below threshold {ALERT_THRESHOLD} — sending alert")
            try:
                alert_subj, alert_html, alert_plain = build_alert_email(analysis, topic, len(posts))
                send_email(alert_subj, alert_html, alert_plain)
                log.warning(f"ALERT sent — {alert_subj}")
            except Exception as e:
                log.error(f"Alert email failed: {e}")
    else:
        _save_seen_ids([p.id for p in posts], args.output)
        log.info("Run with --send to actually send the email. Opening preview in browser...")
        try:
            import subprocess as _sp
            _sp.Popen(["open", preview_path])
        except Exception:
            pass

    log.info(f"Done — {len(posts)} posts processed")
    if analysis:
        log.info(f"Sentiment: {analysis.get('overall_sentiment','?').upper()}")
        for theme in analysis.get("key_themes", [])[:3]:
            log.info(f"  • {theme['theme']} ({theme['frequency']})")
        if trend.get("delta") is not None:
            direction = "↑" if trend["delta"] > 0.05 else ("↓" if trend["delta"] < -0.05 else "→")
            log.info(f"Trend: {direction} {trend['delta']:+.2f} vs {trend['previous_date']}")


if __name__ == "__main__":
    main()
