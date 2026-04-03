#!/usr/bin/env python3
"""
PR Review Bot — core CLI logic.

Runs git diff/log against a base branch, sends the output to Claude,
and streams the code review to stdout (or posts it as a GitHub PR comment).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import anthropic
except ImportError:
    print(
        "❌  The 'anthropic' package is not installed.\n    Fix: pip install anthropic",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_DIFF_CHARS = 120_000  # ~30 k tokens — truncate above this
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"  # …/pr-review-bot/prompts/


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: str) -> tuple[str, int]:
    """Run a git sub-command; return (combined_output, returncode)."""
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


def current_branch(repo: str) -> Optional[str]:
    out, rc = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return out.strip() if rc == 0 else None


def git_diff(base: str, repo: str) -> tuple[str, int]:
    return _git(["diff", f"{base}...HEAD"], repo)


def git_log(base: str, repo: str) -> tuple[str, int]:
    return _git(["log", f"{base}...HEAD", "--oneline", "--no-merges"], repo)


def commit_count(log_output: str) -> int:
    lines = [l for l in log_output.strip().splitlines() if l.strip()]
    return len(lines)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def load_system_prompt(name: str = "pr_review") -> str:
    """
    Load a prompt from the prompts/ directory.

    Search order:
      1. <repo-root>/prompts/<name>.md  (installed package layout)
      2. ./prompts/<name>.md            (running from source tree)
    Falls back to a minimal inline prompt if neither file exists.
    """
    candidates = [
        PROMPTS_DIR / f"{name}.md",
        Path.cwd() / "prompts" / f"{name}.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")

    # Inline fallback — enough to produce a useful review
    return (
        "You are a Staff Software Engineer. Review the following git diff for "
        "logic flaws, security risks, resource leaks, and severe complexity "
        "regressions. Skip style and formatting issues. "
        "Format findings as: filename · line N | Severity | Issue | Fix."
    )


def build_user_message(branch: str, base: str, diff: str, log: str) -> str:
    """Compose the user-turn message that contains the diff and log."""
    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS]
            + f"\n\n... [diff truncated at {MAX_DIFF_CHARS:,} characters] ..."
        )

    n = commit_count(log)
    commit_word = "commit" if n == 1 else "commits"

    return (
        f"Please review this pull request.\n\n"
        f"**Branch:** `{branch}` → `{base}` ({n} {commit_word})\n\n"
        f"## Commit Log\n"
        f"```\n{log.strip() or '(no commits)'}\n```\n\n"
        f"## Diff\n"
        f"```diff\n{diff}\n```"
    )


# ---------------------------------------------------------------------------
# GitHub comment
# ---------------------------------------------------------------------------


def post_github_comment(
    body: str,
    pr_number: str,
    github_repo: Optional[str] = None,
) -> bool:
    """
    Post *body* as a comment on the given PR using the `gh` CLI.
    Returns True on success.
    """
    cmd = ["gh", "pr", "comment", pr_number, "--body", body]
    if github_repo:
        cmd += ["--repo", github_repo]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"⚠️   gh CLI error: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-review",
        description="PR Review Bot — automated code review powered by Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  ANTHROPIC_API_KEY   Required. Your Anthropic API key.\n"
            "  GH_TOKEN            Required only with --post-comment.\n\n"
            "Examples:\n"
            "  pr-review\n"
            "  pr-review --base develop\n"
            "  pr-review --model claude-opus-4-5\n"
            "  pr-review --post-comment --pr 42 --github-repo owner/repo\n"
        ),
    )

    parser.add_argument(
        "--base",
        default="main",
        metavar="BRANCH",
        help="Base branch to compare against (default: main)",
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
        help=f"Anthropic model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt",
        default="pr_review",
        metavar="NAME",
        help="Prompt filename stem in prompts/ directory (default: pr_review)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        metavar="N",
        help="Maximum tokens in the response (default: 4096)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Collect the full response before printing (disables streaming)",
    )

    github = parser.add_argument_group("GitHub integration")
    github.add_argument(
        "--post-comment",
        action="store_true",
        help="Post the review as a GitHub PR comment via the gh CLI",
    )
    github.add_argument(
        "--pr",
        metavar="NUMBER",
        help="PR number (required with --post-comment)",
    )
    github.add_argument(
        "--github-repo",
        metavar="OWNER/REPO",
        help="GitHub repository slug, e.g. acme/backend (optional with --post-comment)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Validate argument combinations
    # ------------------------------------------------------------------
    if args.post_comment and not args.pr:
        parser.error("--pr NUMBER is required when using --post-comment")

    # ------------------------------------------------------------------
    # Resolve paths & environment
    # ------------------------------------------------------------------
    repo = os.path.abspath(args.repo)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "❌  ANTHROPIC_API_KEY is not set.\n"
            "    Export it before running:\n"
            "      export ANTHROPIC_API_KEY=sk-ant-...\n"
            "    Get a key at: https://console.anthropic.com/",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Resolve branch name
    # ------------------------------------------------------------------
    branch = current_branch(repo)
    if branch is None:
        print(
            f"❌  '{repo}' does not appear to be a git repository, "
            "or git is not installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if branch == args.base:
        print(
            f"⚠️   Current branch is '{branch}' which is the same as --base. "
            "Checkout a feature branch first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🔍  Reviewing  {branch}  ←  {args.base}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Collect git data
    # ------------------------------------------------------------------
    diff, diff_rc = git_diff(args.base, repo)
    if diff_rc != 0:
        print(
            f"❌  git diff failed.\n"
            f"    Is '{args.base}' a valid branch reachable from this repo?\n"
            f"    Output: {diff.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)

    log, _ = git_log(args.base, repo)

    if not diff.strip():
        print(
            "✅  Branch is identical to base — nothing to review.",
            file=sys.stderr,
        )
        sys.exit(0)

    n_commits = commit_count(log)
    diff_lines = diff.count("\n")
    print(
        f"    {n_commits} commit(s) · {diff_lines:,} diff lines",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # Build prompts
    # ------------------------------------------------------------------
    system_prompt = load_system_prompt(args.prompt)
    user_message = build_user_message(branch, args.base, diff, log)

    # ------------------------------------------------------------------
    # Call Claude
    # ------------------------------------------------------------------
    client = anthropic.Anthropic(api_key=api_key)
    collected: list[str] = []

    print("", file=sys.stderr)  # visual separator before review output

    use_stream = not args.no_stream and not args.post_comment

    if use_stream:
        try:
            with client.messages.stream(
                model=args.model,
                max_tokens=args.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                for chunk in stream.text_stream:
                    print(chunk, end="", flush=True)
                    collected.append(chunk)
            print()  # trailing newline
        except anthropic.APIStatusError as exc:
            print(
                f"\n❌  Anthropic API error {exc.status_code}: {exc.message}",
                file=sys.stderr,
            )
            sys.exit(1)
        except anthropic.APIConnectionError:
            print(
                "\n❌  Could not reach the Anthropic API. Check your network.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        try:
            response = client.messages.create(
                model=args.model,
                max_tokens=args.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIStatusError as exc:
            print(
                f"❌  Anthropic API error {exc.status_code}: {exc.message}",
                file=sys.stderr,
            )
            sys.exit(1)
        except anthropic.APIConnectionError:
            print(
                "❌  Could not reach the Anthropic API. Check your network.",
                file=sys.stderr,
            )
            sys.exit(1)

        review_text = response.content[0].text
        collected.append(review_text)
        print(review_text)

    # ------------------------------------------------------------------
    # Optionally post to GitHub
    # ------------------------------------------------------------------
    if args.post_comment:
        full_review = "".join(collected)
        print(f"📬  Posting review to PR #{args.pr}…", file=sys.stderr)
        ok = post_github_comment(full_review, args.pr, args.github_repo)
        if ok:
            print("✅  Review posted successfully.", file=sys.stderr)
        else:
            print(
                "⚠️   Comment could not be posted. Review was printed to stdout.",
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
