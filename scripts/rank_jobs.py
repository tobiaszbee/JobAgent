"""
Re-rank the entire active ('new') job pool using the full AI pipeline:
1. Semantic similarity (Voyage embeddings) — broad recall
2. Voyage cross-encoder rerank (top-50) — precision
3. Claude Opus listwise ranking with extended thinking (top-20) — final ordering

Runs over ALL 'new' jobs every time (not just newly-collected ones), so listwise_rank
stays comparable across the whole list instead of being scoped to one day's batch.
"""
import sys
import logging

sys.stdout.reconfigure(line_buffering=True)
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
logger = logging.getLogger(__name__)

import api_client
from db.repositories import job_repository, preference_repository
from embeddings.indexer import score_pool_by_similarity, index_jobs
from ranker.fusion import fuse_by_rrf
from ranker.reranker import rerank_jobs
from ranker.listwise import listwise_rank
from ranker.debate import debate_rank
from ranker.rank_cache import reuse_if_unchanged
from ranker.would_apply import compute_would_apply
from evaluator.profile import load_active_profile, load_questionnaire_preferences, build_hyde_query
from config import RANKING

try:
    candidate_profile = load_active_profile()
except ValueError as e:
    logger.warning(f"No CV profile: {e} — ranking without candidate context")
    candidate_profile = ""

latest_pref = preference_repository.get_latest()
preferences = latest_pref["signals"] if latest_pref else []
questionnaire = load_questionnaire_preferences()
retrieval_query = build_hyde_query(candidate_profile, questionnaire)

RANKING_POOL_LIMIT = 2000
jobs = job_repository.get_jobs_for_ranking(limit=RANKING_POOL_LIMIT)
if not jobs:
    print("No active jobs to rank.")
    sys.exit(0)
if len(jobs) == RANKING_POOL_LIMIT:
    print(f"WARNING: active job pool hit the safety cap ({RANKING_POOL_LIMIT}) — oldest 'new' jobs beyond this were not considered this run.")

print(f"Processing {len(jobs)} active job(s)...")

# Step 1: Index any missing embeddings
existing_ids = set(api_client.get("/api/embeddings/ids").json()["job_ids"])
unindexed = [j for j in jobs if j["id"] not in existing_ids]
if unindexed:
    print(f"\nIndexing {len(unindexed)} new embedding(s)...")
    indexed = index_jobs(unindexed)
    print(f"  Indexed {indexed} job(s)")

# Step 2: Semantic similarity — max-sim kNN against individual applied vectors
# when there's applied history, else a single-vector cold-start fallback (see
# embeddings/indexer.py::score_pool_by_similarity for why max-sim replaced the
# old single-centroid approach).
job_ids = [j["id"] for j in jobs]
sim_scores, basis = score_pool_by_similarity(job_ids, retrieval_query)
if basis:
    print(f"\nScoring by semantic similarity to {basis}...")
    for job in jobs:
        job["_embedding_score"] = sim_scores.get(job["id"], 0.0)
    jobs_by_sim = sorted(jobs, key=lambda j: j["_embedding_score"], reverse=True)
    top_scores = [round(j["_embedding_score"], 3) for j in jobs_by_sim[:5]]
    print(f"  Top-5 similarity scores: {top_scores}")
else:
    print("\nNo applied jobs, CV profile, or questionnaire preferences — skipping semantic retrieval.")
    jobs_by_sim = jobs
    for job in jobs:
        job["_embedding_score"] = None

# Step 3: Voyage rerank (top-N)
# Exclude jobs already known (via the scorer) to be near-dealbreakers — no point
# spending Voyage/Opus calls ranking them, and it keeps them from crowding out
# real candidates in the top-N pools. Jobs not yet scored are kept (score is None).
min_score = RANKING["min_score_for_ranking"]
ranking_eligible = [j for j in jobs_by_sim if j.get("score") is None or j["score"] > min_score]
excluded_low_score = len(jobs_by_sim) - len(ranking_eligible)
if excluded_low_score:
    print(f"\nExcluding {excluded_low_score} job(s) with score <= {min_score} from the rerank/listwise pool")

