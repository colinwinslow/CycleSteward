#!/usr/bin/env python3
"""Claude Code spend gauge + cross-repo ledger for the agentic-workflow-kit.

The Claude Code analogue of scripts/codex_spend.py. It renders, at `/startup` and
`/closeout`, a status box and a "gas gauge" footer that shows **tokens AND
dollars**:

* Tokens come from Claude Code's own session history (`~/.claude/projects/`),
  parsed by the sibling ``cc_token_usage.py``.
* Dollars are computed at render time from ``claude/pricing.json`` (Anthropic
  per-token list prices). Unlike Codex, Claude input is split into three disjoint
  categories — uncached input, cache-write, and cache-read — each with its own
  rate, so ``price_usage`` prices all three without any subtraction.

CROSS-REPO BY DESIGN. Every repo that installs the kit appends to ONE shared
ledger above all repos (default ``~/.agentic-workflow-kit/spend-ledger-claude.csv``,
override the directory with ``CC_SPEND_DIR``). The gauge reads the whole ledger,
so a developer working across several repos sees one combined daily/weekly/monthly
total, split per repo.

Kept SEPARATE from the Codex ledger (``spend-ledger.csv``) on purpose: the two
tools' token columns differ, so they live in distinct files in the same shared
directory rather than corrupting one CSV header.

Subcommands::

    cc_spend.py record --event startup     # session baseline + startup timing
    cc_spend.py mark-closeout              # stamp closeout start (run first)
    cc_spend.py record --event closeout    # session token delta + $ -> ledger
    cc_spend.py gauge --tier thin|thicker|dashboard|auto
    cc_spend.py dashboard                  # the /startup HEALTH box

Read-only and non-blocking by contract: any error degrades to one line + exit 0,
so the footer can never block a session. Money/credit figures live ONLY in this
ephemeral display and in the local ledger -- never in git commit trailers (the
kit's commit trailers forbid cost; see claude/token-tracking.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the hardened parsing engine (same scripts/ dir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cc_token_usage import (  # noqa: E402
    ModelKey,
    Usage,
    TOKEN_FIELDS,
    default_claude_dir,
    load_sessions,
    parse_utc_timestamp,
    usage_from_sessions,
    usage_total,
    utc_timestamp,
)
from cc_pricing import (  # noqa: E402
    DEFAULT_MAX_AGE_DAYS,
    PricingRefreshError,
    is_stale,
    pricing_age_days,
    refresh_pricing_file,
    resolve_rate,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_NAME = ROOT_DIR.name
DEFAULT_PRICING = ROOT_DIR / "claude" / "pricing.json"
DEFAULT_SESSION_MARKER = ROOT_DIR / "build" / "cc-token-usage" / "session-start.json"
SPEND_BASELINE = ROOT_DIR / "build" / "cc-token-usage" / "spend-baseline.json"
CLOSEOUT_MARKER = ROOT_DIR / "build" / "cc-token-usage" / "closeout-start.json"

LEDGER_SCHEMA = "claude-spend-ledger/v1"
BASELINE_SCHEMA = "claude-spend-baseline/v1"
CLOSEOUT_SCHEMA = "claude-closeout-timing/v1"

# Claude token columns differ from Codex: three input categories, no reasoning row.
LEDGER_FIELDS = [
    "schema", "ts", "day", "week", "repo", "event", "measure",
    "total_tokens", "input_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "output_tokens",
    "usd", "credits", "seconds", "models_json", "pricing_source",
]


# ── shared cross-repo location ────────────────────────────────────────────────

def spend_dir() -> Path:
    """The shared directory above every repo. ``CC_SPEND_DIR`` overrides it;
    default is ``~/.agentic-workflow-kit``. This is what makes the gauge
    function cross-repo."""
    override = os.environ.get("CC_SPEND_DIR")
    return Path(override).expanduser() if override else Path.home() / ".agentic-workflow-kit"


def ledger_path() -> Path:
    # Distinct from the Codex ledger (spend-ledger.csv) so the two tools' differing
    # token columns never collide in one CSV header.
    return spend_dir() / "spend-ledger-claude.csv"


# ── time helpers (local time; Monday-start week to match the $100/day x5) ──────

def local_now() -> datetime:
    return datetime.now().astimezone()


def day_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_days(now: datetime) -> set[str]:
    """Monday..today (local), inclusive -- the current calendar work week."""
    monday_offset = now.weekday()  # Mon=0
    days = set()
    for i in range(monday_offset + 1):
        days.add(day_str(datetime.fromtimestamp(now.timestamp() - i * 86400, now.tzinfo)))
    return days


def month_days(now: datetime) -> set[str]:
    return {f"{now.year}-{now.month:02d}-{d:02d}" for d in range(1, now.day + 1)}


# ── pricing ───────────────────────────────────────────────────────────────────

def load_pricing(path: Path = DEFAULT_PRICING) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("credit_usd", 0.04)
    data.setdefault("weekly_budget_usd", 500.0)
    data.setdefault("daily_budget_usd", 100.0)
    data.setdefault("models", {})
    data.setdefault("aliases", {})
    data.setdefault("default_model", None)
    return data


def _rate_for(key: ModelKey, pricing: dict[str, Any]) -> dict[str, float] | None:
    """Exact-or-alias rate for a model, or None when the model id is unknown."""
    name = (key.model or "").strip().lower()
    aliases = {k.lower(): v for k, v in pricing["aliases"].items()}
    models = {k.lower(): v for k, v in pricing["models"].items()}
    if name in aliases:
        name = str(aliases[name]).lower()
    # resolve_rate picks the window in effect today, so a published-but-future
    # rate change (e.g. an introductory price ending) applies on its own date
    # without anyone re-running a refresh.
    return resolve_rate(models.get(name))


def _default_rate(pricing: dict[str, Any]) -> dict[str, float] | None:
    models = {k.lower(): v for k, v in pricing["models"].items()}
    default = pricing.get("default_model")
    return resolve_rate(models.get(str(default).lower())) if default else None


def price_usage(usage: Usage, rate: dict[str, float]) -> float:
    """USD for one model's Usage. Claude reports the three input categories as
    DISJOINT counts (unlike Codex, where input_tokens was cache-inclusive), so
    each is priced directly with no subtraction."""
    return (
        usage.input_tokens / 1e6 * float(rate.get("input", 0.0))
        + usage.cache_creation_input_tokens / 1e6 * float(rate.get("cache_write", 0.0))
        + usage.cache_read_input_tokens / 1e6 * float(rate.get("cache_read", 0.0))
        + usage.output_tokens / 1e6 * float(rate.get("output", 0.0))
    )


def price_models(models: dict[ModelKey, Usage], pricing: dict[str, Any]) -> dict[str, Any]:
    """Returns {usd, credits, partial, priced_tokens, total_tokens}. ``partial``
    is True when any model lacked a price (tokens still counted, $ understated)."""
    usd = 0.0
    partial = False
    priced_tokens = 0
    total_tokens = 0
    for key, usage in models.items():
        total_tokens += usage.total_tokens
        rate = _rate_for(key, pricing)
        if rate is None:
            rate = _default_rate(pricing)
            partial = True
            if rate is None:
                continue
        usd += price_usage(usage, rate)
        priced_tokens += usage.total_tokens
    credit_usd = float(pricing.get("credit_usd") or 0.04)
    credits = usd / credit_usd if credit_usd else 0.0
    return {
        "usd": usd, "credits": credits, "partial": partial,
        "priced_tokens": priced_tokens, "total_tokens": total_tokens,
    }


# ── current Claude token snapshot for this repo ───────────────────────────────

def current_models(project_path: Path) -> dict[ModelKey, Usage]:
    try:
        sessions = load_sessions(default_claude_dir(), project_path)
    except (LookupError, OSError, FileNotFoundError):
        return {}
    return usage_from_sessions(sessions)


def models_to_jsonable(models: dict[ModelKey, Usage]) -> list[dict[str, Any]]:
    rows = []
    for key, usage in sorted(models.items(), key=lambda kv: kv[0].model):
        rows.append({
            "model": key.model,
            "usage": {field: getattr(usage, field) for field in TOKEN_FIELDS},
        })
    return rows


def models_from_jsonable(rows: Any) -> dict[ModelKey, Usage]:
    out: dict[ModelKey, Usage] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = ModelKey(model=str(row.get("model", "")))
        usage = row.get("usage") or {}
        out[key] = Usage(**{field: int(usage.get(field) or 0) for field in TOKEN_FIELDS})
    return out


def delta_models(now: dict[ModelKey, Usage], base: dict[ModelKey, Usage]) -> dict[ModelKey, Usage]:
    out: dict[ModelKey, Usage] = {}
    for key, usage in now.items():
        prior = base.get(key)
        out[key] = usage.subtract(prior) if prior else usage
    return {k: v for k, v in out.items() if not v.is_zero()}


# ── baseline + closeout markers (local, per-repo) ─────────────────────────────

def write_baseline(models: dict[ModelKey, Usage]) -> None:
    SPEND_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": BASELINE_SCHEMA,
        "started_at": utc_timestamp(),
        "models": models_to_jsonable(models),
    }
    SPEND_BASELINE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_baseline() -> dict[ModelKey, Usage]:
    try:
        payload = json.loads(SPEND_BASELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != BASELINE_SCHEMA:
        return {}
    return models_from_jsonable(payload.get("models"))


def write_closeout_marker() -> None:
    CLOSEOUT_MARKER.parent.mkdir(parents=True, exist_ok=True)
    CLOSEOUT_MARKER.write_text(
        json.dumps({"schema": CLOSEOUT_SCHEMA, "started_at": utc_timestamp()}, indent=2),
        encoding="utf-8",
    )


def elapsed_seconds(marker_path: Path, schema: str | None = None) -> float | None:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    started = payload.get("started_at") if isinstance(payload, dict) else None
    if not isinstance(started, str):
        return None
    try:
        start = parse_utc_timestamp(started)
    except ValueError:
        return None
    return max((datetime.now(timezone.utc) - start).total_seconds(), 0.0)


# ── ledger I/O ────────────────────────────────────────────────────────────────

def append_ledger(row: dict[str, Any]) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def read_ledger() -> list[dict[str, str]]:
    path = ledger_path()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def _f(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


# ── rendering primitives (ported from the Codex spend gauge) ──────────────────

EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
SPARK = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

# Max footer width (columns). Override per-machine with CC_FOOTER_WIDTH.
FOOTER_WIDTH = int(os.environ.get("CC_FOOTER_WIDTH") or 100)
REPO_NAME_FLOOR = 4  # never truncate a repo name below this many characters


def usd(n: float) -> str:
    return f"${float(n or 0):.2f}"


def fmt_tok(n: float) -> str:
    n = float(n or 0)
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return str(int(round(n)))


def fmt_credits(n: float) -> str:
    n = float(n or 0)
    if n >= 1e3:
        return f"{n / 1e3:.1f}k cr"
    return f"{int(round(n))} cr"


def bar(frac: float, cells: int = 20) -> str:
    f = max(0.0, min(1.0, float(frac or 0)))
    full = int(f * cells)
    part = round((f * cells - full) * 8)
    out = "█" * full + (EIGHTHS[part] if 0 <= part < len(EIGHTHS) else "")
    return out.ljust(cells, "░")[:cells]


def gauge_state(cost: float, cap: float) -> dict[str, Any]:
    pct = round((cost / cap) * 100) if cap > 0 else 0
    color = "red" if pct >= 80 else "amber" if pct >= 50 else "green"
    return {"pct": pct, "color": color, "warn": pct >= 80}


def pace_str(ratio: float | None) -> str:
    if ratio is None:
        return ""
    arrow = "↑" if ratio > 1.0 else "↓" if ratio < 1.0 else ""
    return f"{arrow}{ratio:.1f}×"


def time_trend(seconds: float | None, median: float | None) -> str:
    if seconds is None or median is None:
        return ""
    arrow = " ↑" if seconds > median * 1.05 else " ↓" if seconds < median * 0.95 else " ·"
    return f"{arrow} ({median:.1f}s)"


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARK[3] * len(values)
    return "".join(SPARK[min(7, int(((v - lo) / (hi - lo)) * 7.999))] for v in values)


def median_num(arr: list[float]) -> float | None:
    if not arr:
        return None
    s = sorted(arr)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def fit_rule(body: list[str], minimum: int = 0) -> str:
    return "─" * max(minimum, *(len(line) for line in body)) if body else "─" * minimum


def _truncate(name: str, cap: int) -> str:
    """First `cap` chars, with trailing separators stripped (api-gateway -> api-g)."""
    return name if len(name) <= cap else name[:cap].rstrip("-_. ")


def _common_cap(names: list[str], avail: int, floor: int) -> int:
    """Largest per-name length L (>= floor) such that the names fit in `avail`."""
    longest = max((len(n) for n in names), default=floor)
    best = floor
    for length in range(floor, longest + 1):
        if sum(min(len(n), length) for n in names) <= avail:
            best = length
        else:
            break
    return best


def fit_repo_split(by_repo: dict[str, float], budget: int, limit: int = 3,
                   floor: int = REPO_NAME_FLOOR, arrow: str = "← ",
                   sep: str = " · ") -> str:
    """Top-N repos by spend within `budget` columns, with common-length name
    truncation and a `(+K)` overflow marker. `budget <= 0` collapses to a count."""
    items = sorted(((n, v) for n, v in by_repo.items() if v > 0),
                   key=lambda kv: kv[1], reverse=True)
    if not items:
        return ""
    if budget <= 0:
        return f"{arrow}{len(items)} repos"
    for show_n in range(min(limit, len(items)), 0, -1):
        shown = items[:show_n]
        extra = len(items) - show_n
        extra_str = f" (+{extra})" if extra > 0 else ""
        overhead = (len(arrow) + sum(len(f" {usd(v)}") for _, v in shown)
                    + (show_n - 1) * len(sep) + len(extra_str))
        names = [n for n, _ in shown]
        avail = budget - overhead
        if avail < sum(min(len(n), floor) for n in names):
            continue
        cap = _common_cap(names, avail, floor)
        out = arrow + sep.join(f"{_truncate(n, cap)} {usd(v)}" for n, v in shown) + extra_str
        if len(out) <= budget:
            return out
    return f"{arrow}{len(items)} repos"


def repo_split(by_repo: dict[str, float], limit: int = 3) -> str:
    return fit_repo_split(by_repo, 10 ** 9, limit=limit)


def repos_used(by_repo: dict[str, float]) -> int:
    return len([v for v in by_repo.values() if v > 0])


def repos_suffix(count: int) -> str:
    if not count:
        return ""
    return f" · {count} repo" + ("s" if count != 1 else "")


# ── windowing over the ledger ─────────────────────────────────────────────────

def window_spend(rows: list[dict[str, str]], days: set[str]) -> dict[str, Any]:
    total_usd = 0.0
    total_tok = 0.0
    by_repo: dict[str, float] = {}
    for r in rows:
        if r.get("measure") != "session_delta" or r.get("day") not in days:
            continue
        total_usd += _f(r, "usd")
        total_tok += _f(r, "total_tokens")
        by_repo[r.get("repo", "?")] = by_repo.get(r.get("repo", "?"), 0.0) + _f(r, "usd")
    return {"usd": total_usd, "tokens": total_tok, "by_repo": by_repo}


def weekly_series(rows: list[dict[str, str]], now: datetime, weeks: int = 8) -> list[float]:
    by_week: dict[str, float] = {}
    for r in rows:
        if r.get("measure") != "session_delta":
            continue
        by_week[r.get("week", "")] = by_week.get(r.get("week", ""), 0.0) + _f(r, "usd")
    keys = sorted(k for k in by_week if k)
    cur = week_key(now)
    if cur not in by_week:
        keys.append(cur)
        by_week[cur] = by_week.get(cur, 0.0)
    keys = sorted(set(keys))[-weeks:]
    return [by_week.get(k, 0.0) for k in keys]


def pace_vs_median(rows: list[dict[str, str]], now: datetime) -> dict[str, Any]:
    by_week: dict[str, float] = {}
    for r in rows:
        if r.get("measure") != "session_delta":
            continue
        by_week[r.get("week", "")] = by_week.get(r.get("week", ""), 0.0) + _f(r, "usd")
    cur = week_key(now)
    this_week = by_week.get(cur, 0.0)
    priors = [v for k, v in by_week.items() if k and k != cur and v > 0]
    median = median_num(priors) if len(priors) >= 2 else None
    ratio = (this_week / median) if median and median > 0 else None
    return {"this_week": this_week, "median": median, "ratio": ratio}


def event_seconds(rows: list[dict[str, str]], event: str) -> list[float]:
    out = []
    for r in rows:
        if r.get("event") == event and r.get("seconds"):
            try:
                out.append(float(r["seconds"]))
            except ValueError:
                pass
    return out


def latest_closeout(rows: list[dict[str, str]]) -> dict[str, str] | None:
    closeouts = [r for r in rows if r.get("event") == "closeout"]
    return closeouts[-1] if closeouts else None


# ── gauge renderers ───────────────────────────────────────────────────────────

def render_thin(ctx: dict[str, Any]) -> list[str]:
    g = gauge_state(ctx["week_usd"], ctx["cap"])
    flag = " ⚠" if g["warn"] else ""
    pace = f" {pace_str(ctx['pace'])}" if ctx.get("pace") is not None else ""
    head = f"  week  {usd(ctx['week_usd'])} / {usd(ctx['cap'])}  {bar(ctx['week_usd'] / ctx['cap'])}  {g['pct']}%{flag}{pace}   "
    split = fit_repo_split(ctx["by_repo"], FOOTER_WIDTH - len(head))
    start_line = ""
    if ctx.get("startup_seconds") is not None:
        start_line = f"      startup {ctx['startup_seconds']:.1f}s{time_trend(ctx['startup_seconds'], ctx.get('startup_median'))}"
    rec = "✓" if ctx.get("reconcile_ok", True) else "✗"
    body = [
        (head + split).rstrip(),
        f"  session {fmt_tok(ctx['session_tok'])} · {usd(ctx['session_usd'])}{start_line}     reconcile {rec}{repos_suffix(ctx.get('repo_count', 0))}",
    ]
    rule = fit_rule(body)
    return [rule, *body, rule]


def render_thicker(ctx: dict[str, Any]) -> list[str]:
    cells = 20
    g = gauge_state(ctx["week_usd"], ctx["cap"])
    flag = " ⚠" if g["warn"] else ""
    prefix = f"  week  {usd(ctx['week_usd'])} / {usd(ctx['cap'])}  "
    dur = f" · {ctx['session_dur']}" if ctx.get("session_dur") else ""
    close_chunk = ""
    if ctx.get("closeout_seconds") is not None:
        close_chunk = f"   closeout {ctx['closeout_seconds']:.1f}s{time_trend(ctx['closeout_seconds'], ctx.get('closeout_median'))}"
    rec = "✓" if ctx.get("reconcile_ok", True) else "✗"
    body: list[str] = []
    median = ctx.get("median")
    if median is not None and median > 0:
        col = round(min(1.0, median / ctx["cap"]) * cells)
        body.append(" " * (len(prefix) + col) + f"▼ med {usd(median)}")
    week_head = (prefix + bar(ctx["week_usd"] / ctx["cap"], cells)
                 + f"  {g['pct']}%{flag} {pace_str(ctx.get('pace'))}   today {usd(ctx['today_usd'])}   ")
    today_split = fit_repo_split(ctx["today_by_repo"], FOOTER_WIDTH - len(week_head))
    body.append((week_head + today_split).rstrip())
    body.append(f"  session {fmt_tok(ctx['session_tok'])} · {usd(ctx['session_usd'])}{dur}{close_chunk}     reconcile {rec}{repos_suffix(ctx.get('repo_count', 0))}")
    rule = fit_rule(body)
    return [rule, *body, rule]


def render_dashboard(ctx: dict[str, Any], width: int = 64) -> list[str]:
    g = gauge_state(ctx["week_usd"], ctx["cap"])
    flag = " ⚠" if g["warn"] else ""
    top = "┌─ AI SPEND · all repos " + "─" * max(0, width - 24)
    bot = "└" + "─" * (width - 1)
    spark = sparkline(ctx.get("series", []))
    start_str = ""
    if ctx.get("startup_seconds") is not None:
        start_str = f"   startup {ctx['startup_seconds']:.1f}s{time_trend(ctx['startup_seconds'], ctx.get('startup_median'))}"
    repo_line = fit_repo_split(ctx["week_by_repo"], width - len("│  repos  "),
                               limit=4, arrow="") or "—"
    return [
        top,
        f"│  WEEK   {usd(ctx['week_usd'])} / {usd(ctx['cap'])}  {bar(ctx['week_usd'] / ctx['cap'], 18)}  {g['pct']}%{flag} {pace_str(ctx.get('pace'))}".rstrip(),
        f"│  {len(ctx.get('series', []))}-wk   {spark}",
        "│",
        f"│  today  {usd(ctx['today_usd']).ljust(9)} {fmt_tok(ctx['today_tok'])}",
        f"│  week   {usd(ctx['week_usd']).ljust(9)} {fmt_tok(ctx['week_tok'])}    {fmt_credits(ctx['week_credits'])}",
        f"│  month  {usd(ctx['month_usd']).ljust(9)} {fmt_tok(ctx['month_tok'])}",
        "│",
        f"│  daily soft cap {usd(ctx['daily_cap'])} · today {g_today(ctx)}",
        f"│  repos  {repo_line}",
        f"│  session {fmt_tok(ctx['session_tok'])} · {usd(ctx['session_usd'])}{start_str}",
        bot,
    ]


def g_today(ctx: dict[str, Any]) -> str:
    st = gauge_state(ctx["today_usd"], ctx["daily_cap"])
    return f"{st['pct']}%{' ⚠' if st['warn'] else ''}"


# ── HEALTH box (the /startup status surface) ──────────────────────────────────

LIGHT = {"green": "🟢", "amber": "🟡", "red": "🔴"}
DONE = "✅"
GATE_OPEN = "◻"


def _top(title: str, right: str, width: int) -> str:
    left = f"┌─ {title} "
    tail = f" {right} ─" if right else "─"
    fill = max(1, width - len(left) - len(tail) + 1)
    return left + "─" * fill + tail


def render_health_box(ctx: dict[str, Any], width: int = 74) -> list[str]:
    checks = ctx["checks"]
    lights = [c["light"] for c in checks.values()]
    if "red" in lights:
        verdict = (LIGHT["red"], "DECISION NEEDED")
    elif "amber" in lights:
        verdict = (LIGHT["green"], f"READY · {lights.count('amber')} {LIGHT['amber']} watch")
    else:
        verdict = (LIGHT["green"], "READY")

    label_w = max(len(k) for k in checks) + 2
    lines = [
        _top(f"claude /startup · {ctx['date']}", f"{verdict[0]} {verdict[1]}", width),
        "│" + (f"  → {ctx['packet']}" if ctx.get("packet") else "  → (set next packet in STATUS.md)"),
        "│",
    ]
    for label, cell in checks.items():
        note = f"   {LIGHT.get(cell.get('note_light'), '')} {cell['note']}" if cell.get("note") else ""
        lines.append("│" + f"  {label.ljust(label_w)}{LIGHT.get(cell['light'], '')} {cell['text']}{note}")
    lines.append("│")
    footer = f"  next → {ctx.get('next_link', 'STATUS.md')}"
    if ctx.get("detail"):
        footer += f"      full report → {ctx['detail']}"
    lines.append("│" + footer)
    lines.append("└" + "─" * (width - 1))
    return lines


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_record(args: argparse.Namespace) -> int:
    pricing = load_pricing(args.pricing)
    repo = args.repo or REPO_NAME
    now = local_now()
    models_now = current_models(_project_path(args))

    if args.event == "startup":
        write_baseline(models_now)
        secs = elapsed_seconds(args.session_marker)
        append_ledger({
            "schema": LEDGER_SCHEMA, "ts": utc_timestamp(), "day": day_str(now),
            "week": week_key(now), "repo": repo, "event": "startup", "measure": "timing",
            "total_tokens": 0, "seconds": f"{secs:.1f}" if secs is not None else "",
            "models_json": "[]", "pricing_source": "",
        })
        print(f"[cc-spend] startup recorded · repo={repo} · ledger={ledger_path()}")
        if secs is not None:
            print(f"[cc-spend] startup elapsed ~{secs:.1f}s")
        return 0

    # closeout
    base = read_baseline()
    delta = delta_models(models_now, base)
    priced = price_models(delta, pricing)
    total = usage_total(delta)
    secs = elapsed_seconds(args.closeout_marker)
    append_ledger({
        "schema": LEDGER_SCHEMA, "ts": utc_timestamp(), "day": day_str(now),
        "week": week_key(now), "repo": repo, "event": "closeout", "measure": "session_delta",
        "total_tokens": total.total_tokens, "input_tokens": total.input_tokens,
        "cache_creation_input_tokens": total.cache_creation_input_tokens,
        "cache_read_input_tokens": total.cache_read_input_tokens,
        "output_tokens": total.output_tokens,
        "usd": f"{priced['usd']:.4f}", "credits": f"{priced['credits']:.2f}",
        "seconds": f"{secs:.1f}" if secs is not None else "",
        "models_json": json.dumps(models_to_jsonable(delta), separators=(",", ":")),
        "pricing_source": str(args.pricing.name),
    })
    write_baseline(models_now)  # advance so post-closeout live spend = 0
    print(f"[cc-spend] closeout recorded · {fmt_tok(total.total_tokens)} tok · "
          f"{usd(priced['usd'])} (~{fmt_credits(priced['credits'])})"
          + (" · PARTIAL pricing" if priced["partial"] else ""))
    return 0


def cmd_mark_closeout(args: argparse.Namespace) -> int:
    write_closeout_marker()
    print("[cc-spend] closeout timer started")
    return 0


def _gauge_context(args: argparse.Namespace, tier: str) -> dict[str, Any]:
    pricing = load_pricing(args.pricing)
    cap = float(os.environ.get("CC_WEEKLY_BUDGET_USD") or pricing["weekly_budget_usd"])
    daily_cap = float(pricing["daily_budget_usd"])
    rows = read_ledger()
    now = local_now()
    week = window_spend(rows, week_days(now))
    today = window_spend(rows, {day_str(now)})
    month = window_spend(rows, month_days(now))
    pace = pace_vs_median(rows, now)

    if tier == "thicker":
        last = latest_closeout(rows)
        session_tok = _f(last, "total_tokens") if last else 0.0
        session_usd = _f(last, "usd") if last else 0.0
        session_dur = ""
    else:
        live = delta_models(current_models(_project_path(args)), read_baseline())
        priced = price_models(live, pricing)
        session_tok = float(usage_total(live).total_tokens)
        session_usd = priced["usd"]
        session_dur = ""

    startup_secs = event_seconds(rows, "startup")
    closeout_secs = event_seconds(rows, "closeout")
    return {
        "cap": cap, "daily_cap": daily_cap,
        "week_usd": week["usd"], "week_tok": week["tokens"], "by_repo": week["by_repo"],
        "week_by_repo": week["by_repo"], "today_usd": today["usd"], "today_tok": today["tokens"],
        "today_by_repo": today["by_repo"], "month_usd": month["usd"], "month_tok": month["tokens"],
        "week_credits": week["usd"] / float(pricing.get("credit_usd") or 0.04),
        "pace": pace["ratio"], "median": pace["median"],
        "session_tok": session_tok, "session_usd": session_usd, "session_dur": session_dur,
        "repo_count": repos_used(week["by_repo"]),
        "series": weekly_series(rows, now),
        "startup_seconds": startup_secs[-1] if startup_secs else None,
        "startup_median": median_num(startup_secs[:-1]) if len(startup_secs) >= 2 else None,
        "closeout_seconds": closeout_secs[-1] if closeout_secs else None,
        "closeout_median": median_num(closeout_secs[:-1]) if len(closeout_secs) >= 2 else None,
        "reconcile_ok": True,
    }


def cmd_gauge(args: argparse.Namespace) -> int:
    tier = (args.tier or "thin").lower()
    if tier == "auto":
        tier = "dashboard" if _first_of_day() else "thin"
    ctx = _gauge_context(args, tier)
    if tier == "thicker":
        lines = render_thicker(ctx)
    elif tier == "dashboard":
        lines = render_dashboard(ctx)
    else:
        lines = render_thin(ctx)
    for line in lines:
        print(line)
    return 0


def _first_of_day() -> bool:
    """Shared once-a-day latch across repos. Kept distinct from the Codex latch so
    the two tools don't suppress each other's daily dashboard."""
    latch = spend_dir() / "dashboard-shown-claude.txt"
    today = day_str(local_now())
    try:
        if latch.read_text(encoding="utf-8").strip() == today:
            return False
    except OSError:
        pass
    try:
        latch.parent.mkdir(parents=True, exist_ok=True)
        latch.write_text(today, encoding="utf-8")
    except OSError:
        pass
    return True


def cmd_dashboard(args: argparse.Namespace) -> int:
    now = local_now()
    pricing = load_pricing(args.pricing)
    daily_cap = float(pricing["daily_budget_usd"])
    checks: dict[str, dict[str, Any]] = {}

    behind, dirty = _git_drift()
    if behind > 0:
        checks["drift"] = {"light": "red", "text": f"behind {behind} — pull owed"}
    else:
        note = f"tree: {dirty} uncommitted" if dirty else ""
        checks["drift"] = {"light": "green", "text": "even (behind 0)",
                           "note": note, "note_light": "amber" if dirty else None}

    cfg = _read_config(args)
    tt = cfg.get("token_tracking")
    at = cfg.get("activity_tracking")
    routed = _hooks_routed()
    checks["tracking"] = {
        "light": "green" if tt else "amber",
        "text": (f"token {'on' if tt else 'off'} · activity {'on' if at else 'off'} · "
                 f"hooks {'routed' if routed else 'NOT routed'}"),
    }

    checks["spend"] = _spend_check(args, now, daily_cap)

    status_ok = (ROOT_DIR / "STATUS.md").exists()
    checks["sync"] = {"light": "green" if status_ok else "amber",
                      "text": "STATUS.md present" if status_ok else "STATUS.md missing"}

    ctx = {"date": day_str(now), "packet": args.packet or "", "checks": checks,
           "next_link": args.next or "STATUS.md", "detail": args.detail or ""}
    for line in render_health_box(ctx):
        print(line)
    return 0


def _spend_check(args: argparse.Namespace, now: datetime, daily_cap: float) -> dict[str, Any]:
    pricing = load_pricing(args.pricing)
    cap = float(os.environ.get("CC_WEEKLY_BUDGET_USD") or pricing["weekly_budget_usd"])
    rows = read_ledger()
    week = window_spend(rows, week_days(now))
    today = window_spend(rows, {day_str(now)})
    g = gauge_state(week["usd"], cap)
    over_soft = today["usd"] > daily_cap
    light = "red" if g["pct"] >= 80 else "amber" if (g["pct"] >= 50 or over_soft) else "green"
    soft = " · over soft cap" if over_soft else ""
    return {"light": light,
            "text": f"week {usd(week['usd'])}/{usd(cap)} ({g['pct']}%) · today {usd(today['usd'])}/{usd(daily_cap)}{soft}"}


def _git_drift() -> tuple[int, int]:
    behind = dirty = 0
    try:
        out = subprocess.run(["git", "-C", str(ROOT_DIR), "rev-list", "--count", "main..origin/main"],
                             capture_output=True, text=True, timeout=10)
        behind = int(out.stdout.strip() or 0)
    except (subprocess.SubprocessError, ValueError):
        pass
    try:
        out = subprocess.run(["git", "-C", str(ROOT_DIR), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=10)
        dirty = len([l for l in out.stdout.splitlines() if l.strip()])
    except subprocess.SubprocessError:
        pass
    return behind, dirty


def _hooks_routed() -> bool:
    try:
        out = subprocess.run(["git", "-C", str(ROOT_DIR), "config", "--get", "core.hooksPath"],
                             capture_output=True, text=True, timeout=10)
        return "scripts/cc-hooks" in out.stdout.strip()
    except subprocess.SubprocessError:
        return False


def _read_config(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return json.loads(Path(args.workflow_config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _project_path(args: argparse.Namespace) -> Path:
    return Path(args.project_path).expanduser() if args.project_path else ROOT_DIR


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude Code spend gauge + cross-repo ledger.")
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--project-path", default=None)
    parser.add_argument("--session-marker", type=Path, default=DEFAULT_SESSION_MARKER)
    parser.add_argument("--closeout-marker", type=Path, default=CLOSEOUT_MARKER)
    parser.add_argument("--workflow-config", type=Path,
                        default=ROOT_DIR / "claude" / "workflow-config.json")
    parser.add_argument("--repo", default=None, help="Repo label for the ledger (default: dir name).")
    sub = parser.add_subparsers(dest="command")

    record = sub.add_parser("record", help="Record a startup baseline or a closeout session delta.")
    record.add_argument("--event", choices=["startup", "closeout"], required=True)
    record.set_defaults(func=cmd_record)

    mark = sub.add_parser("mark-closeout", help="Stamp the closeout-start timing marker.")
    mark.set_defaults(func=cmd_mark_closeout)

    gauge = sub.add_parser("gauge", help="Render the spend gauge footer.")
    gauge.add_argument("--tier", choices=["thin", "thicker", "dashboard", "auto"], default="thin")
    gauge.set_defaults(func=cmd_gauge)

    refresh = sub.add_parser(
        "refresh-pricing",
        help="Re-sync claude/pricing.json with Anthropic's published rate card.")
    refresh.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                         help="Skip the network call if the table is newer than this.")
    refresh.add_argument("--force", action="store_true",
                         help="Refresh regardless of age.")
    refresh.set_defaults(func=cmd_refresh_pricing)

    dash = sub.add_parser("dashboard", help="Render the /startup HEALTH box.")
    dash.add_argument("--packet", default="")
    dash.add_argument("--next", default="")
    dash.add_argument("--detail", default="")
    dash.set_defaults(func=cmd_dashboard)

    return parser


def cmd_refresh_pricing(args: argparse.Namespace) -> int:
    """Re-sync the rate card. Never fails the caller.

    This runs inside /closeout, so a DNS hiccup or a docs-format change must not
    block a closeout. Every failure path degrades to "keep the cached table and
    say so, with its age" -- a stale price is a wrong dollar figure, but a
    blocked closeout is a wrong workflow.
    """
    pricing_path = args.pricing
    pricing = load_pricing(pricing_path)
    age = pricing_age_days(pricing)

    if not args.force and not is_stale(pricing, max_age_days=args.max_age_days):
        print(f"[cc-spend] pricing current ({age}d old); skipping refresh")
        return 0

    try:
        changed, changes = refresh_pricing_file(pricing_path)
    except PricingRefreshError as exc:
        age_note = "never fetched" if age is None else f"{age}d old"
        print(f"[cc-spend] WARNING: pricing refresh failed ({exc})", file=sys.stderr)
        print(f"[cc-spend] using cached rates ({age_note}); dollar figures may be stale",
              file=sys.stderr)
        return 0

    if not changed:
        print("[cc-spend] pricing refreshed; no rate changes")
        return 0

    print(f"[cc-spend] pricing updated: {pricing_path}")
    for line in changes:
        print(f"  {line}")
    if changes:
        print("[cc-spend] ACTION: review the pricing.json diff before committing")
    return 0


def _force_utf8_stdout() -> None:
    """The footer prints box/gauge/emoji glyphs. Force UTF-8 (with replacement) so
    the gauge renders instead of crashing on a non-UTF-8 console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)
    if not hasattr(args, "func"):
        build_parser().print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # never block a session
        print(f"  spend gauge unavailable ({exc})")
        raise SystemExit(0)
