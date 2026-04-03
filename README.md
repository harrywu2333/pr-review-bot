# PR Review Bot 🤖

An automated pull-request code reviewer powered by [Claude](https://www.anthropic.com/claude). Drop it into any Python repo and get Staff-Engineer-level feedback on every PR — locally or via GitHub Actions.

---

## Features

- **Zero noise** — ignores formatting/style (assumes `ruff`/`flake8` in CI), focuses only on logic flaws, security risks, and resource leaks
- **Streaming output** — review appears token-by-token in your terminal
- **GitHub Actions ready** — use as a reusable composite action or copy the bundled workflow
- **PR comments** — optionally posts the review directly to the GitHub PR via the `gh` CLI
- **Configurable** — swap base branch, Claude model, or prompt file via flags

---

## Quick Start (Local)

```bash
# 1. Clone / copy this repo
git clone https://github.com/your-org/pr-review-bot.git
cd pr-review-bot

# 2. Install dependencies
pip install -r requirements.txt
# — or install as a CLI tool —
pip install .

# 3. Set your Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# 4. Run from inside the repo you want to review
cd /path/to/your-project
python /path/to/pr-review-bot/review.py
```

Get your API key at <https://console.anthropic.com/>.

---

## Usage

```
usage: review.py [-h] [--base BRANCH] [--repo PATH] [--model MODEL]
                 [--prompt NAME] [--no-stream]
                 [--post-comment] [--pr NUMBER] [--github-repo OWNER/REPO]

PR Review Bot — automated code review powered by Claude.

options:
  --base BRANCH          Base branch to diff against          (default: main)
  --repo PATH            Path to the git repository           (default: .)
  --model MODEL          Claude model to use                  (default: claude-sonnet-4-5)
  --prompt NAME          Prompt file in prompts/ without .md  (default: pr_review)
  --no-stream            Disable streaming; print all at once
  --post-comment         Post review as a GitHub PR comment via gh CLI
  --pr NUMBER            PR number (required with --post-comment)
  --github-repo OWNER/REPO  Target repo for --post-comment
```

### Examples

```bash
# Review current branch against main (streaming)
review.py

# Review against a different base branch
review.py --base develop

# Use Claude Opus for a deeper review
review.py --model claude-opus-4-5

# Post result directly to GitHub PR #42
review.py --post-comment --pr 42 --github-repo owner/repo
```

If installed via `pip install .`, replace `review.py` with `pr-review`.

---

## GitHub Actions Integration

### Option A — Reusable composite action (recommended)

Add this workflow to **your target repository** (`.github/workflows/pr-review.yml`):

```yaml
name: PR Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    name: AI Code Review
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # full history required for git diff

      - uses: your-org/pr-review-bot@main
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          base_branch:       ${{ github.base_ref }}
          pr_number:         ${{ github.event.pull_request.number }}
          github_token:      ${{ secrets.GITHUB_TOKEN }}
```

Then add `ANTHROPIC_API_KEY` as a repository secret
(*Settings → Secrets and variables → Actions → New repository secret*).

### Option B — Self-contained workflow (no external action)

Copy `.github/workflows/pr-review.yml` from this repo directly into your target repository. It uses the same secrets and runs the script inline.

---

## Customising the Prompt

The review logic lives entirely in `prompts/pr_review.md`. Edit it to:

- Change the severity labels
- Add project-specific rules (e.g. "also flag missing `pytest` fixtures")
- Switch the primary language context

You can maintain multiple prompt files and select them with `--prompt`:

```bash
review.py --prompt security_audit   # uses prompts/security_audit.md
```

---

## Models

| Model | Speed | Quality | Recommended for |
|---|---|---|---|
| `claude-sonnet-4-5` *(default)* | Fast | High | Daily PR feedback |
| `claude-opus-4-5` | Slower | Highest | Pre-release / security audits |
| `claude-haiku-4-5` | Fastest | Good | Draft / WIP PRs |

---

## Project Structure

```
pr-review-bot/
├── prompts/
│   └── pr_review.md          # System prompt (edit to customise)
├── pr_review_bot/
│   ├── __init__.py
│   └── cli.py                # Core logic (importable module)
├── .github/
│   └── workflows/
│       └── pr-review.yml     # Copy this into your target repo
├── action.yml                # GitHub composite action entry-point
├── review.py                 # Standalone CLI entry-point
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Requirements

- Python ≥ 3.9
- `anthropic` ≥ 0.40.0
- `git` in `PATH`
- `gh` CLI (only needed for `--post-comment`)

---

## License

MIT — see [LICENSE](LICENSE).