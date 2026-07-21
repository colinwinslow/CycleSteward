#!/usr/bin/env python3
"""Keep ``claude/pricing.json`` in sync with Anthropic's published rate card.

Rates change, and a stale table is silently wrong rather than loudly broken: the
spend gauge keeps rendering a confident dollar figure computed from last
quarter's prices. This module removes the hand-maintenance step.

Two independent mechanisms, because they cover different failure modes:

* **Effective-dated rates.** A scheduled change that is *already published*
  (e.g. Claude Sonnet 5's introductory pricing ending 2026-08-31) is stored as
  two dated windows and resolved against the current date. No network needed --
  the flip happens on schedule even on a box that never refreshes.
* **Refresh from the docs.** Anything unforeseen -- a new model, an unannounced
  change -- is picked up by re-parsing the published pricing table.

There is no pricing API: ``/v1/models`` returns capabilities but not rates. The
docs page is the authoritative machine-readable source, is public (no API key),
and carries all five rate columns including both cache-write TTLs.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

# CC_PRICING_URL lets a caller point at a mirror or a local copy (and keeps the
# tests off the network).
PRICING_DOC_URL = (
    os.environ.get("CC_PRICING_URL")
    or "https://platform.claude.com/docs/en/about-claude/pricing.md"
)
FETCH_TIMEOUT_SECONDS = 20
USER_AGENT = "agentic-workflow-kit/cc_pricing (+https://platform.claude.com/docs)"
DEFAULT_MAX_AGE_DAYS = 7

# Column order in the published table, mapped to our rate keys. "1h Cache
# Writes" is captured too: a request using the 1-hour TTL bills at 2x input
# rather than 1.25x, which the old hand-maintained table could not express.
RATE_COLUMNS = ["input", "cache_write", "cache_write_1h", "cache_read", "output"]
HEADER_MARKER = "Base Input Tokens"

PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
THROUGH_RE = re.compile(r"\bthrough\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})", re.I)
STARTING_RE = re.compile(r"\bstarting\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


class PricingRefreshError(RuntimeError):
    """Refresh could not complete. Callers keep the cached table and warn."""


# ── effective-dated resolution ────────────────────────────────────────────────

def resolve_rate(entry: Any, on: date | None = None) -> dict[str, float] | None:
    """Resolve a model entry to the rate in effect on a given date.

    An entry is either a plain rate object (no scheduled change) or a list of
    dated windows with optional ``from``/``until`` bounds, inclusive. Accepting
    both keeps every previously written pricing.json readable.
    """
    if isinstance(entry, dict):
        return entry
    if not isinstance(entry, list):
        return None
    today = on or date.today()
    fallback = None
    for window in entry:
        if not isinstance(window, dict):
            continue
        starts = parse_iso_date(window.get("from"))
        ends = parse_iso_date(window.get("until"))
        if starts and today < starts:
            continue
        if ends and today > ends:
            fallback = fallback or window
            continue
        return window
    # Every window has expired: price at the most recent rather than silently
    # dropping the model to $0.
    return fallback


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


# ── parsing the published table ───────────────────────────────────────────────

def model_id_from_display_name(name: str) -> str:
    """'Claude Opus 4.8' -> 'claude-opus-4-8'.

    The published table lists display names; our rates are keyed by API model
    id. The transformation is mechanical, which is what makes an unattended
    refresh viable.
    """
    name = MARKDOWN_LINK_RE.sub(r"\1", name)
    name = PARENTHETICAL_RE.sub("", name)
    name = THROUGH_RE.sub("", name)
    name = STARTING_RE.sub("", name)
    name = name.strip().lower()
    name = re.sub(r"[.\s_]+", "-", name)
    return re.sub(r"-+", "-", name).strip("-")


def parse_us_date(value: str) -> str | None:
    """'August 31, 2026' -> '2026-08-31'."""
    match = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", value.strip())
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if not month:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"


def parse_pricing_table(markdown: str) -> dict[str, Any]:
    """Extract {model_id: rate-or-windows} from the docs pricing table."""
    rows = [line for line in markdown.splitlines() if line.strip().startswith("|")]
    header_index = next(
        (i for i, line in enumerate(rows) if HEADER_MARKER in line), None
    )
    if header_index is None:
        raise PricingRefreshError(
            f"pricing table not found (no {HEADER_MARKER!r} header); "
            "the published format likely changed"
        )

    models: dict[str, list[dict[str, Any]]] = {}
    for line in rows[header_index + 1:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(RATE_COLUMNS) + 1:
            continue
        if set(cells[1].replace(" ", "")) <= {"-", ":"}:
            continue  # separator row

        display = cells[0]
        prices = []
        for cell in cells[1:len(RATE_COLUMNS) + 1]:
            match = PRICE_RE.search(cell)
            if not match:
                break
            prices.append(float(match.group(1)))
        if len(prices) != len(RATE_COLUMNS):
            continue

        model_id = model_id_from_display_name(display)
        if not model_id.startswith("claude-"):
            continue

        window: dict[str, Any] = dict(zip(RATE_COLUMNS, prices))
        through = THROUGH_RE.search(MARKDOWN_LINK_RE.sub(r"\1", display))
        starting = STARTING_RE.search(MARKDOWN_LINK_RE.sub(r"\1", display))
        if through:
            window["until"] = parse_us_date(through.group(1))
        if starting:
            window["from"] = parse_us_date(starting.group(1))
        models.setdefault(model_id, []).append(window)

    if not models:
        raise PricingRefreshError("pricing table parsed but contained no model rows")

    # Collapse the common case (one undated window) back to a plain rate object.
    return {
        model_id: windows[0] if len(windows) == 1 and not _is_dated(windows[0]) else windows
        for model_id, windows in models.items()
    }


def _is_dated(window: dict[str, Any]) -> bool:
    return bool(window.get("from") or window.get("until"))


def fetch_pricing_markdown(url: str = PRICING_DOC_URL) -> str:
    # The docs site 403s urllib's default user-agent; identify ourselves instead.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise PricingRefreshError(f"could not fetch {url}: {exc}") from exc


# ── staleness + merge ─────────────────────────────────────────────────────────

def pricing_age_days(pricing: dict[str, Any], on: date | None = None) -> int | None:
    fetched = parse_iso_date(pricing.get("fetched"))
    if fetched is None:
        return None
    return ((on or date.today()) - fetched).days


def is_stale(pricing: dict[str, Any], max_age_days: int = DEFAULT_MAX_AGE_DAYS,
             on: date | None = None) -> bool:
    age = pricing_age_days(pricing, on=on)
    return age is None or age >= max_age_days


def diff_rates(old: dict[str, Any], new: dict[str, Any],
               on: date | None = None) -> list[str]:
    """Human-readable per-model changes in the rate in effect today."""
    changes = []
    for model_id in sorted(set(old) | set(new)):
        before = resolve_rate(old.get(model_id), on=on)
        after = resolve_rate(new.get(model_id), on=on)
        if before == after:
            continue
        if before is None:
            changes.append(f"+ {model_id}: added at {_fmt(after)}")
        elif after is None:
            changes.append(f"- {model_id}: removed (was {_fmt(before)})")
        else:
            changes.append(f"~ {model_id}: {_fmt(before)} -> {_fmt(after)}")
    return changes


def _fmt(rate: dict[str, float] | None) -> str:
    """Render every priced field. A diff line that says '$10/$50 -> $10/$50'
    because an unshown field changed is worse than no diff line at all."""
    if not rate:
        return "unpriced"
    parts = [f"in ${rate.get('input', 0):g}", f"out ${rate.get('output', 0):g}"]
    cache = [f"w5m ${rate.get('cache_write', 0):g}"]
    if "cache_write_1h" in rate:
        cache.append(f"w1h ${rate['cache_write_1h']:g}")
    cache.append(f"r ${rate.get('cache_read', 0):g}")
    return f"{' / '.join(parts)} (cache {', '.join(cache)})"


def merge_pricing(existing: dict[str, Any], models: dict[str, Any],
                  on: date | None = None) -> dict[str, Any]:
    """New rates, existing local settings. Budgets and credit_usd are the
    operator's, not Anthropic's, so a refresh must never overwrite them."""
    merged = dict(existing)
    merged["models"] = models
    merged["fetched"] = (on or date.today()).isoformat()
    merged["source"] = [PRICING_DOC_URL]
    merged["schema"] = "claude-pricing/v2"
    merged.pop("unverified", None)
    merged["aliases"] = prune_shadowed_aliases(existing.get("aliases") or {}, models)
    merged.setdefault("default_model", None)
    return merged


def prune_shadowed_aliases(aliases: dict[str, str],
                           models: dict[str, Any]) -> dict[str, str]:
    """Drop aliases whose name is now a real model with its own rates.

    Aliases are convenience redirects for ids that have no entry of their own,
    and they are resolved *before* the model table. Once the published card
    lists e.g. ``claude-opus-4`` (retired, $15/MTok), an alias pointing it at
    ``claude-opus-4-8`` ($5/MTok) would silently misprice real usage of the
    older model by 3x. A shadowed alias is always wrong, so drop it.
    """
    lowered = {k.lower() for k in models}
    return {k: v for k, v in aliases.items() if k.lower() not in lowered}


def refresh_pricing_file(path: Path, on: date | None = None,
                         url: str = PRICING_DOC_URL) -> tuple[bool, list[str]]:
    """Fetch, parse, and rewrite the pricing file. Returns (changed, changes).

    Raises PricingRefreshError on any failure; callers keep the cached table.
    """
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}

    models = parse_pricing_table(fetch_pricing_markdown(url))
    changes = diff_rates(existing.get("models") or {}, models, on=on)
    merged = merge_pricing(existing, models, on=on)

    if merged == existing:
        return False, []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return True, changes
