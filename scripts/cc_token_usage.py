#!/usr/bin/env python3
"""Hook-friendly Claude Code token usage metadata for git commit bodies.

Reads local Claude Code JSONL session history under ~/.claude/projects/ by
default. Does not read auth files, call the network, or store
prompts/transcripts in Git. Git hooks call this script to inject and validate
one commit trailer:

    Claude-Token-Usage: {"schema":"claude-token-usage/v1",...}

Claude Code token fields differ from Codex: input is split into three
categories — uncached (input_tokens), cache-write (cache_creation_input_tokens),
and cache-read (cache_read_input_tokens) — each billed at a different rate.
Per-turn counts are additive; no delta computation required within a session.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "total_tokens",
)

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT_DIR / "build" / "cc-token-usage" / "commit-baseline.json"
DEFAULT_PENDING_BASELINE = ROOT_DIR / "build" / "cc-token-usage" / "pending-baseline.json"
DEFAULT_SESSION_MARKER = ROOT_DIR / "build" / "cc-token-usage" / "session-start.json"
DEFAULT_WORKFLOW_CONFIG = ROOT_DIR / "claude" / "workflow-config.json"
TRACKED_HOOKS_PATH = "scripts/cc-hooks"
MANAGED_HOOK_NAMES = ("prepare-commit-msg", "commit-msg", "post-commit")
TRAILER_NAME = "Claude-Token-Usage"
USAGE_SCHEMA = "claude-token-usage/v1"
BASELINE_SCHEMA = "claude-token-baseline/v1"
PENDING_BASELINE_SCHEMA = "claude-token-pending-baseline/v1"
SESSION_SCHEMA = "claude-session-timing/v1"
SOURCE_NAME = "local-claude-session-history"
TRAILER_RE = re.compile(rf"^{re.escape(TRAILER_NAME)}:\s*(\{{.*\}})\s*$")
WORK_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b", re.IGNORECASE)
WORK_SOURCES = {"branch", "env", "manual"}

FORBIDDEN_KEY_EXACT = {"api_key", "apikey", "session_id", "sessionid"}
FORBIDDEN_KEY_PARTS = {
    "credential", "credentials", "host", "hostname", "path", "file",
    "prompt", "prompts", "messages", "transcript", "cost",
}

TOKEN_TRAILER_FIELDS = {
    "schema", "measurement", "source", "captured_at", "baseline",
    "session_count", "model_count", "models", "totals", "session", "work",
    "warnings",
}


@dataclass(frozen=True, order=True)
class ModelKey:
    model: str


@dataclass
class Usage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens

    def subtract(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=max(self.input_tokens - other.input_tokens, 0),
            cache_creation_input_tokens=max(self.cache_creation_input_tokens - other.cache_creation_input_tokens, 0),
            cache_read_input_tokens=max(self.cache_read_input_tokens - other.cache_read_input_tokens, 0),
            output_tokens=max(self.output_tokens - other.output_tokens, 0),
            total_tokens=max(self.total_tokens - other.total_tokens, 0),
        )

    def is_zero(self) -> bool:
        return all(getattr(self, f) == 0 for f in TOKEN_FIELDS)

    def to_dict(self) -> dict[str, int]:
        return {f: getattr(self, f) for f in TOKEN_FIELDS}


@dataclass
class SessionTurn:
    """One assistant turn, identified by the API message id it was billed under."""
    message_id: str
    key: ModelKey
    usage: Usage


@dataclass
class SessionUsage:
    session_id: str
    started_at: str
    updated_at: str
    project_path: str
    file: Path
    models: dict[ModelKey, Usage] = field(default_factory=dict)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: str) -> datetime:
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_claude_dir() -> Path:
    override = os.environ.get("CLAUDE_HOME")
    if override:
        return Path(override)
    return Path.home() / ".claude"


def encode_project_path(project_path: Path) -> str:
    """Encode a project path as Claude Code stores it: replace / with - ."""
    return str(project_path).replace("/", "-")


def usage_from_api_response(usage_obj: Any) -> tuple[ModelKey | None, Usage | None]:
    """Extract model key and usage from a Claude Code assistant message's usage field."""
    if not isinstance(usage_obj, dict):
        return None, None
    input_tok = int(usage_obj.get("input_tokens") or 0)
    cache_write = int(usage_obj.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage_obj.get("cache_read_input_tokens") or 0)
    output_tok = int(usage_obj.get("output_tokens") or 0)
    total = input_tok + cache_write + cache_read + output_tok
    return None, Usage(
        input_tokens=input_tok,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        output_tokens=output_tok,
        total_tokens=total,
    )


