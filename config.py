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

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found. Create a .env file with your API key.")
