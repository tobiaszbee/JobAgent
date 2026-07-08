import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-6"          # CV parsing, legacy scorer
CLAUDE_EXTRACT_MODEL  = "claude-haiku-4-5-20251001"
CLAUDE_RANK_MODEL     = "claude-opus-4-8"
CLAUDE_DISTILL_MODEL  = "claude-opus-4-8"

VOYAGE_API_KEY      = os.getenv("VOYAGE_API_KEY")
VOYAGE_EMBED_MODEL  = "voyage-3-large"
VOYAGE_RERANK_MODEL = "rerank-2"

RANKING = {
    "top_n_rerank":        50,
    "top_n_listwise":      20,
    "auto_distill_after":  25,
}

# Approximate pricing — update if Anthropic/Voyage change their rates.
# Format: (input $/1M tokens, output $/1M tokens)
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":            (15.00, 75.00),
    "claude-sonnet-4-6":          (3.00,  15.00),
    "claude-haiku-4-5-20251001":  (0.25,   1.25),
    "voyage-3-large":             (0.06,   0.00),   # per 1M embed tokens
    "rerank-2":                   (0.05,   0.00),   # per 1K queries (stored as input_tokens)
}

_ROOT = os.path.dirname(os.path.abspath(__file__))

LINKEDIN = {
    "search_url": "https://www.linkedin.com/jobs/search/",
}

AGENT = {
    "headless": False,
    "db_path": os.path.join(_ROOT, "data", "agent.db"),
    "reports_path": "data/reports",
    "seed_urls_path": "data/seed_urls.txt",
    "chrome_profile": "data/chrome_profile",
}

STEALTH = {
    # Delay between description page loads (seconds)
    "desc_delay_min": 8,
    "desc_delay_max": 30,
    # Delay between search queries/locations (seconds)
    "search_pause_min": 60,
    "search_pause_max": 300,
    # Number of descriptions fetched per browser session
    "batch_size": 7,
    # Pause between description batches (seconds) — 2 to 10 min
    "batch_pause_min": 120,
    "batch_pause_max": 600,
    # Visit LinkedIn feed every N batches (0 = never)
    "distract_every_n_batches": 2,
    # Random startup delay max (seconds) used by scheduler
    "startup_delay_max": 5400,   # 90 minutes
}

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found. Add it to .env.")
if not VOYAGE_API_KEY:
    raise ValueError("VOYAGE_API_KEY not found. Add it to .env. Get one at voyageai.com.")
