#!/usr/bin/env python3
"""
PR Review Bot — Automated code review powered by Claude.

Quick start:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    python review.py

Usage:
    python review.py [--base BRANCH] [--repo PATH] [--model MODEL]
                     [--post-comment --pr NUMBER [--github-repo OWNER/REPO]]
                     [--no-stream] [--prompt NAME]

Examples:
    # Review current branch against main (streaming output)
    python review.py

    # Review against a different base branch
    python review.py --base develop

    # Review a repo at a specific path
    python review.py --repo ~/projects/my-app

    # Post the review as a GitHub PR comment (requires `gh` CLI authenticated)
    python review.py --post-comment --pr 42

    # Use a more powerful model for deeper analysis
    python review.py --model claude-opus-4-5
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Dependency check — give a friendly error before anything else blows up
# ---------------------------------------------------------------------------
try:
    import anthropic
except ModuleNotFoundError:
    print(
        "❌  The 'anthropic' package is not installed.\n"
        "    Fix: pip install anthropic\n"
        "    Docs: https://docs.anthropic.com/",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_BASE = "main"
MAX_DIFF_CHARS = 120_000  # ~30 k tokens — truncate beyond this
MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: str) -> tuple[str, int]:
    """Run a git sub-command; returns (stdout+stderr, returncode)."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    output = result.stdout
    if result.returncode != 0 and result.stderr:
        output += result.stderr
    return output, result.returncode


def get_current_branch(repo: str) -> Optional[str]:
    out, rc = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return out.strip() if rc == 0 else None


def get_diff(base: str, repo: str) -> tuple[str, int]:
    return _git(["diff", f"{base}...HEAD"], repo)


def get_log(base: str, repo: str) -> tuple[str, int]:
    return _git(["log", f"{base}...HEAD", "--oneline", "--no-merges"], repo)


def get_commit_count(log_output: str) -> int:
    lines = [l for l in log_output.strip().splitlines() if l.strip()]
    return len(lines)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def load_system_prompt(name: str) -> str:
    """
    Search for prompts/{name}.md in, in order:
      1. The directory containing this script  (works when used as GitHub Action)
      2. The current working directory          (works when installed / called from repo root)
    Falls back to a minimal inline prompt if neither is found.
    """
    candidates = [
        SCRIPT_DIR / "prompts" / f"{name}.md",
        Path.cwd() / "prompts" / f"{name}.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")

    # Inline fallback so the bot still works without the file
    return (
        "You are a Staff Software Engineer. Review the following git diff for "
        "logic flaws, security issues, and resource leaks only. "
        "Ignore style and formatting. "
        "If there are no critical issues output exactly: "
        "✅ **Status: Approved.** No critical issues identified."
    )


def build_user_message(
    branch: str, base: str, diff: str, log: str, max_diff_chars: int = MAX_DIFF_CHARS
) -> str:
    """Assemble the user turn that carries the actual diff data."""
    truncated = False
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars]
        truncated = True

    parts = [
        f"Please review the following pull request.\n",
        f"**Branch:** `{branch}` → `{base}`\n",
        "## Commit Log\n",
        "```\n",
        (log.strip() or "(no commits)") + "\n",
        "```\n\n",
        "## Diff\n",
        "```diff\n",
        diff,
    ]
    if truncated:
        parts.append(
            f"\n\n... [diff truncated at {max_diff_chars:,} characters — "
            "remaining files not shown] ..."
        )
    parts.append("\n```")
    return "".join(parts)


# ---------------------------------------------------------------------------
# GitHub comment
# ---------------------------------------------------------------------------


def post_github_comment(
    body: str,
    pr_number: str,
    github_repo: Optional[str],
) -> bool:
    """Post *body* as a comment on the given PR using the `gh` CLI."""
    cmd = ["gh", "pr", "comment", pr_number, "--body", body]
    if github_repo:
        cmd += ["--repo", github_repo]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"⚠️  gh CLI failed to post comment:\n{result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Core review runner
