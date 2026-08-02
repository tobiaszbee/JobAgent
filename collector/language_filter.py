import logging

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from db.repositories import candidate_preferences_repository, job_repository

logger = logging.getLogger(__name__)

# langdetect's classifier is randomly seeded by default, which would make results
# (and this filter's rejections) non-reproducible run to run.
DetectorFactory.seed = 0

# Every language langdetect's classifier can actually recognize (see its `profiles/`
# directory) — the candidate can type any language name in the questionnaire (free
# text with suggestions, not a fixed dropdown), so this covers the full set the
# detector supports, not just a handful. A name not in this table simply can't be
# matched against a detection result and is ignored (see _candidate_language_codes).
_LANGUAGE_CODES = {
    "afrikaans": "af", "arabic": "ar", "bulgarian": "bg", "bengali": "bn", "catalan": "ca",
    "czech": "cs", "welsh": "cy", "danish": "da", "german": "de", "greek": "el",
    "english": "en", "spanish": "es", "estonian": "et", "persian": "fa", "farsi": "fa",
    "finnish": "fi", "french": "fr", "gujarati": "gu", "hebrew": "he", "hindi": "hi",
    "croatian": "hr", "hungarian": "hu", "indonesian": "id", "italian": "it", "japanese": "ja",
    "kannada": "kn", "korean": "ko", "lithuanian": "lt", "latvian": "lv", "macedonian": "mk",
    "malayalam": "ml", "marathi": "mr", "nepali": "ne", "dutch": "nl", "norwegian": "no",
    "punjabi": "pa", "polish": "pl", "portuguese": "pt", "romanian": "ro", "russian": "ru",
    "slovak": "sk", "slovenian": "sl", "somali": "so", "albanian": "sq", "swedish": "sv",
    "swahili": "sw", "tamil": "ta", "telugu": "te", "thai": "th", "tagalog": "tl",
    "filipino": "tl", "turkish": "tr", "ukrainian": "uk", "urdu": "ur", "vietnamese": "vi",
    "chinese": "zh-cn", "chinese (simplified)": "zh-cn", "mandarin": "zh-cn",
    "chinese (traditional)": "zh-tw", "cantonese": "zh-tw",
}

_MIN_TEXT_LEN = 20  # shorter text is unreliable for language detection — skip, don't reject


def _candidate_language_codes() -> set[str]:
    prefs = candidate_preferences_repository.get_active()
    if not prefs:
        return set()
    codes = set()
    for entry in prefs.get("languages") or []:
        code = _LANGUAGE_CODES.get((entry.get("language") or "").strip().lower())
        if code:
            codes.add(code)
    return codes


def _detected_codes(text: str) -> set[str]:
    """All plausible languages for this text (not just the top guess) — a posting
    that mixes two languages (e.g. a German company writing tech requirements in
    English) should match if the candidate speaks either one."""
    try:
        return {lang.lang for lang in detect_langs(text)}
    except LangDetectException:
        return set()


def apply_language_filter(jobs: list[dict] | None = None) -> dict:
    """Hard-reject jobs written in a language the candidate didn't select in the
    questionnaire. Deterministic, no LLM call — runs as early as possible, right
    after collection, before any paid filter/scoring step. Skips gracefully (never
    rejects) when the candidate hasn't configured any languages, the text is too
    short, or detection is inconclusive — absence of a clear signal is never
    treated as a violation.

    `jobs` lets a caller that's also running apply_keyword_filter() share one
    get_new() fetch instead of each independently pulling the full 'new' pool
    (with descriptions) over HTTP. Defaults to fetching its own when omitted."""
    candidate_codes = _candidate_language_codes()
    if not candidate_codes:
        return {"checked": 0, "auto_rejected": 0, "rejected_ids": []}

    if jobs is None:
        jobs = job_repository.get_new()
    auto_rejected = 0
    rejected_ids = []

    for job in jobs:
        text = f"{job['title']} {job.get('description') or ''}".strip()
        if len(text) < _MIN_TEXT_LEN:
            continue

        detected = _detected_codes(text)
        if not detected or not detected.isdisjoint(candidate_codes):
            continue

        reason = (
            f"Auto-rejected: posting language ({'/'.join(sorted(detected))}) "
            f"not in your selected languages ({'/'.join(sorted(candidate_codes))})"
        )
        job_repository.update_score_and_status(job["id"], 0.0, reason, "auto_rejected")
        auto_rejected += 1
        rejected_ids.append(job["id"])
        logger.info(f"  [language] {job['title']} @ {job['company']} — {reason}")

    return {"checked": len(jobs), "auto_rejected": auto_rejected, "rejected_ids": rejected_ids}
