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


def _debate_response(reviews: list[dict], stop_reason="tool_use"):
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"reviews": reviews}
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=0)
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
    def test_overrated_flag_moves_job_down(self, mock_anthropic):
        # Regression: overrated/underrated used to be attached to the job
        # (debate_flag/debate_note, shown in the UI) but never changed its
        # actual position — only dealbreaker_risk did anything.
        jobs = [_job("j1", rank=1), _job("j2", rank=2)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j1", "flag": "overrated", "note": "Slightly overrated"},
        ])
        result = debate_rank(jobs, "profile")
        assert [j["id"] for j in result] == ["j2", "j1"]
        assert result[-1]["debate_flag"] == "overrated"
        assert result[-1]["listwise_rank"] == 2

    @patch("ranker.debate.anthropic.Anthropic")
    def test_overrated_flag_moves_down_by_rank_nudge_positions(self, mock_anthropic):
        jobs = [_job(f"j{i}", rank=i) for i in range(1, 8)]  # j1..j7, plenty of room below
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j1", "flag": "overrated", "note": "x"},
        ])
        result = debate_rank(jobs, "profile")
        ids = [j["id"] for j in result]
        assert ids.index("j1") == 3  # moved from index 0 down exactly _RANK_NUDGE=3

    @patch("ranker.debate.anthropic.Anthropic")
    def test_underrated_flag_moves_up_by_rank_nudge_positions(self, mock_anthropic):
        jobs = [_job(f"j{i}", rank=i) for i in range(1, 8)]  # j1..j7
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j7", "flag": "underrated", "note": "x"},
        ])
        result = debate_rank(jobs, "profile")
        ids = [j["id"] for j in result]
        assert ids.index("j7") == 3  # moved from index 6 up exactly _RANK_NUDGE=3

    @patch("ranker.debate.anthropic.Anthropic")
    def test_underrated_flag_clamped_at_top_when_not_enough_room(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2), _job("j3", rank=3)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j2", "flag": "underrated", "note": "x"},
        ])
        result = debate_rank(jobs, "profile")
        assert result[0]["id"] == "j2"

    @patch("ranker.debate.anthropic.Anthropic")
    def test_overrated_flag_clamped_at_bottom_when_not_enough_room(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2), _job("j3", rank=3)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j2", "flag": "overrated", "note": "x"},
        ])
        result = debate_rank(jobs, "profile")
        assert result[-1]["id"] == "j2"

    @patch("ranker.debate.anthropic.Anthropic")
    def test_dealbreaker_demotion_and_nudge_combine_correctly(self, mock_anthropic):
        jobs = [_job("j1", rank=1), _job("j2", rank=2), _job("j3", rank=3), _job("j4", rank=4)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([
            {"job_id": "j1", "flag": "dealbreaker_risk", "note": "x"},
            {"job_id": "j4", "flag": "underrated", "note": "y"},
        ])
        result = debate_rank(jobs, "profile")
        ids = [j["id"] for j in result]
        assert ids[-1] == "j1"  # dealbreaker still goes to the absolute bottom
        assert ids.index("j4") < ids.index("j2")  # underrated j4 nudged ahead of j2/j3

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
        response = MagicMock(
            content=[text_block], stop_reason="end_turn",
            usage=MagicMock(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        )
        mock_anthropic.return_value.messages.create.return_value = response
        jobs = [_job("j1", rank=1)]
        result = debate_rank(jobs, "profile")
        assert result == jobs

    @patch("ranker.debate.anthropic.Anthropic")
    def test_truncated_response_returns_original_ranking_unchanged(self, mock_anthropic):
        # Regression: a truncated reviews array can still parse as valid-but-
        # partial JSON — without an explicit stop_reason check, a partial
        # critique could apply flags based on an incomplete review.
        jobs = [_job("j1", rank=1), _job("j2", rank=2)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response(
            [{"job_id": "j1", "flag": "dealbreaker_risk", "note": "x"}], stop_reason="max_tokens"
        )
        result = debate_rank(jobs, "profile")
        assert result == jobs
        assert "debate_flag" not in result[0]

    @patch("ranker.debate.anthropic.Anthropic")
    def test_questionnaire_included_in_system_prompt_when_given(self, mock_anthropic):
        jobs = [_job("j1", rank=1)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([])
        debate_rank(jobs, "profile", questionnaire="CANDIDATE QUESTIONNAIRE:\n- Work mode: remote")
        system_prompt = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
        assert "CANDIDATE QUESTIONNAIRE" in system_prompt
        assert "Work mode: remote" in system_prompt

    @patch("ranker.debate.anthropic.Anthropic")
    def test_no_questionnaire_section_when_omitted(self, mock_anthropic):
        jobs = [_job("j1", rank=1)]
        mock_anthropic.return_value.messages.create.return_value = _debate_response([])
        debate_rank(jobs, "profile")
        system_prompt = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
        assert "CANDIDATE QUESTIONNAIRE" not in system_prompt