# ---------------------------------------------------------------------------


def run_review(
    *,
    repo: str,
    base: str,
    model: str,
    prompt_name: str,
    stream: bool,
    max_diff_chars: int = MAX_DIFF_CHARS,
) -> str:
    """
    Run the full review pipeline.
    Returns the complete review text.
    Raises SystemExit on unrecoverable errors.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "❌  ANTHROPIC_API_KEY is not set.\n"
            "    Export it:  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "    Get a key:  https://console.anthropic.com/",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate repo
    repo_abs = os.path.abspath(repo)
    branch = get_current_branch(repo_abs)
    if branch is None:
        print(
            f"❌  '{repo_abs}' is not a git repository (or git is not installed).",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"🔍  Reviewing  \033[1m{branch}\033[0m  ←  \033[1m{base}\033[0m",
        file=sys.stderr,
    )

    # Collect git data
    diff, diff_rc = get_diff(base, repo_abs)
    if diff_rc != 0:
        print(
            f"❌  git diff failed. Is '{base}' a valid branch/ref?\n    {diff.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not diff.strip():
        print(
            "✅  Branch is identical to base — nothing to review.",
            file=sys.stderr,
        )
        sys.exit(0)

    log, _ = get_log(base, repo_abs)
    n_commits = get_commit_count(log)
    diff_lines = diff.count("\n")

    print(
        f"    {n_commits} commit(s) · {diff_lines:,} diff lines",
        file=sys.stderr,
    )

    # Build prompts
    system_prompt = load_system_prompt(prompt_name)
    user_message = build_user_message(branch, base, diff, log, max_diff_chars)

    # Call Claude
    client = anthropic.Anthropic(api_key=api_key)
    print("", file=sys.stderr)  # visual separator before review output

    review_chunks: list[str] = []

    if stream:
        with client.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as s:
            for chunk in s.text_stream:
                print(chunk, end="", flush=True)
                review_chunks.append(chunk)
        print()  # trailing newline after streamed output
    else:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        print(text)
        review_chunks.append(text)

    return "".join(review_chunks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review",
        description="PR Review Bot — automated code review powered by Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  ANTHROPIC_API_KEY   Your Anthropic API key (required)\n"
            "  GH_TOKEN            GitHub token used by the gh CLI (for --post-comment)\n"
        ),
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        metavar="BRANCH",
        help=f"Base branch / ref to diff against (default: {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Path to the git repository (default: current directory)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=f"Anthropic model ID (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt",
        default="pr_review",
        metavar="NAME",
        help=(
            "Name of the prompt file inside prompts/ to use, without the .md extension "
            "(default: pr_review)"
        ),
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Collect the full response before printing (disables streaming)",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=MAX_DIFF_CHARS,
        metavar="N",
        help=(
            f"Truncate the git diff at N characters before sending to the model "
            f"(default: {MAX_DIFF_CHARS:,}). Increase for large PRs, decrease to save tokens."
        ),
    )
    # GitHub comment integration
    gh_group = parser.add_argument_group("GitHub integration")
    gh_group.add_argument(
        "--post-comment",
        action="store_true",
        help="Post the review as a PR comment via the `gh` CLI",
    )
    gh_group.add_argument(
        "--pr",
        metavar="NUMBER",
        help="PR number to comment on (required with --post-comment)",
    )
    gh_group.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        help="GitHub repository slug, e.g. octocat/hello-world (optional with --post-comment)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.post_comment and not args.pr:
        parser.error("--pr NUMBER is required when --post-comment is set")

    review = run_review(
        repo=args.repo,
        base=args.base,
        model=args.model,
        prompt_name=args.prompt,
        stream=not (args.no_stream or args.post_comment),
        max_diff_chars=args.max_diff_chars,
    )

    if args.post_comment:
        print(f"📬  Posting review to PR #{args.pr} …", file=sys.stderr)
        ok = post_github_comment(review, args.pr, args.github_repo)
        if ok:
            print("✅  Comment posted successfully.", file=sys.stderr)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
