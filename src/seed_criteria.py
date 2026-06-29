import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.db.migrations import run as init_db
from src.db.repositories.criteria_repository import seed_from_config
from config import JOB_CRITERIA

if __name__ == "__main__":
    init_db()
    seed_from_config(JOB_CRITERIA)
    print("Done.")
