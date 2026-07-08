from unittest.mock import MagicMock, patch

from extractor.runner import extract_job, run_extraction


def _make_tool_response(data: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.input = data
    response = MagicMock()
    response.content = [block]
    return response


def _make_empty_response():
    response = MagicMock()
    response.content = []
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
def test_run_extraction_returns_zero_when_extract_returns_empty(mock_extract, mock_repo):
    mock_extract.return_value = {}
    jobs = [{"id": "j1", "title": "Dev", "company": "Co", "description": "desc", "structured_data": None}]
    count = run_extraction(jobs)
    assert count == 0