def path_is_within(path: Path, root: Path) -> bool:
    """True if path is root or lives beneath it."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_session_turns(
    path: Path,
    project_root: Path | None = None,
    cwd_required: bool = False,
) -> tuple[list[SessionTurn], str, str]:
    """Parse one session JSONL file into attributable turns plus its time span.

    When project_root is given, only turns whose per-event ``cwd`` is inside that
    root are counted, so a session that ranged across several repos is split
    correctly. Events predating the ``cwd`` field are counted only when the file
    already lives in this project's own session dir (cwd_required=False); for
    files borrowed from an ancestor or descendant dir they cannot be attributed
    and are skipped.

    Turns are keyed by the API's ``message.id`` rather than summed here, because
    the same message can appear many times on disk (see load_sessions).
    """
    turns: list[SessionTurn] = []
    first_timestamp = ""
    last_timestamp = ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp = str(event.get("timestamp") or "")
            if timestamp and not first_timestamp:
                first_timestamp = timestamp
            if timestamp:
                last_timestamp = timestamp

            if event.get("type") != "assistant":
                continue

            if project_root is not None:
                cwd = event.get("cwd")
                if not isinstance(cwd, str) or not cwd:
                    if cwd_required:
                        continue
                elif not path_is_within(Path(cwd), project_root):
                    continue

            msg = event.get("message")
            if not isinstance(msg, dict):
                continue

            model_name = str(msg.get("model") or "unknown").strip()
            if not model_name:
                model_name = "unknown"
            key = ModelKey(model=model_name)

            usage_obj = msg.get("usage")
            _, usage = usage_from_api_response(usage_obj)
            if usage is None or usage.is_zero():
                continue

            message_id = str(msg.get("id") or "").strip()
            if not message_id:
                # No API id to dedupe on: key by position so the turn still counts
                # exactly once instead of colliding with every other id-less turn.
                message_id = f"{path}#{len(turns)}"

            turns.append(SessionTurn(message_id=message_id, key=key, usage=usage))

    return turns, first_timestamp, last_timestamp


def read_session_usage(
    path: Path,
    project_root: Path | None = None,
    cwd_required: bool = False,
) -> SessionUsage | None:
    """Sum one session file's usage, deduplicating repeated messages within it."""
    turns, first_timestamp, last_timestamp = read_session_turns(
        path, project_root=project_root, cwd_required=cwd_required
    )
    best: dict[str, SessionTurn] = {}
    for turn in turns:
        keep_best_turn(best, turn)
    models = accumulate_models(best.values())
    if not models:
        return None

    return SessionUsage(
        session_id=path.stem,
        started_at=first_timestamp,
        updated_at=last_timestamp,
        project_path="",
        file=path,
        models=models,
    )


def keep_best_turn(best: dict[str, SessionTurn], turn: SessionTurn) -> None:
    """Record a turn, keeping the largest usage seen for its message id.

    Claude Code writes the same API message to disk more than once. Resuming or
    forking a session copies the earlier transcript into the new file verbatim,
    and a streaming turn is rewritten in place as output accumulates. Both cases
    share one ``message.id``; the tokens were billed once, when the message was
    generated. Summing every row roughly doubles the total, so keep exactly one
    row per id — the largest, since a streamed row grows toward its final value
    and the partials are prefixes of it.
    """
    current = best.get(turn.message_id)
    if current is None or turn.usage.total_tokens > current.usage.total_tokens:
        best[turn.message_id] = turn


def accumulate_models(turns: Iterable[SessionTurn]) -> dict[ModelKey, Usage]:
    models: dict[ModelKey, Usage] = {}
    for turn in turns:
        if turn.key not in models:
            models[turn.key] = Usage()
        models[turn.key].add(turn.usage)
    return models


