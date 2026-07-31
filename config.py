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

SCORING = {
    # Below this, evaluator/scorer.py auto-rejects instead of leaving it in 'new'. Reversible.
    "auto_reject_at_or_below": 1.0,
}

QUERY_PRUNING = {
    "source": "linkedin",  # only source slow/paced enough for wasted queries to matter
    "min_terminal_sample": 20,  # terminally-decided jobs needed before a reject rate is trusted
    "reject_rate_threshold": 0.95,  # LinkedIn's baseline reject rate is already ~0.65
    "min_searches_for_zero_yield": 5,  # never excluded if it's produced any applied/reviewed job
}

RANKING = {
    "top_n_rerank":        50,
    "top_n_listwise":      20,
    "auto_distill_after":  25,
    "min_score_for_ranking": 2.0,  # below scorer's own near-dealbreaker cutoff — skip paid ranking
}

WOULD_APPLY = {
    # Phase 1 of auto-apply: flag-and-validate only. Absolute floor (2026-07-26: 4/222 active jobs cleared it).
    "score_floor": 7.0,
}

# Pricing — verified live against docs.anthropic.com / docs.voyageai.com, July 2026.
# Update if Anthropic/Voyage change their rates. Format: (input $/1M tokens, output $/1M tokens)
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":            (5.00,  25.00),   # was (15, 75) — Opus 4.8 launched at a lower rate
    "claude-sonnet-4-6":          (3.00,  15.00),
    "claude-haiku-4-5-20251001":  (1.00,   5.00),   # was (0.25, 1.25) — undercounted actual Haiku 4.5 rate
    "voyage-3-large":             (0.18,   0.00),   # was 0.06 — per 1M embed tokens
    "rerank-2":                   (0.05,   0.00),   # per 1M tokens (rerank billing is now token-based, not per-query)
}

# Prompt-cache pricing is a fixed multiplier of a model's base input rate, same across
# every Claude model (docs.anthropic.com). Only the default 5-minute ephemeral TTL is
# used anywhere in this codebase (evaluator/scorer.py's cache_control), so there's no
# 1-hour-TTL rate to track.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER  = 0.1

_ROOT = os.path.dirname(os.path.abspath(__file__))

LINKEDIN = {
    "search_url": "https://www.linkedin.com/jobs/search/",
}

AGENT = {
    "headless": False,
    "reports_path": "data/reports",
    "seed_urls_path": "data/seed_urls.txt",
    "chrome_profile": "data/chrome_profile",
}

# WireGuard tunnel address, not the public HTTPS URL — Caddy's basic_auth in front of
# the public site blocks API traffic the same as browser traffic. Requires the tunnel;
# a real multi-user setup needs Caddy to let /api/* through instead (not needed yet).
JOBAGENTWEB_BASE_URL = os.getenv("JOBAGENTWEB_BASE_URL", "http://10.66.0.1:8000")

STEALTH = {
    "desc_delay_min": 8,   # reading-time delay after a description loads, clamped to this range
    "desc_delay_max": 45,
    "desc_reading_wpm": 200,
    "search_glance_min": 5,   # flat "glance at results" pause, plus below per newly-found job
    "search_glance_max": 20,
    "search_new_min": 10,
    "search_new_max": 30,
    "batch_size": 10,          # descriptions fetched per browser session
    "batch_pause_min": 120,    # pause between description batches, seconds
    "batch_pause_max": 600,
    "distract_every_n_batches": 2,  # visit LinkedIn feed every N batches (0 = never)
}

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found. Add it to .env.")
if not VOYAGE_API_KEY:
    raise ValueError("VOYAGE_API_KEY not found. Add it to .env. Get one at voyageai.com.")
