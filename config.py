import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-6"

LINKEDIN = {
    "search_url": "https://www.linkedin.com/jobs/search/",
}

AGENT = {
    "headless": False,
    "db_path": "data/agent.db",
    "reports_path": "data/reports",
    "seed_urls_path": "data/seed_urls.txt",
    "chrome_profile": "data/chrome_profile",
}

STEALTH = {
    # Delay between description page loads (seconds) — beta-distributed, skewed short
    "desc_delay_min": 25,
    "desc_delay_max": 90,
    # Delay between search queries/locations (seconds)
    "search_pause_min": 90,
    "search_pause_max": 480,
    # Number of descriptions fetched per browser session
    "batch_size": 7,
    # Pause between description batches (seconds) — 10 to 30 min
    "batch_pause_min": 600,
    "batch_pause_max": 1800,
    # Visit LinkedIn feed every N batches (0 = never)
    "distract_every_n_batches": 2,
    # Random startup delay max (seconds) used by scheduler
    "startup_delay_max": 5400,   # 90 minutes
}

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found. Create a .env file with your API key.")