def iter_project_session_files(claude_dir: Path, project_path: Path) -> Iterable[Path]:
    """Find JSONL session files that may contain work done inside project_path.

    Claude Code keys session history by the directory it was LAUNCHED from, not
    by repo. Launching from a parent (e.g. ~/repos) files every repo's history
    under that parent's dir, so this repo's own dir may not exist at all. Scan
    the exact dir plus any ancestor or descendant dir; matching here is a cheap
    string filter on the encoded names to keep the scan small, and read_session_
    usage() does the authoritative per-event ``cwd`` attribution.
    """
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return
    encoded = encode_project_path(project_path.resolve())
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        name = project_dir.name
        related = (
            name == encoded                    # this repo's own dir
            or name.startswith(encoded + "-")  # launched from a subdirectory
            or encoded.startswith(name + "-")  # launched from a parent directory
        )
        if related:
            # Recursive: subagent transcripts live in <session-id>/subagents/, and
            # their usage appears nowhere in the top-level session file.
            yield from sorted(project_dir.rglob("*.jsonl"))


def load_sessions(claude_dir: Path, project_path: Path) -> list[SessionUsage]:
    if not claude_dir.exists():
        raise FileNotFoundError(f"Claude data directory not found: {claude_dir}")
    project_root = project_path.resolve()
    encoded = encode_project_path(project_root)

    # Dedupe across files, not just within one: a resumed session copies the
    # earlier transcript into a new file, so the same message id appears in both.
    best: dict[str, tuple[Path, SessionTurn]] = {}
    spans: dict[Path, tuple[str, str]] = {}
    for path in iter_project_session_files(claude_dir, project_path):
        turns, started_at, updated_at = read_session_turns(
            path,
            project_root=project_root,
            cwd_required=not path_is_within(path.parent, claude_dir / "projects" / encoded),
        )
        if not turns:
            continue
        spans[path] = (started_at, updated_at)
        for turn in turns:
            current = best.get(turn.message_id)
            if current is None or turn.usage.total_tokens > current[1].usage.total_tokens:
                best[turn.message_id] = (path, turn)

    owned: dict[Path, list[SessionTurn]] = {}
    for path, turn in best.values():
        owned.setdefault(path, []).append(turn)

    sessions = []
    for path in sorted(owned):
        started_at, updated_at = spans[path]
        sessions.append(SessionUsage(
            session_id=path.stem,
            started_at=started_at,
            updated_at=updated_at,
            project_path="",
            file=path,
            models=accumulate_models(owned[path]),
        ))
    if not sessions:
        raise LookupError(
            f"No Claude Code sessions found for project: {project_path}\n"
            f"  Searched {claude_dir}/projects/ for sessions with turns run inside that path\n"
            f"  (own dir, parent dirs, and subdirectory dirs of {encoded})"
        )
    return sessions


def usage_from_sessions(sessions: list[SessionUsage]) -> dict[ModelKey, Usage]:
    models: dict[ModelKey, Usage] = {}
    for session in sessions:
        for key, usage in session.models.items():
            if key not in models:
                models[key] = Usage()
            models[key].add(usage)
    return models


def usage_total(models: dict[ModelKey, Usage]) -> Usage:
    total = Usage()
    for usage in models.values():
        total.add(usage)
    return total


def sorted_model_rows(models: dict[ModelKey, Usage], include_zero: bool = False) -> list[dict[str, Any]]:
    rows = []
    for key in sorted(models, key=lambda k: k.model):
        usage = models[key]
        if not include_zero and usage.is_zero():
            continue
        rows.append({"model": key.model, **usage.to_dict()})
    return rows


def models_from_rows(rows: Any) -> dict[ModelKey, Usage]:
    models: dict[ModelKey, Usage] = {}
    if not isinstance(rows, list):
        return models
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = ModelKey(model=str(row.get("model") or "unknown"))
        models[key] = Usage(**{f: int(row.get(f) or 0) for f in TOKEN_FIELDS})
    return models


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT_DIR), *args],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def git_path(path: str) -> Path:
    result = run_git(["rev-parse", "--git-path", path])
    value = result.stdout.strip()
    return Path(value) if Path(value).is_absolute() else ROOT_DIR / value


def local_hooks_path() -> str | None:
    result = run_git(["config", "--local", "--get", "core.hooksPath"], check=False)
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "unable to read local core.hooksPath")
    value = result.stdout.strip()
    return value or None


def hooks_path_is_tracked(value: str | None) -> bool:
    if value is None:
        return False
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    tracked = ROOT_DIR / TRACKED_HOOKS_PATH
    try:
        return candidate.resolve() == tracked.resolve()
    except OSError:
        return False


def repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def tracked_hook_path(name: str) -> Path:
    return ROOT_DIR / TRACKED_HOOKS_PATH / name


