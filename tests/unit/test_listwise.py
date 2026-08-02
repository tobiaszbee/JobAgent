import json
from unittest.mock import MagicMock, patch

from ranker.listwise import _format_job, listwise_rank


def _job(id="j1", title="Senior Dev", company="Acme", location="Remote", description="Good job", structured_data=None):
    return {
        "id": id, "title": title, "company": company,
        "location": location, "description": description,
        "structured_data": json.dumps(structured_data) if structured_data else None,
    }


def _make_ranking_response(ranking: list[dict]):
    """Simulate Opus text response with JSON inside <ranking> tags."""
    import json as _json
    block = MagicMock()
    block.type = "text"
    block.text = f"<ranking>\n{_json.dumps(ranking, indent=2)}\n</ranking>"
    response = MagicMock()
    response.content = [block]
    response.usage = MagicMock(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return response


def _make_empty_response():
    response = MagicMock()
    response.content = []
    response.usage = MagicMock(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return response


class TestFormatJob:
    def test_includes_title_company(self):
        text = _format_job(_job(title="Engineer", company="Corp"), 0)
        assert "Engineer" in text
        assert "Corp" in text

    def test_includes_description_excerpt(self):
        text = _format_job(_job(description="We use Python and Django"), 0)
        assert "Python" in text

    def test_structured_data_tags_appear(self):
        sd = {"remote": True, "seniority": "senior", "company_type": "startup",
              "product_vs_outsourcing": "product", "stack": ["Python"],
              "hybrid": False, "salary_min": None, "salary_max": None, "salary_currency": None}
        text = _format_job(_job(structured_data=sd), 0)
        assert "remote" in text.lower()
        assert "senior" in text.lower()
        assert "startup" in text.lower()


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_assigns_sequential_ranks(mock_anthropic):
    jobs = [_job("j1", "Dev A"), _job("j2", "Dev B"), _job("j3", "Dev C")]
    ranking = [
        {"job_id": "j2", "reason": "Best match"},
        {"job_id": "j1", "reason": "Good"},
        {"job_id": "j3", "reason": "Decent"},
    ]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(ranking)

    result = listwise_rank(jobs, "Candidate with Python", [])
    assert len(result) == 3
    ids_in_order = [r["id"] for r in result]
    assert ids_in_order == ["j2", "j1", "j3"]
    assert result[0]["listwise_rank"] == 1
    assert result[1]["listwise_rank"] == 2
    assert result[2]["listwise_rank"] == 3


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_includes_reasons(mock_anthropic):
    jobs = [_job("j1"), _job("j2")]
    ranking = [
        {"job_id": "j1", "reason": "Perfect stack match"},
        {"job_id": "j2", "reason": "Too junior"},
    ]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(ranking)

    result = listwise_rank(jobs, "", [])
    assert result[0]["rank_reason"] == "Perfect stack match"
    assert result[1]["rank_reason"] == "Too junior"


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_safety_net_adds_missed_jobs(mock_anthropic):
    jobs = [_job("j1"), _job("j2"), _job("j3")]
    ranking = [{"job_id": "j1", "reason": "Best"}]  # j2, j3 omitted by Opus
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(ranking)

    result = listwise_rank(jobs, "", [])
    ids = [r["id"] for r in result]
    assert "j1" in ids and "j2" in ids and "j3" in ids
    assert result[0]["listwise_rank"] == 1
    assert len(result) == 3


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_no_duplicate_ranks_when_hallucinated_id_precedes_an_omission(mock_anthropic):
    # Regression: rank_pos used to come from enumerate(ranking)'s raw index,
    # which still advances past a skipped (hallucinated) job_id — leaving a
    # gap the safety-net loop (numbering from len(result) + 1) could collide
    # with. Here "ghost" (hallucinated) precedes "j2", and "j3" is omitted
    # entirely — j2 used to land on the same listwise_rank as j3's safety-net
    # entry.
    jobs = [_job("j1"), _job("j2"), _job("j3")]
    ranking = [
        {"job_id": "j1", "reason": "Best"},
        {"job_id": "ghost", "reason": "Hallucinated id, not a real job"},
        {"job_id": "j2", "reason": "Second"},
    ]  # j3 omitted by Opus
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(ranking)

    result = listwise_rank(jobs, "", [])
    ranks = [r["listwise_rank"] for r in result]
    assert len(ranks) == len(set(ranks)), f"duplicate listwise_rank values: {ranks}"
    assert sorted(ranks) == [1, 2, 3]
    ids_by_rank = {r["listwise_rank"]: r["id"] for r in result}
    assert ids_by_rank[1] == "j1"
    assert ids_by_rank[2] == "j2"
    assert ids_by_rank[3] == "j3"  # safety net, correctly placed after the compacted real ranks


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_fallback_on_api_error(mock_anthropic):
    jobs = [_job("j1"), _job("j2")]
    mock_anthropic.return_value.messages.create.side_effect = Exception("API down")

    result = listwise_rank(jobs, "", [])
    assert len(result) == 2
    assert result[0]["listwise_rank"] == 1
    assert result[1]["listwise_rank"] == 2


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_fallback_on_no_tool_block(mock_anthropic):
    jobs = [_job("j1")]
    mock_anthropic.return_value.messages.create.return_value = _make_empty_response()

    result = listwise_rank(jobs, "", [])
    assert result[0]["listwise_rank"] == 1


def test_listwise_rank_empty_input():
    result = listwise_rank([], "", [])
    assert result == []


@patch("ranker.listwise.anthropic.Anthropic")
def test_system_prompt_forbids_deliberation_in_reason(mock_anthropic):
    # Opus has leaked raw self-correction ("wait, correcting...") directly into a
    # "reason" value before — guard against the prompt instruction being dropped.
    jobs = [_job("j1")]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(
        [{"job_id": "j1", "reason": "Good match"}]
    )

    listwise_rank(jobs, "", [])

    system_prompt = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "deliberation" in system_prompt.lower() or "wait, correcting" in system_prompt.lower()
