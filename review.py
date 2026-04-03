#!/usr/bin/env python3
"""
PR Review Bot — Automated code review powered by Gemini, Groq, or OpenRouter.

Quick start (pick one provider):

  # Google Gemini
  pip install openai
  export GEMINI_API_KEY=AIza...
  python review.py

  # Groq
  pip install openai
  export GROQ_API_KEY=gsk_...
  python review.py

  # OpenRouter
  pip install openai
  export OPENROUTER_API_KEY=sk-or-...
  python review.py

The provider is auto-detected from whichever API key env var is set.
If more than one key is set, pass --provider explicitly:

  python review.py --provider gemini

Environment variables:
  GEMINI_API_KEY        Google Gemini API key  (https://aistudio.google.com/)
  GROQ_API_KEY          Groq API key           (https://console.groq.com/)
  OPENROUTER_API_KEY    OpenRouter API key     (https://openrouter.ai/)

Run `python review.py --help` for the full list of options.
"""

from __future__ import annotations

import os
import sys

# Make the package importable when this script is run directly from a clone,
# even without `pip install .`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pr_review_bot.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
