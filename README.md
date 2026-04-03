# PR Review Bot 🤖

An automated pull-request code reviewer powered by [Google Gemini](https://aistudio.google.com/), [Groq](https://console.groq.com/), or [OpenRouter](https://openrouter.ai/). Drop it into any Python repo and get Staff-Engineer-level feedback on every PR — locally or via GitHub Actions.

---

## Features

- **Zero noise** — ignores formatting/style (assumes `ruff`/`flake8` in CI), focuses only on logic flaws, security risks, and resource leaks
- **Multi-provider** — works with Gemini, Groq, or OpenRouter; auto-detects provider from the API key you set
- **Streaming output** — review appears token-by-token in your terminal
- **GitHub Actions ready** — use as a reusable composite action or copy the bundled workflow
- **PR comments** — optionally posts the review directly to the GitHub PR via the `gh` CLI
- **Configurable** — swap base branch, model, or prompt file via flags

---

## Supported Providers

| Provider | Env Var | Default Model | Get Key |
|---|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.0-flash` | https://aistudio.google.com/ |
| Groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` | https://console.groq.com/ |
| OpenRouter | `OPENROUTER_API_KEY` | `google/gemini-2.0-flash-001` | https://openrouter.ai/ |

Set **exactly one** key and the provider is detected automatically. If you have multiple keys, pass `--provider` to choose.

---

## Quick Start (Local)

```bash
pip install -r requirements.txt
# — or install as a CLI tool —
pip install .

# Set exactly ONE of these (auto-detects provider):
export GEMINI_API_KEY=...
# export GROQ_API_KEY=...
# export OPENROUTER_API_KEY=...

cd /path/to/your-project
python /path/to/pr-review-bot/review.py
```

---

## Usage

```
usage: pr-review [-h] [--provider {gemini,groq,openrouter}]
                 [--base BRANCH] [--repo PATH] [--model MODEL]
                 [--prompt NAME] [--no-stream] [--max-diff-chars N]
                 [--post-comment] [--pr NUMBER] [--github-repo OWNER/REPO]

PR Review Bot — automated code review powered by Gemini, Groq, or OpenRouter.

options:
  --provider {gemini,groq,openrouter}
                         LLM provider to use. Auto-detected when exactly one
                         API key env var is set. Required when multiple keys
                         are present.
  --base BRANCH          Base branch to diff against          (default: main)
  --repo PATH            Path to the git repository           (default: .)
  --model MODEL          Model ID to use (defaults to provider's default model)
  --prompt NAME          Prompt file in prompts/ without .md  (default: pr_review)
  --no-stream            Disable streaming; print all at once
  --max-diff-chars N     Truncate the diff at N chars before sending to model
                         (default: 120,000). Increase for large PRs.

GitHub integration:
  --post-comment         Post review as a GitHub PR comment via gh CLI
  --pr NUMBER            PR number (required with --post-comment)
  --github-repo OWNER/REPO
                         Target repo slug for --post-comment (e.g. octocat/hello-world)
```

If installed via `pip install .`, the `pr-review` command is available globally.

---

## Examples

```bash
# Auto-detect provider from whichever key is set, review against main
pr-review

# Use Groq explicitly
export GROQ_API_KEY=gsk_...
pr-review --provider groq

# Use Gemini with a specific model
export GEMINI_API_KEY=AIza...
pr-review --provider gemini --model gemini-2.0-flash

# Use OpenRouter with a custom model
export OPENROUTER_API_KEY=sk-or-...
pr-review --provider openrouter --model meta-llama/llama-3.3-70b-instruct

# Review against a different base branch
pr-review --base develop

# Review a repo at a specific path
pr-review --repo ~/projects/my-app

# Post the review as a GitHub PR comment (requires `gh` CLI authenticated)
pr-review --post-comment --pr 42

# Post to a specific repo
pr-review --post-comment --pr 42 --github-repo owner/repo

# Non-streaming (collect full response before printing)
pr-review --no-stream
```

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
    name: Automated Code Review
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: read

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run PR Review Bot
        uses: your-org/pr-review-bot@main
        with:
          # Set whichever API key(s) you have as repo secrets.
          # The bot auto-detects the provider when exactly one key is set.
          # Set `provider:` explicitly if you have multiple keys configured.
          gemini_api_key:      ${{ secrets.GEMINI_API_KEY }}
          groq_api_key:        ${{ secrets.GROQ_API_KEY }}
          openrouter_api_key:  ${{ secrets.OPENROUTER_API_KEY }}
          # provider: gemini   # uncomment to force a specific provider
          base_branch:  ${{ github.base_ref }}
          pr_number:    ${{ github.event.pull_request.number }}
```

Then add your chosen API key as a repository secret
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
pr-review --prompt security_audit   # uses prompts/security_audit.md
```

---

## Project Structure

```
pr-review-bot/
├── prompts/
│   └── pr_review.md          # System prompt (edit to customise)
├── pr_review_bot/
│   ├── __init__.py
│   ├── providers.py          # Provider configs & OpenAI-compatible clients
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
- `openai` ≥ 1.0.0
- `git` in `PATH`
- `gh` CLI (only needed for `--post-comment`)

---

## License

MIT — see [LICENSE](LICENSE).