def is_managed_legacy_hook(path: Path) -> bool:
    if path.name not in MANAGED_HOOK_NAMES:
        return False
    tracked = tracked_hook_path(path.name)
    if not tracked.exists():
        return False
    try:
        return path.read_bytes() == tracked.read_bytes()
    except OSError:
        return False


def legacy_hook_conflicts() -> list[str]:
    hooks_dir = git_path("hooks")
    if not hooks_dir.exists():
        return []
    conflicts: list[str] = []
    for path in sorted(hooks_dir.iterdir(), key=lambda p: p.name):
        if path.name.endswith(".sample") or not path.is_file():
            continue
        if is_managed_legacy_hook(path):
            continue
        conflicts.append(repo_relative_path(path))
    return conflicts


def ensure_tracked_hook_files_executable() -> None:
    for name in (*MANAGED_HOOK_NAMES, "run-cc-token-helper.sh"):
        path = tracked_hook_path(name)
        if not path.exists():
            raise ValueError(f"tracked hook file not found: {path}")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_baseline_ignore() -> None:
    exclude_file = git_path("info/exclude")
    baseline_ignore = "build/cc-token-usage/"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    if exclude_file.exists():
        existing = exclude_file.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        existing = []
    if baseline_ignore in existing:
        return
    with exclude_file.open("a", encoding="utf-8", newline="\n") as handle:
        if existing:
            handle.write("\n")
        handle.write("# Local Claude Code token usage baseline.\n")
        handle.write(f"{baseline_ignore}\n")


def configure_tracked_hooks() -> dict[str, Any]:
    current = local_hooks_path()
    if current is not None and not hooks_path_is_tracked(current):
        raise ValueError(
            f"local core.hooksPath is already set to {current!r}; "
            "refusing to replace existing hook routing"
        )
    if current is None:
        conflicts = legacy_hook_conflicts()
        if conflicts:
            raise ValueError(
                "existing local Git hooks would be bypassed by tracked hooks: "
                + ", ".join(conflicts)
                + ". Move, chain, or remove them before installing Claude Code hooks."
            )
    ensure_tracked_hook_files_executable()
    run_git(["config", "--local", "core.hooksPath", TRACKED_HOOKS_PATH])
    ensure_baseline_ignore()
    return {"hooks_path": TRACKED_HOOKS_PATH, "previous_hooks_path": current}


