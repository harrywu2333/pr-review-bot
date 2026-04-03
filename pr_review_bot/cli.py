#!/usr/bin/env python3
"""
PR Review Bot — core CLI logic.

Supports Gemini, Groq, and OpenRouter via the OpenAI-compatible API.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import openai as _openai_module
except ImportError:
    print(
        "❌  The 'openai' package is not installed.\n    Fix: pip install openai",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print(
        "❌  The 'python-dotenv' package is not installed.\n    Fix: pip install python-dotenv",
        file=sys.stderr,
    )
    sys.exit(1)

from .providers import (
    PROVIDER_NAMES,
    PROVIDERS,
    create_completion,
    detect_provider,
    make_client,
    stream_completion,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE = "main"
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
    lines = [line for line in log_output.strip().splitlines() if line.strip()]
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
# Core review logic
# ---------------------------------------------------------------------------


def run_review(
    *,
    repo: str,
    base: str,
    provider_key: str | None,  # None = auto-detect
    model: str | None,  # None = use provider default
    prompt_name: str,
    stream: bool,
    max_diff_chars: int = MAX_DIFF_CHARS,
    max_tokens: int = 4096,
) -> str:
    """
    Run a full PR review and return the complete review text.

    Prints the review to stdout (streaming or all-at-once depending on
    *stream*).  Exits with code 1 on any unrecoverable error.
    """

    # ------------------------------------------------------------------
    # 1. Resolve provider
    # ------------------------------------------------------------------
    if provider_key is not None:
        provider = PROVIDERS[provider_key]
        if provider.api_key is None:
            print(
                f"❌  {provider.env_var} is not set or is empty.\n"
                f"    Export it before running:\n"
                f"      export {provider.env_var}=<your-key>",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        provider, found_keys = detect_provider()
        if not found_keys:
            print(
                "❌  No API key found. Set one of the following env vars:\n"
                "      GEMINI_API_KEY      — Google Gemini\n"
                "      GROQ_API_KEY        — Groq\n"
                "      OPENROUTER_API_KEY  — OpenRouter\n\n"
                "    Then re-run, or pass --provider to specify explicitly.",
                file=sys.stderr,
            )
            sys.exit(1)
        if provider is None:
            # More than one key was found
            keys_fmt = ", ".join(found_keys)
            print(
                f"❌  Multiple API keys found ({keys_fmt}).\n"
                "    Use --provider to specify which provider to use.",
                file=sys.stderr,
            )
            sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Get api_key (guaranteed non-None at this point, but be safe)
    # ------------------------------------------------------------------
    api_key = provider.api_key
    if api_key is None:
        print(
            f"❌  {provider.env_var} became unavailable unexpectedly.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Resolve model
    # ------------------------------------------------------------------
    model = model or provider.default_model

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

    if branch == base:
        print(
            f"⚠️   Current branch is '{branch}' which is the same as --base. "
            "Checkout a feature branch first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Print header
    # ------------------------------------------------------------------
    print(
        f"🔍  Reviewing  {branch}  ←  {base}  [{provider.display_name} / {model}]",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # 5. Collect git data
    # ------------------------------------------------------------------
    diff, diff_rc = git_diff(base, repo)
    if diff_rc != 0:
        print(
            f"❌  git diff failed.\n"
            f"    Is '{base}' a valid branch reachable from this repo?\n"
            f"    Output: {diff.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)

    log, _ = git_log(base, repo)

    if not diff.strip():
        print(
            "✅  Branch is identical to base — nothing to review.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Truncate diff early when a custom limit is requested so the
    # build_user_message helper sees an already-bounded string.
    if len(diff) > max_diff_chars:
        diff = (
            diff[:max_diff_chars]
            + f"\n\n... [diff truncated at {max_diff_chars:,} characters] ..."
        )

    n_commits = commit_count(log)
    diff_lines = diff.count("\n")
    print(
        f"    {n_commits} commit(s) · {diff_lines:,} diff lines",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # Build prompts
    # ------------------------------------------------------------------
    system_prompt = load_system_prompt(prompt_name)
    user_message = build_user_message(branch, base, diff, log)

    # ------------------------------------------------------------------
    # 6. Create client
    # ------------------------------------------------------------------
    client = make_client(provider)
    collected: list[str] = []

    print("", file=sys.stderr)  # visual separator before review output

    # ------------------------------------------------------------------
    # 7. Call the LLM
    # ------------------------------------------------------------------
    if stream:
        try:
            for chunk in stream_completion(
                client, model, system_prompt, user_message, max_tokens
            ):
                print(chunk, end="", flush=True)
                collected.append(chunk)
            print()  # trailing newline
        except _openai_module.APIStatusError as exc:
            print(
                f"\n❌  API error {exc.status_code} from {provider.display_name}: "
                f"{exc.message}",
                file=sys.stderr,
            )
            sys.exit(1)
        except _openai_module.APIConnectionError:
            print(
                f"\n❌  Could not reach the {provider.display_name} API. "
                "Check your network connection.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        try:
            review_text = create_completion(
                client, model, system_prompt, user_message, max_tokens
            )
        except _openai_module.APIStatusError as exc:
            print(
                f"❌  API error {exc.status_code} from {provider.display_name}: "
                f"{exc.message}",
                file=sys.stderr,
            )
            sys.exit(1)
        except _openai_module.APIConnectionError:
            print(
                f"❌  Could not reach the {provider.display_name} API. "
                "Check your network connection.",
                file=sys.stderr,
            )
            sys.exit(1)

        collected.append(review_text)
        print(review_text)

    return "".join(collected)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    provider_help_lines = "\n".join(
        f"  {p.key:<12} {PROVIDERS[p.key].env_var}  (default model: {p.default_model})"
        for p in (PROVIDERS[n] for n in PROVIDER_NAMES)
    )

    parser = argparse.ArgumentParser(
        prog="pr-review",
        description=(
            "PR Review Bot — automated code review powered by Gemini, Groq, "
            "or OpenRouter."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Providers and their environment variables:\n"
            f"{provider_help_lines}\n\n"
            "Other environment variables:\n"
            "  GH_TOKEN            Required only with --post-comment.\n\n"
            "Examples:\n"
            "  pr-review\n"
            "  pr-review --base develop\n"
            "  pr-review --provider groq\n"
            "  pr-review --provider gemini --model gemini-1.5-pro\n"
            "  pr-review --post-comment --pr 42 --github-repo owner/repo\n"
        ),
    )

    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        metavar="BRANCH",
        help=f"Base branch to compare against (default: {DEFAULT_BASE})",
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Path to the git repository (default: current directory)",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default=None,
        metavar="PROVIDER",
        help=(
            "LLM provider to use: %(choices)s. "
            "Auto-detected from environment variables if not specified. "
            "Each provider requires its own API key env var "
            "(see epilog for details)."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Model name to pass to the provider. "
            "Defaults to the provider's default model if not set."
        ),
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
        "--max-diff-chars",
        type=int,
        default=MAX_DIFF_CHARS,
        metavar="N",
        help=(
            f"Truncate the git diff to this many characters before sending "
            f"(default: {MAX_DIFF_CHARS:,})"
        ),
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
        help=(
            "GitHub repository slug, e.g. acme/backend (optional with --post-comment)"
        ),
    )

    return parser


def main() -> None:
    # Load .env file before anything reads environment variables.
    # Existing shell env vars always take precedence (override=False is the default).
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Validate argument combinations
    # ------------------------------------------------------------------
    if args.post_comment and not args.pr:
        parser.error("--pr NUMBER is required when using --post-comment")

    # ------------------------------------------------------------------
    # Resolve paths
    # ------------------------------------------------------------------
    repo = os.path.abspath(args.repo)

    # Disable streaming when we need to collect the full text for a comment
    use_stream = not args.no_stream and not args.post_comment

    # ------------------------------------------------------------------
    # Run the review
    # ------------------------------------------------------------------
    full_review = run_review(
        repo=repo,
        base=args.base,
        provider_key=args.provider,
        model=args.model,
        prompt_name=args.prompt,
        stream=use_stream,
        max_diff_chars=args.max_diff_chars,
        max_tokens=args.max_tokens,
    )

    # ------------------------------------------------------------------
    # Optionally post to GitHub
    # ------------------------------------------------------------------
    if args.post_comment:
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
