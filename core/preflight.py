import logging
import os

logger = logging.getLogger(__name__)


def check_required_env():
    has_llm = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not has_llm:
        raise RuntimeError(
            "No LLM provider key set. Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY in your .env file."
        )
    for var in ("SENTRY_WEBHOOK_SECRET", "ROLLBAR_ACCESS_TOKEN", "GITHUB_TOKEN"):
        if not os.environ.get(var):
            logger.warning("Optional env var %s not set — related features will be disabled.", var)