def current_branch_name() -> str:
    result = run_git(["branch", "--show-current"], check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def work_id_from_text(value: str) -> str:
    match = WORK_ID_RE.search(value)
    return match.group(1).upper() if match else ""


def work_payload(args: argparse.Namespace) -> dict[str, str] | None:
    explicit_id = str(getattr(args, "work_id", "") or "").strip()
    explicit_system = str(getattr(args, "work_system", "") or "").strip()
    if explicit_id:
        return {"system": explicit_system or "jira", "id": explicit_id.upper(), "source": "manual"}

    env_id = str(os.environ.get("CC_WORK_ID") or "").strip()
    if env_id:
        return {
            "system": explicit_system or str(os.environ.get("CC_WORK_SYSTEM") or "jira"),
            "id": env_id.upper(),
            "source": "env",
        }

    branch_id = work_id_from_text(current_branch_name())
    if not branch_id:
        return None
    return {"system": explicit_system or "jira", "id": branch_id, "source": "branch"}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def current_commit_sha() -> str:
    result = run_git(["rev-parse", "--verify", "HEAD"], check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def load_workflow_config(path: Path) -> dict[str, bool]:
    defaults: dict[str, bool] = {"token_tracking": True}
    if not path.exists():
        return defaults
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    config = defaults.copy()
    for key in defaults:
        if key in payload:
            if not isinstance(payload[key], bool):
                raise ValueError(f"{path} {key} must be true or false")
            config[key] = payload[key]
    return config


def token_tracking_enabled(args: argparse.Namespace) -> bool:
    return load_workflow_config(resolve_repo_path(args.workflow_config))["token_tracking"]


def current_project_path(args: argparse.Namespace) -> Path:
    return Path(args.project_path).expanduser() if args.project_path else ROOT_DIR


def current_sessions(args: argparse.Namespace) -> list[SessionUsage]:
    return load_sessions(args.claude_dir.expanduser(), current_project_path(args))


def current_usage(args: argparse.Namespace) -> tuple[int, dict[ModelKey, Usage]]:
    sessions = current_sessions(args)
    return len(sessions), usage_from_sessions(sessions)


def baseline_payload(session_count: int, models: dict[ModelKey, Usage]) -> dict[str, Any]:
    rows = sorted_model_rows(models)
    return {
        "schema": BASELINE_SCHEMA,
        "source": SOURCE_NAME,
        "created_at": utc_timestamp(),
        "session_count": session_count,
        "models": rows,
        "totals": usage_total(models_from_rows(rows)).to_dict(),
    }


def load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Token baseline not found: {path}. "
            "Run 'bash scripts/cc-hooks/run-cc-token-helper.sh startup' before committing."
        )
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if payload.get("schema") != BASELINE_SCHEMA:
        raise ValueError(f"{path} schema must be {BASELINE_SCHEMA!r}")
    return payload


def session_start_payload() -> dict[str, Any]:
    return {
        "schema": SESSION_SCHEMA,
        "source": "repo-startup-protocol",
        "started_at": utc_timestamp(),
    }


def load_session_marker(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "session-start-marker-missing"
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None, "session-start-marker-invalid"
    if not isinstance(payload, dict) or payload.get("schema") != SESSION_SCHEMA:
        return None, "session-start-marker-invalid"
    started_at = payload.get("started_at")
    if not isinstance(started_at, str) or not started_at:
        return None, "session-start-marker-invalid"
    try:
        parse_utc_timestamp(started_at)
    except ValueError:
        return None, "session-start-marker-invalid"
    return payload, None


def session_timing_payload(marker: dict[str, Any], captured_at: str) -> dict[str, Any]:
    started = parse_utc_timestamp(marker["started_at"])
    captured = parse_utc_timestamp(captured_at)
    return {
        "schema": SESSION_SCHEMA,
        "measurement": "startup-to-commit",
        "started_at": marker["started_at"],
        "elapsed_seconds": max(int((captured - started).total_seconds()), 0),
    }


def pending_baseline_warning(path: Path) -> str | None:
    return "pending-baseline-refresh" if path.exists() else None


def trailer_payload(
    session_count: int,
    models: dict[ModelKey, Usage],
    baseline: dict[str, Any],
    session_marker: dict[str, Any] | None = None,
    work: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    baseline_models = models_from_rows(baseline.get("models"))
    delta_models: dict[ModelKey, Usage] = {}
    for key in sorted(set(models) | set(baseline_models), key=lambda k: k.model):
        delta = models.get(key, Usage()).subtract(baseline_models.get(key, Usage()))
        if not delta.is_zero():
            delta_models[key] = delta

    rows = sorted_model_rows(delta_models)
    captured_at = captured_at or utc_timestamp()
    payload: dict[str, Any] = {
        "schema": USAGE_SCHEMA,
        "measurement": "commit-delta",
        "source": SOURCE_NAME,
        "captured_at": captured_at,
        "baseline": {"created_at": str(baseline.get("created_at") or "")},
        "session_count": session_count,
        "model_count": len(rows),
        "models": rows,
        "totals": usage_total(models_from_rows(rows)).to_dict(),
    }
    if session_marker is not None:
        payload["session"] = session_timing_payload(session_marker, captured_at)
    if work is not None:
        payload["work"] = work
    if warnings:
        payload["warnings"] = sorted(set(warnings))
    return payload


def compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def trailer_line(payload: dict[str, Any]) -> str:
    return f"{TRAILER_NAME}: {compact_json(payload)}"


def remove_trailer_lines(text: str) -> str:
    lines = text.splitlines()
    filtered = [line for line in lines if not TRAILER_RE.match(line)]
    while filtered and filtered[-1] == "":
        filtered.pop()
    return "\n".join(filtered)


def inject_trailer(message_path: Path, payload: dict[str, Any]) -> None:
    existing = message_path.read_text(encoding="utf-8", errors="replace")
    body = remove_trailer_lines(existing)
    line = trailer_line(payload)
    next_text = f"{body}\n\n{line}\n" if body else f"{line}\n"
    message_path.write_text(next_text, encoding="utf-8", newline="\n")


def remove_managed_trailers(message_path: Path) -> None:
    existing = message_path.read_text(encoding="utf-8", errors="replace")
    next_text = remove_trailer_lines(existing)
    if next_text:
        next_text += "\n"
    message_path.write_text(next_text, encoding="utf-8", newline="\n")


def trailer_json_values(text: str) -> list[str]:
    return [m.group(1) for line in text.splitlines() if (m := TRAILER_RE.match(line))]


def is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    compact = normalized.replace("_", "")
    parts = [p for p in normalized.split("_") if p]
    if normalized in FORBIDDEN_KEY_EXACT or compact in FORBIDDEN_KEY_EXACT:
        return True
    if normalized in FORBIDDEN_KEY_PARTS or compact in FORBIDDEN_KEY_PARTS:
        return True
    return any(p in FORBIDDEN_KEY_PARTS for p in parts)


def sensitive_key_paths(value: Any, path: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for k, nested in value.items():
            next_path = f"{path}.{k}" if path else str(k)
            if is_sensitive_key(k):
                paths.append(next_path)
            paths.extend(sensitive_key_paths(nested, next_path))
    elif isinstance(value, list):
        for i, nested in enumerate(value):
            paths.extend(sensitive_key_paths(nested, f"{path}[{i}]"))
    return paths


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["trailer value must be a JSON object"]

    sensitive = sorted(set(sensitive_key_paths(payload)))
    if sensitive:
        errors.append("forbidden key names: " + ", ".join(sensitive))

    unknown = sorted(str(k) for k in payload if k not in TOKEN_TRAILER_FIELDS)
    if unknown:
        errors.append("unknown top-level fields: " + ", ".join(unknown))

    for key, expected in [("schema", USAGE_SCHEMA), ("measurement", "commit-delta"), ("source", SOURCE_NAME)]:
        if payload.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")

    baseline = payload.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("created_at"), str):
        errors.append("baseline.created_at must be a string")

    models = payload.get("models")
    if not isinstance(models, list):
        errors.append("models must be an array")
        models = []

    if payload.get("model_count") != len(models):
        errors.append("model_count must equal len(models)")
    if not isinstance(payload.get("session_count"), int) or payload["session_count"] < 0:
        errors.append("session_count must be a non-negative integer")

    expected_totals = Usage()
    for i, row in enumerate(models):
        if not isinstance(row, dict):
            errors.append(f"models[{i}] must be an object")
            continue
        if not isinstance(row.get("model"), str) or not row["model"]:
            errors.append(f"models[{i}].model must be a non-empty string")
        for f in TOKEN_FIELDS:
            v = row.get(f)
            if not isinstance(v, int) or v < 0:
                errors.append(f"models[{i}].{f} must be a non-negative integer")
                continue
            setattr(expected_totals, f, getattr(expected_totals, f) + v)

    totals = payload.get("totals")
    if not isinstance(totals, dict):
        errors.append("totals must be an object")
    else:
        for f, expected_val in expected_totals.to_dict().items():
            if totals.get(f) != expected_val:
                errors.append(f"totals.{f} must equal sum(models[].{f})")

    return errors


def initialize_baseline_if_missing(args: argparse.Namespace) -> tuple[bool, dict[str, Any] | None, str | None]:
    baseline_path = resolve_repo_path(args.baseline)
    if baseline_path.exists():
        return True, {"baseline": str(baseline_path), "created": False}, None
    try:
        session_count, models = current_usage(args)
        payload = baseline_payload(session_count, models)
        write_json_file(baseline_path, payload)
    except (FileNotFoundError, LookupError, ValueError, json.JSONDecodeError) as exc:
        return False, None, str(exc)
    return True, {
        "baseline": str(baseline_path),
        "created": True,
        "session_count": payload["session_count"],
        "model_count": len(payload["models"]),
        "total_tokens": payload["totals"]["total_tokens"],
    }, None


# ── subcommand implementations ────────────────────────────────────────────────

def startup_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        print("[cc-token-usage] startup offload skipped; token_tracking is disabled")
        return 0

    baseline_ok, baseline_info, baseline_warning = initialize_baseline_if_missing(args)
    warnings: list[str] = []

    # Install the tracked hooks unconditionally. Gating this on a usable baseline
    # created a bootstrap trap: a fresh clone has no session history yet, so the
    # first session left core.hooksPath unset and tracking silently never started.
    # The commit-path hooks degrade to a no-op while the baseline is missing.
    hooks_info = configure_tracked_hooks()

    if not baseline_ok:
        warnings.append(f"token-baseline-unavailable: {baseline_warning}")
        print(
            "[cc-token-usage] WARNING: token baseline could not be initialized; "
            "tracked hooks are installed but will not write trailers yet.",
            file=sys.stderr,
        )
        print(
            "[cc-token-usage] ACTION: run /startup again after this project has "
            "local Claude Code session history, or run the baseline command manually.",
            file=sys.stderr,
        )

    marker_path = resolve_repo_path(args.session_marker)
    session_payload = session_start_payload()
    write_json_file(marker_path, session_payload)

    if args.json:
        print(json.dumps({
            "baseline": baseline_info, "hooks": hooks_info,
            "session_marker": str(marker_path), "session": session_payload,
            "warnings": warnings,
        }, indent=2, sort_keys=True))
        return 0

    if hooks_info is not None:
        print(f"hooks_path={hooks_info['hooks_path']}")
    print(f"session_marker={marker_path}")
    print(f"started_at={session_payload['started_at']}")
    for warning in warnings:
        print(f"[cc-token-usage] WARNING: {warning}", file=sys.stderr)
    return 0


def baseline_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        print("[cc-token-usage] disabled by workflow config")
        return 0
    session_count, models = current_usage(args)
    payload = baseline_payload(session_count, models)
    baseline_path = resolve_repo_path(args.baseline)
    write_json_file(baseline_path, payload)
    remove_file_if_exists(resolve_repo_path(args.pending_baseline))
    if args.json:
        print(json.dumps({"baseline": str(baseline_path), "payload": payload}, indent=2, sort_keys=True))
        return 0
    print(f"baseline={baseline_path}")
    print(f"session_count={payload['session_count']}")
    print(f"model_count={len(payload['models'])}")
    print(f"total_tokens={payload['totals']['total_tokens']}")
    return 0


def status_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        print("[cc-token-usage] disabled by workflow config")
        return 0
    session_count, models = current_usage(args)
    payload = {
        "source": SOURCE_NAME,
        "session_count": session_count,
        "model_count": len(models),
        "models": sorted_model_rows(models),
        "totals": usage_total(models).to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"session_count={payload['session_count']}")
    print(f"model_count={payload['model_count']}")
    print(f"total_tokens={payload['totals']['total_tokens']}")
    for row in payload["models"]:
        print(f"model={row['model']} total_tokens={row['total_tokens']}")
    return 0


def prepare_commit_msg_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        remove_managed_trailers(Path(args.message_file))
        print("[cc-token-usage] disabled by workflow config")
        return 0

    baseline_path = resolve_repo_path(args.baseline)
    bootstrapped = baseline_path.exists()
    try:
        session_count, models = current_usage(args)
        baseline = load_baseline(baseline_path)
    except (FileNotFoundError, LookupError) as exc:
        # Once tracking is bootstrapped these are real failures and must block the
        # commit. Before then the hooks are installed but dormant, so let the
        # commit through untracked rather than wedging a fresh clone.
        if bootstrapped:
            raise
        remove_managed_trailers(Path(args.message_file))
        print(
            f"[cc-token-usage] WARNING: token trailer skipped; tracking not yet "
            f"initialized ({exc})",
            file=sys.stderr,
        )
        return 0
    warnings: list[str] = []
    session_marker, session_warning = load_session_marker(resolve_repo_path(args.session_marker))
    if session_warning:
        warnings.append(session_warning)
    baseline_warning = pending_baseline_warning(resolve_repo_path(args.pending_baseline))
    if baseline_warning:
        warnings.append(baseline_warning)

    captured_at = utc_timestamp()
    payload = trailer_payload(
        session_count, models, baseline, session_marker, work_payload(args), warnings, captured_at,
    )
    inject_trailer(Path(args.message_file), payload)
    for warning in warnings:
        print(f"[cc-token-usage] WARNING: {warning}", file=sys.stderr)
    print(f"[cc-token-usage] injected {TRAILER_NAME}")
    return 0


def commit_msg_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        print("[cc-token-usage] disabled by workflow config")
        return 0
    text = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
    values = trailer_json_values(text)
    if not values and not resolve_repo_path(args.baseline).exists():
        # Matches the dormant path in prepare-commit-msg: no baseline yet, so no
        # trailer was injected and its absence is expected rather than tampering.
        print(
            f"[cc-token-usage] WARNING: no {TRAILER_NAME} trailer; tracking not yet initialized",
            file=sys.stderr,
        )
        return 0
    if len(values) != 1:
        print(
            f"[cc-token-usage] ERROR: expected exactly one {TRAILER_NAME} trailer; found {len(values)}",
            file=sys.stderr,
        )
        return 1
    try:
        payload = json.loads(values[0])
    except json.JSONDecodeError as exc:
        print(f"[cc-token-usage] ERROR: invalid JSON trailer: {exc}", file=sys.stderr)
        return 1
    errors = validate_payload(payload)
    if errors:
        for error in errors:
            print(f"[cc-token-usage] ERROR: {error}", file=sys.stderr)
        return 1
    print(f"[cc-token-usage] valid {TRAILER_NAME}")
    return 0


def post_commit_command(args: argparse.Namespace) -> int:
    if not token_tracking_enabled(args):
        print("[cc-token-usage] disabled by workflow config")
        return 0

    pending_path = resolve_repo_path(args.pending_baseline)
    write_json_file(pending_path, {
        "schema": PENDING_BASELINE_SCHEMA,
        "source": SOURCE_NAME,
        "created_at": utc_timestamp(),
        "reason": "post-commit-refresh-started",
    })
    try:
        session_count, models = current_usage(args)
        payload = baseline_payload(session_count, models)
        baseline_path = resolve_repo_path(args.baseline)
        write_json_file(baseline_path, payload)
    except (FileNotFoundError, LookupError, ValueError, json.JSONDecodeError) as exc:
        write_json_file(pending_path, {
            "schema": PENDING_BASELINE_SCHEMA,
            "source": SOURCE_NAME,
            "created_at": utc_timestamp(),
            "reason": "post-commit-refresh-failed",
            "error": str(exc),
        })
        print(
            "[cc-token-usage] ERROR: post-commit baseline refresh failed; "
            "the next commit trailer will include pending-baseline-refresh",
            file=sys.stderr,
        )
        return 1

    remove_file_if_exists(pending_path)
    if args.json:
        print(json.dumps({"baseline": str(resolve_repo_path(args.baseline)), "payload": payload}, indent=2, sort_keys=True))
        return 0
    print(f"baseline={resolve_repo_path(args.baseline)}")
    print(f"total_tokens={payload['totals']['total_tokens']}")
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-path",
        help="Project path to match against Claude Code session dirs. Defaults to the repository root.",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--pending-baseline", type=Path, default=DEFAULT_PENDING_BASELINE)
    parser.add_argument("--session-marker", type=Path, default=DEFAULT_SESSION_MARKER)
    parser.add_argument("--workflow-config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--work-id", help="Optional durable work item id.")
    parser.add_argument("--work-system", help="Work tracking system name (default: jira).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture Claude Code token usage from local session history.",
    )
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=default_claude_dir(),
        help="Path to the Claude Code data directory. Defaults to CLAUDE_HOME or ~/.claude.",
    )
    sub = parser.add_subparsers(dest="command")

    status = sub.add_parser("status", help="Show aggregate token usage for the current project.")
    add_common_arguments(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_command)

    baseline = sub.add_parser("baseline", help="Write the local token baseline.")
    add_common_arguments(baseline)
    baseline.add_argument("--json", action="store_true")
    baseline.set_defaults(func=baseline_command)

    startup = sub.add_parser("startup", help="Run config-gated startup offloads: hooks and session marker.")
    add_common_arguments(startup)
    startup.add_argument("--json", action="store_true")
    startup.set_defaults(func=startup_command)

    trailer = sub.add_parser("trailer", help="Emit the git commit token usage trailer.")
    add_common_arguments(trailer)
    trailer.add_argument("--json", action="store_true")
    trailer.set_defaults(func=lambda args: (
        print(trailer_line(trailer_payload(*current_usage(args), load_baseline(resolve_repo_path(args.baseline))))),
        0,
    )[-1])

    prepare = sub.add_parser("prepare-commit-msg", help="Git hook: inject token trailer into commit message.")
    add_common_arguments(prepare)
    prepare.add_argument("--message-file", required=True)
    prepare.set_defaults(func=prepare_commit_msg_command)

    commit_msg = sub.add_parser("commit-msg", help="Git hook: validate managed commit trailers.")
    add_common_arguments(commit_msg)
    commit_msg.add_argument("--message-file", required=True)
    commit_msg.set_defaults(func=commit_msg_command)

    post_commit = sub.add_parser("post-commit", help="Git hook: refresh the local token baseline.")
    add_common_arguments(post_commit)
    post_commit.add_argument("--json", action="store_true")
    post_commit.set_defaults(func=post_commit_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["status"]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except (FileNotFoundError, LookupError, ValueError, json.JSONDecodeError) as exc:
        print(f"[cc-token-usage] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
