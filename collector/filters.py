from collector.base import RawJob


def apply_filters(jobs: list[RawJob], rejected_keywords: list[str]) -> list[RawJob]:
    """
    Drop jobs where title, company, or location contains a rejected keyword.
    Runs before description fetching to avoid wasting time on obvious rejects.
    """
    if not rejected_keywords:
        return jobs

    lowered = [kw.lower() for kw in rejected_keywords]
    result = []
    for job in jobs:
        text = f"{job.title} {job.company} {job.location}".lower()
        if any(kw in text for kw in lowered):
            continue
        result.append(job)
    return result
