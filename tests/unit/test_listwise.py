import json
from unittest.mock import MagicMock, patch

from ranker.listwise import FALLBACK_RANK_REASON, OMITTED_RANK_REASON, _format_job, listwise_rank


def _job(id="j1", title="Senior Dev", company="Acme", location="Remote", description="Good job",
         structured_data=None, score=None, score_reason=None):
    return {
        "id": id, "title": title, "company": company,
        "location": location, "description": description,
        "structured_data": json.dumps(structured_data) if structured_data else None,
        "score": score, "score_reason": score_reason,
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
        text = _format_job(_job(title="Engineer", company="Corp"))
        assert "Engineer" in text
        assert "Corp" in text

    def test_includes_description_excerpt(self):
        text = _format_job(_job(description="We use Python and Django"))
        assert "Python" in text

    def test_structured_data_tags_appear(self):
        sd = {"remote": True, "seniority": "senior", "company_type": "startup",
              "product_vs_outsourcing": "product", "stack": ["Python"],
              "hybrid": False, "salary_min": None, "salary_max": None, "salary_currency": None}
        text = _format_job(_job(structured_data=sd))
        assert "remote" in text.lower()
        assert "senior" in text.lower()
        assert "startup" in text.lower()

    def test_no_positional_label_in_output(self):
        # Regression: a "[Job #N]" label matching presentation order let Opus
        # anchor on position instead of content — only the job's own id
        # identifies it now.
        text = _format_job(_job(id="j1"))
        assert "Job #" not in text
        assert "[ID: j1]" in text

    def test_scorer_rating_included_when_present(self):
        # Regression: the listwise prompt never showed Opus the scorer's own
        # rating — the most expensive signal in the pipeline was invisible to
        # the model doing the final ranking.
        text = _format_job(_job(score=8.5, score_reason="Strong Python/Django match"))
        assert "8.5/10" in text
        assert "Strong Python/Django match" in text

    def test_scorer_rating_omitted_when_none(self):
        text = _format_job(_job(score=None))
        assert "Scorer's rating" not in text

    def test_scorer_rating_without_reason_does_not_crash(self):
        text = _format_job(_job(score=6.0, score_reason=None))
        assert "6.0/10" in text


@patch("ranker.listwise.random.shuffle")
@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_shuffles_presentation_order(mock_anthropic, mock_shuffle):
    # Regression: jobs used to be presented to Opus in the reranker's own
    # best-first order with sequential labels, which a listwise ranker tends
    # to mostly echo back — shuffling breaks that positional anchor.
    jobs = [_job("j1"), _job("j2"), _job("j3")]
    ranking = [{"job_id": j["id"], "reason": "x"} for j in jobs]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(ranking)

    listwise_rank(jobs, "", [])

    mock_shuffle.assert_called_once()


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

    by_id = {r["id"]: r for r in result}
    assert by_id["j1"]["rank_reason"] == "Best"
    # Regression: omitted jobs used to get rank_reason="", indistinguishable from
    # a real (if terse) Opus ranking anywhere downstream (calibration/precision
    # metrics, dashboard display).
    assert by_id["j2"]["rank_reason"] == OMITTED_RANK_REASON
    assert by_id["j3"]["rank_reason"] == OMITTED_RANK_REASON


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
    # Regression: fallback used to write rank_reason="", indistinguishable
    # anywhere in the data from a genuine (if terse) Opus ranking.
    assert result[0]["rank_reason"] == FALLBACK_RANK_REASON
    assert result[1]["rank_reason"] == FALLBACK_RANK_REASON


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_fallback_on_no_tool_block(mock_anthropic):
    jobs = [_job("j1")]
    mock_anthropic.return_value.messages.create.return_value = _make_empty_response()

    result = listwise_rank(jobs, "", [])
    assert result[0]["listwise_rank"] == 1
    assert result[0]["rank_reason"] == FALLBACK_RANK_REASON


@patch("ranker.listwise.anthropic.Anthropic")
def test_listwise_rank_fallback_on_unparseable_json(mock_anthropic):
    jobs = [_job("j1")]
    block = MagicMock(type="text", text="<ranking>\n[{not valid json, missing quotes}]\n</ranking>")
    response = MagicMock(
        content=[block],
        usage=MagicMock(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )
    mock_anthropic.return_value.messages.create.return_value = response

    result = listwise_rank(jobs, "", [])
    assert result[0]["listwise_rank"] == 1
    assert result[0]["rank_reason"] == FALLBACK_RANK_REASON


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


@patch("ranker.listwise.anthropic.Anthropic")
def test_questionnaire_included_in_system_prompt_when_given(mock_anthropic):
    jobs = [_job("j1")]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(
        [{"job_id": "j1", "reason": "Good match"}]
    )

    listwise_rank(jobs, "", [], questionnaire="CANDIDATE QUESTIONNAIRE:\n- Work mode: remote")

    system_prompt = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "CANDIDATE QUESTIONNAIRE" in system_prompt
    assert "Work mode: remote" in system_prompt


@patch("ranker.listwise.anthropic.Anthropic")
def test_no_questionnaire_section_when_omitted(mock_anthropic):
    jobs = [_job("j1")]
    mock_anthropic.return_value.messages.create.return_value = _make_ranking_response(
        [{"job_id": "j1", "reason": "Good match"}]
    )

    listwise_rank(jobs, "", [])

    system_prompt = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "CANDIDATE QUESTIONNAIRE" not in system_prompt
