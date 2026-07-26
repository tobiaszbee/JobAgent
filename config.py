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
    # Jobs scored at/below this by evaluator/scorer.py are auto-rejected (status
    # "auto_rejected") right away instead of sitting in 'new' for manual review —
    # score_reason at this level is reliably "no PHP", "wrong field entirely",
    # "US-citizens-only", etc. Reversible: auto_rejected jobs stay in the DB and
    # are visible/re-evaluable from the dashboard's Auto-rejected tab.
    "auto_reject_at_or_below": 1.0,
}

QUERY_PRUNING = {
    # LinkedIn only (config.STEALTH's slow, paced collection is what makes wasted
    # queries expensive — the other sources are cheap plain-HTTP fetches where
    # pruning isn't worth the risk of losing a rarely-hitting-but-good query).
    "source": "linkedin",
    # A query needs this many *terminally decided* jobs (status != 'new') before
    # its reject rate is trusted at all — small samples are noise, not signal.
    "min_terminal_sample": 20,
    # Must clear this well above the source's overall baseline reject rate (real
    # LinkedIn baseline observed ~0.65) to count as "this specific query is bad",
    # not just "most jobs get rejected anyway".
    "reject_rate_threshold": 0.95,
    # Even at a high reject rate, a query that has produced any applied/reviewed
    # job is never auto-excluded — see get_query_outcome_stats().
    # Separate, reject-rate-independent signal: searched this many times with
    # zero new (non-duplicate) jobs found across every single search.
    "min_searches_for_zero_yield": 5,
}

RANKING = {
    "top_n_rerank":        50,
    "top_n_listwise":      20,
    "auto_distill_after":  25,
    # Jobs already scored at/below this (scorer's own "near dealbreaker" cutoff,
    # see evaluator/scorer.py _LEGEND) are excluded from the rerank/listwise pool
    # entirely — no point spending Voyage/Opus calls ranking jobs already known
    # to be bad, and it keeps them from crowding out real candidates in the
    # top-N pools. Jobs not yet scored (score IS NULL) are still included.
    "min_score_for_ranking": 2.0,
}

WOULD_APPLY = {
    # Phase 1 of the auto-apply plan: flag jobs the agent would apply to, for the
    # candidate to validate — never sends anything. Gate is an absolute score
    # floor (not a relative top-N cut), so a weak ranking run yields zero flagged
    # jobs instead of always flagging "the best of a bad batch". Real distribution
    # check (2026-07-26, 222 active jobs): only 4 clear 7.0 — deliberately narrow,
    # since a false "would apply" is the exact risk being tested for before any
    # real auto-send is considered.
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

# "sqlite" (default, used by the whole test suite) or "postgres" (real local +
# JobAgentWeb usage, both pointed at the same server-hosted DB — see
# db/connection.py). Never set to "postgres" in tests; tests always redirect
# AGENT["db_path"] to a temp SQLite file and never touch this.
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")

POSTGRES = {
    "host":     os.getenv("POSTGRES_HOST", "localhost"),
    "port":     int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname":   os.getenv("POSTGRES_DB", "jobagent"),
    "user":     os.getenv("POSTGRES_USER", "jobagent"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

# "local" (default): full JobAgent, every blueprint registered, RunAgent/collector
# available. "web": JobAgentWeb — browse jobs + change status only, no pipeline
# actions. See web/app.py.
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "local")

STEALTH = {
    # Reading-time delay after a description loads: scaled to word count (below),
    # clamped to this range so very short/long postings stay plausible.
    "desc_delay_min": 8,
    "desc_delay_max": 45,
    "desc_reading_wpm": 200,
    # Post-search pause: a flat "glance at the results" component (always applied,
    # duplicates need no extra look) plus a per-newly-found-job "reading" component
    # (duplicates add nothing; a search with 5 new jobs takes longer than one with 0).
    "search_glance_min": 5,
    "search_glance_max": 20,
    "search_new_min": 10,
    "search_new_max": 30,
    # Number of descriptions fetched per browser session
    "batch_size": 10,
    # Pause between description batches (seconds) — 2 to 10 min
    "batch_pause_min": 120,
    "batch_pause_max": 600,
    # Visit LinkedIn feed every N batches (0 = never)
    "distract_every_n_batches": 2,
}

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found. Add it to .env.")
if not VOYAGE_API_KEY:
    raise ValueError("VOYAGE_API_KEY not found. Add it to .env. Get one at voyageai.com.")
