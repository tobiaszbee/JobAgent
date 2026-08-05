import logging

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from db.repositories import candidate_preferences_repository, job_repository

logger = logging.getLogger(__name__)

# langdetect's classifier is randomly seeded by default, which would make results
# (and this filter's rejections) non-reproducible run to run.
DetectorFactory.seed = 0

# Every language langdetect's classifier can recognize (see its `profiles/`
# directory), since the questionnaire lets the candidate type any language
# name. A name not in this table can't be matched and is ignored.
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

_MIN_TEXT_LEN = 20  # shorter text is unreliable for language detection, skip, don't reject

# CEFR proficiency ordering, low to high, questionnaire.js's LEVEL_OPTIONS.
_CEFR_RANK = {"a1": 0, "a2": 1, "b1": 2, "b2": 3, "c1": 4, "c2": 5, "native": 6}
# B2 is the conventional minimum for actually working in a language, not just
# reading a posting written in it.
_MIN_WORKING_LEVEL = _CEFR_RANK["b2"]


def _candidate_language_codes() -> set[str]:
    prefs = candidate_preferences_repository.get_active()
    if not prefs:
        return set()
    codes = set()
    for entry in prefs.get("languages") or []:
        level_rank = _CEFR_RANK.get((entry.get("level") or "").strip().lower())
        # Unrecognized/missing level is never treated as a violation, only an
        # explicit sub-B2 level excludes a language.
        if level_rank is not None and level_rank < _MIN_WORKING_LEVEL:
            continue
        code = _LANGUAGE_CODES.get((entry.get("language") or "").strip().lower())
        if code:
            codes.add(code)
    return codes


def _detected_codes(text: str) -> set[str]:
    # All plausible languages, not just the top guess, so a posting mixing
    # two languages matches if the candidate speaks either one.
    try:
        return {lang.lang for lang in detect_langs(text)}
    except LangDetectException:
        return set()


def apply_language_filter(jobs: list[dict] | None = None) -> dict:
    # Hard-rejects jobs written in a language the candidate didn't select.
    # Deterministic, no LLM call, runs before any paid filter/scoring step.
    # Skips gracefully rather than rejecting when signal is missing or
    # inconclusive. `jobs` lets a caller also running apply_keyword_filter()
    # share one get_new() fetch instead of each pulling its own.
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
        logger.info(f"  [language] {job['title']} @ {job['company']}, {reason}")

    return {"checked": len(jobs), "auto_rejected": auto_rejected, "rejected_ids": rejected_ids}
