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
| OpenRouter | `OPENROUTER_API_KEY` | **required — see below** | https://openrouter.ai/ |

Set **exactly one** key and the provider is detected automatically. If you have multiple keys, pass `--provider` to choose.

> **OpenRouter:** Because OpenRouter routes to hundreds of different models, there is no built-in default. You must always pass `--model` when using it — e.g. `--model google/gemini-2.0-flash-001`. Browse the full catalogue at <https://openrouter.ai/models>.

---

## Quick Start (Local)

```bash
pip install -r requirements.txt
# — or install as a CLI tool —
pip install .
```

**Option A — `.env` file (recommended for local use)**

```bash
cp /path/to/pr-review-bot/.env.example .env
# Edit .env and uncomment the key for your chosen provider
```

```ini
# .env
GROQ_API_KEY=gsk_...
```

**Option B — export directly in your shell**

```bash
export GROQ_API_KEY=gsk_...
```

Then run the bot from inside the repo you want to review:

```bash
cd /path/to/your-project
python /path/to/pr-review-bot/review.py
```

---

## .env File Support

The bot automatically loads a `.env` file from your **current working directory** on every run, so you never have to `export` keys in your shell manually.

```bash
# One-time setup inside your project
cp /path/to/pr-review-bot/.env.example .env
# Uncomment and fill in one key:
#   GEMINI_API_KEY=AIza...
#   GROQ_API_KEY=gsk_...
#   OPENROUTER_API_KEY=sk-or-...
```

Rules:
- **Shell env vars always win** — `.env` values are only applied when the variable is not already set in the environment.
- **`.env` is in `.gitignore`** — it will never be accidentally committed.
- The `.env.example` file (safe to commit) documents every available key.

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

# Use OpenRouter — --model is required, pick any model from https://openrouter.ai/models
export OPENROUTER_API_KEY=sk-or-...
pr-review --provider openrouter --model google/gemini-2.0-flash-001
pr-review --provider openrouter --model anthropic/claude-sonnet-4-5
pr-review --provider openrouter --model meta-llama/llama-3.3-70b-instruct
pr-review --provider openrouter --model "mistralai/mistral-small-3.2-24b-instruct:free"

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
├── .env.example              # Copy to .env and fill in your API key
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Requirements

- Python ≥ 3.9
- `openai` ≥ 1.0.0
- `python-dotenv` ≥ 1.0.0
- `git` in `PATH`
- `gh` CLI (only needed for `--post-comment`)

---

## License

MIT — see [LICENSE](LICENSE).