# RRF instead of pure embedding-rank truncation: a job the LLM scorer rated
# highly (e.g. 9/10) but with only average cosine similarity used to never
# surface here — the min_score exclusion above was the ONLY place the
# scorer's score ever affected this pool; ordering into the top-N was 100%
# cosine similarity until now.
fused = fuse_by_rrf(ranking_eligible)
rerank_pool = fused[:RANKING["top_n_rerank"]]
if len(rerank_pool) > 1:
    print(f"\nReranking top-{len(rerank_pool)} with Voyage cross-encoder...")
    rerank_pool = rerank_jobs(rerank_pool, retrieval_query, top_k=RANKING["top_n_listwise"])
    print(f"  Got {len(rerank_pool)} after reranking")
else:
    for j in rerank_pool:
        j["rerank_score"] = j.get("_embedding_score")

# Step 4: Listwise Opus ranking + debate review (top-N) — skipped when the
# candidate set is identical to what was ranked last run, since re-running
# Opus/debate against the exact same jobs would just reproduce the same
# reasoning at full cost (the one real repeated waste flagged by the audit).
listwise_pool = rerank_pool[:RANKING["top_n_listwise"]]
reused = reuse_if_unchanged(listwise_pool, jobs)
if reused is not None:
    if reused:
        print(f"\nTop-{len(reused)} candidate set unchanged since last run — reusing previous listwise + debate results")
    ranked = reused
else:
    print(f"\nListwise ranking {len(listwise_pool)} job(s) with Claude Opus + extended thinking...")
    ranked = listwise_rank(listwise_pool, candidate_profile, preferences, questionnaire)
    print(f"\nDebate review of top-{len(ranked)} with a second model...")
    ranked = debate_rank(ranked, candidate_profile, questionnaire)

# Step 4b: Would-apply flag — phase 1 of the auto-apply plan (flag-and-validate
# only, never sends anything). See ranker/would_apply.py for the gate logic.
would_apply_items = []
would_apply_count = 0
for job in ranked:
    flagged, reason = compute_would_apply(job.get("score"), job.get("debate_flag"))
    would_apply_count += flagged
    would_apply_items.append({"job_id": job["id"], "would_apply": flagged, "reason": reason})
if would_apply_items:
    job_repository.update_would_apply_batch(would_apply_items)
if would_apply_count:
    print(f"\nWould-apply: flagged {would_apply_count}/{len(ranked)} job(s) for validation")

# Step 5: Save ranking results — one batched request for the whole pool (ranked
# jobs plus everything outside the listwise pool) instead of one PATCH per job.
ranking_items = [
    {
        "job_id": job["id"],
        "embedding_score": job.get("_embedding_score"),
        "rerank_score": job.get("rerank_score"),
        "listwise_rank": job.get("listwise_rank"),
        "rank_reason": job.get("rank_reason"),
        "debate_flag": job.get("debate_flag"),
        "debate_note": job.get("debate_note"),
    }
    for job in ranked
]

ranked_ids = {j["id"] for j in ranked}
ranking_items += [
    {
        "job_id": job["id"],
        "embedding_score": job.get("_embedding_score"),
        "rerank_score": job.get("rerank_score"),
        "listwise_rank": None,
    }
    for job in jobs_by_sim
    if job["id"] not in ranked_ids
]

if ranking_items:
    job_repository.update_ranking_scores_batch(ranking_items)

print(f"\nDone. Listwise ranked: {len(ranked)} | Embedding-scored only: {len(jobs) - len(ranked)}")
if ranked:
    print("\nTop 5:")
    for job in ranked[:5]:
        print(f"  #{job['listwise_rank']} {job['title']} @ {job['company']} — {job.get('rank_reason', '')[:80]}")
