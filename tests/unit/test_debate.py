from unittest.mock import MagicMock, patch

from ranker.debate import debate_rank, _format_job_for_review, _parse_reviews


def _job(job_id="j1", title="Dev", rank=1, rank_reason="Good fit", breakdown=None, **overrides):
    job = {
        "id": job_id, "title": title, "company": "Acme", "description": "PHP role",
        "listwise_rank": rank, "rank_reason": rank_reason,
        "score_breakdown": breakdown,
    }
    job.update(overrides)
    return job


def _debate_response(reviews: list[dict]):
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"reviews": reviews}
    response = MagicMock()
    response.content = [block]
    response.usage = MagicMock(input_tokens=100, output_tokens=50)
    return response


class TestFormatJobForReview:
    def test_includes_rank_reason(self):
        text = _format_job_for_review(_job(rank_reason="Great Symfony match"), 0)
        assert "Great Symfony match" in text

    def test_includes_pros_cons_from_breakdown(self):
        import json
        breakdown = json.dumps({"pros": ["Strong stack"], "cons": ["No salary"]})
        text = _format_job_for_review(_job(breakdown=breakdown), 0)
        assert "Strong stack" in text
        assert "No salary" in text

    def test_missing_breakdown_does_not_crash(self):
        text = _format_job_for_review(_job(breakdown=None), 0)
        assert "Dev" in text


class TestParseReviews:
    def test_valid_flag_kept(self):
        reviews = _parse_reviews({"reviews": [{"job_id": "j1", "flag": "dealbreaker_risk", "note": "x"}]})
        assert reviews["j1"]["flag"] == "dealbreaker_risk"

    def test_invalid_flag_dropped(self):
        reviews = _parse_reviews({"reviews": [{"job_id": "j1", "flag": "not_a_real_flag", "note": "x"}]})
        assert reviews == {}

    def test_missing_job_id_dropped(self):
        reviews = _parse_reviews({"reviews": [{"flag": "overrated", "note": "x"}]})
        assert reviews == {}


class TestDebateRank:
    def test_empty_input_returns_empty(self):
        assert debate_rank([], "profile") == []

    @patch("ranker.debate.anthropic.Anthropic")
    def test_no_flags_preserves_order(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([])
        result = debate_rank(jobs, "profile")
        assert [j["id"] for j in result] == ["j1", "j2"]

    @patch("ranker.debate.anthropic.Anthropic")
    def test_dealbreaker_risk_demotes_job_to_bottom(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2), _job("j3", rank=3)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j1", "flag": "dealbreaker_risk", "note": "Seniority mismatch"},
        ])
        result = debate_rank(jobs, "profile")
        assert [j["id"] for j in result] == ["j2", "j3", "j1"]
        assert result[-1]["listwise_rank"] == 3
        assert result[-1]["debate_flag"] == "dealbreaker_risk"
        assert result[-1]["debate_note"] == "Seniority mismatch"

    @patch("ranker.debate.anthropic.Anthropic")
    def test_overrated_flag_does_not_reorder(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j1", "flag": "overrated", "note": "Slightly overrated"},
        ])
        result = debate_rank(jobs, "profile")
        assert [j["id"] for j in result] == ["j1", "j2"]
        assert result[0]["debate_flag"] == "overrated"

    @patch("ranker.debate.anthropic.Anthropic")
    def test_ranks_renumbered_sequentially_after_demotion(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2), _job("j3", rank=3)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j2", "flag": "dealbreaker_risk", "note": "x"},
        ])
        result = debate_rank(jobs, "profile")
        assert [j["listwise_rank"] for j in result] == [1, 2, 3]

    @patch("ranker.debate.anthropic.Anthropic")
    def test_api_error_returns_original_ranking_unchanged(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2)]
        mock_anthropic.return_value.messages.create.side_effect = Exception("boom")
        result = debate_rank(jobs, "profile")
        assert result == jobs

    @patch("ranker.debate.anthropic.Anthropic")
    def test_no_tool_use_block_returns_original_ranking(self, mock_anthropic):
        text_block = MagicMock(type="text")
        response = MagicMock(content=[text_block], usage=MagicMock(input_tokens=1, output_tokens=1))
        mock_anthropic.return_value.messages.create.return_value = response
        jobs = [_job("j1", rank=1)]
        result = debate_rank(jobs, "profile")
        assert result == jobs
