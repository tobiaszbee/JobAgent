from unittest.mock import MagicMock, patch

from extractor.runner import _EXTRACT_TOOL, extract_job, run_extraction


def _make_tool_response(data: dict, stop_reason="tool_use"):
    block = MagicMock()
    block.type = "tool_use"
    block.input = data
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


def _make_empty_response():
    response = MagicMock()
    response.content = []
    response.stop_reason = "end_turn"
    return response


@patch("extractor.runner._get_client")
def test_extract_job_returns_parsed_dict(mock_get_client):
    payload = {
        "remote": True, "hybrid": False, "seniority": "senior",
        "salary_min": 15000, "salary_max": 20000, "salary_currency": "PLN",
        "stack": ["Python", "Django"], "company_type": "startup",
        "product_vs_outsourcing": "product", "working_language": "english",
    }
    mock_get_client.return_value.messages.create.return_value = _make_tool_response(payload)

    result = extract_job("Senior Python Developer, remote, 15-20k PLN")
    assert result["remote"] is True
    assert result["seniority"] == "senior"
    assert "Python" in result["stack"]


class TestExtractionSchema:
    # Regression coverage for the audit's biggest single schema gap: `remote`
    # was a bare boolean with no geo information, so nothing in the pipeline
    # could ever tell "remote — Poland only" from "remote — US only" apart.
    _NEW_FIELDS = {
        "remote_regions", "timezone_requirement", "contract_types",
        "stack_required", "stack_preferred",
    }

    def test_new_fields_present_in_schema(self):
        props = _EXTRACT_TOOL["input_schema"]["properties"]
        assert self._NEW_FIELDS <= props.keys()

    def test_new_fields_are_required_so_the_model_always_considers_them(self):
        # "required" here means "must appear in the tool call" — nullable/empty-
        # array fields still satisfy it, this just stops the model from silently
        # omitting the field rather than explicitly saying "unstated".
        required = set(_EXTRACT_TOOL["input_schema"]["required"])
        assert self._NEW_FIELDS <= required

    def test_remote_regions_and_stack_tiers_are_plain_string_arrays(self):
        props = _EXTRACT_TOOL["input_schema"]["properties"]
        for field in ("remote_regions", "stack_required", "stack_preferred"):
            assert props[field]["type"] == "array"

    def test_timezone_requirement_is_nullable_string(self):
        assert _EXTRACT_TOOL["input_schema"]["properties"]["timezone_requirement"]["type"] == ["string", "null"]

    @patch("extractor.runner._get_client")
    def test_new_fields_round_trip_through_extract_job(self, mock_get_client):
        payload = {
            "remote": True, "hybrid": False, "seniority": "senior",
            "salary_min": None, "salary_max": None, "salary_period": None, "salary_currency": None,
            "stack": ["Kubernetes", "Docker"], "stack_required": ["Kubernetes"], "stack_preferred": ["Docker"],
            "company_type": "startup", "product_vs_outsourcing": "product", "working_language": "english",
            "remote_regions": ["Poland", "Ukraine"], "timezone_requirement": "CET ±2", "contract_types": ["b2b"],
        }
        mock_get_client.return_value.messages.create.return_value = _make_tool_response(payload)

        result = extract_job("Senior Kubernetes role, remote from Poland/Ukraine, CET +-2h, B2B")
        assert result["remote_regions"] == ["Poland", "Ukraine"]
        assert result["timezone_requirement"] == "CET ±2"
        assert result["contract_types"] == ["b2b"]
        assert result["stack_required"] == ["Kubernetes"]
        assert result["stack_preferred"] == ["Docker"]
        assert result["company_type"] == "startup"


@patch("extractor.runner._get_client")
def test_extract_job_returns_empty_on_api_error(mock_get_client):
    mock_get_client.return_value.messages.create.side_effect = Exception("API error")
    result = extract_job("Some job description")
    assert result == {}


@patch("extractor.runner._get_client")
def test_extract_job_returns_empty_when_no_tool_block(mock_get_client):
    mock_get_client.return_value.messages.create.return_value = _make_empty_response()
    result = extract_job("Description without tool response")
    assert result == {}


@patch("extractor.runner._get_client")
def test_extract_job_returns_empty_on_truncated_response(mock_get_client):
    # Regression: a truncated tool_use block can still parse as valid-but-
    # partial JSON — without an explicit stop_reason check, run_extraction()'s
    # `if data:` guard would treat a truthy-but-incomplete dict as a final,
    # complete extraction and never retry the missing fields.
    payload = {"remote": True}  # as if cut off mid-object
    mock_get_client.return_value.messages.create.return_value = _make_tool_response(payload, stop_reason="max_tokens")
    result = extract_job("Some job description")
    assert result == {}


@patch("extractor.runner._get_client")
def test_extract_job_strips_linkedin_junk_before_extraction(mock_get_client):
    # Regression guard: extract_job used to send description[:3000] raw, so LinkedIn's
    # page-chrome junk could land inside the extraction window for short postings.
    mock_get_client.return_value.messages.create.return_value = _make_tool_response({})
    description = "Senior Python Developer, remote.\nSet alert for similar jobs\nUnrelated footer junk."

    extract_job(description, source="linkedin")

    sent_content = mock_get_client.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Senior Python Developer" in sent_content
    assert "Unrelated footer junk" not in sent_content


@patch("extractor.runner._get_client")
def test_extract_job_non_linkedin_source_unaffected(mock_get_client):
    mock_get_client.return_value.messages.create.return_value = _make_tool_response({})
    extract_job("Clean posting text", source="remotive")

    sent_content = mock_get_client.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Clean posting text" in sent_content


@patch("extractor.runner.job_repository")
@patch("extractor.runner.extract_job")
def test_run_extraction_skips_jobs_without_description(mock_extract, mock_repo):
    jobs = [{"id": "j1", "title": "Dev", "company": "Co", "description": None, "structured_data": None}]
    count = run_extraction(jobs)
    assert count == 0
    mock_extract.assert_not_called()


@patch("extractor.runner.job_repository")
@patch("extractor.runner.extract_job")
def test_run_extraction_skips_already_extracted(mock_extract, mock_repo):
    jobs = [{
        "id": "j1", "title": "Dev", "company": "Co",
        "description": "desc", "structured_data": '{"remote": true}',
    }]
    count = run_extraction(jobs)
    assert count == 0
    mock_extract.assert_not_called()


@patch("extractor.runner.job_repository")
@patch("extractor.runner.extract_job")
def test_run_extraction_calls_update_on_success(mock_extract, mock_repo):
    mock_extract.return_value = {"remote": True, "stack": ["Python"]}
    jobs = [{"id": "j1", "title": "Dev", "company": "Co", "description": "desc", "structured_data": None}]
    count = run_extraction(jobs)
    assert count == 1
    mock_repo.update_structured_data.assert_called_once()


@patch("extractor.runner.job_repository")
@patch("extractor.runner.extract_job")
def test_run_extraction_passes_job_source_through(mock_extract, mock_repo):
    mock_extract.return_value = {}
    jobs = [{"id": "j1", "title": "Dev", "company": "Co", "source": "linkedin", "description": "desc", "structured_data": None}]
    run_extraction(jobs)
    mock_extract.assert_called_once_with("desc", "linkedin")


@patch("extractor.runner.job_repository")
@patch("extractor.runner.extract_job")
def test_run_extraction_returns_zero_when_extract_returns_empty(mock_extract, mock_repo):
    mock_extract.return_value = {}
    jobs = [{"id": "j1", "title": "Dev", "company": "Co", "description": "desc", "structured_data": None}]
    count = run_extraction(jobs)
    assert count == 0
