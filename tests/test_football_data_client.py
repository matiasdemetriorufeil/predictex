import httpx
import pytest
import respx

from src.exceptions import ExternalAPIError, RateLimitExceededError
from src.ingestion.football_data_client import BASE_URL, FootballDataClient

# Realistic payload shape confirmed against docs.football-data.org/general/v4/ for Paso 2.2.
SAMPLE_RESPONSE = {
    "filters": {"season": "2025"},
    "resultSet": {"count": 1, "played": 1},
    "competition": {"id": 2013, "name": "Campeonato Brasileiro Série A", "code": "BSA"},
    "matches": [
        {
            "id": 500001,
            "utcDate": "2025-04-13T20:00:00Z",
            "status": "FINISHED",
            "matchday": 1,
            "venue": "Maracanã",
            "homeTeam": {"id": 1783, "name": "Flamengo", "shortName": "Flamengo"},
            "awayTeam": {"id": 1837, "name": "Fluminense", "shortName": "Fluminense"},
            "score": {"winner": "HOME_TEAM", "fullTime": {"home": 2, "away": 1}},
        }
    ],
}


@pytest.mark.external_api
@respx.mock
def test_get_matches_returns_raw_match_list():
    route = respx.get(f"{BASE_URL}/competitions/BSA/matches", params={"season": "2025"}).mock(
        return_value=httpx.Response(200, json=SAMPLE_RESPONSE)
    )
    client = FootballDataClient(api_key="fake-key")

    matches = client.get_matches("BSA", 2025)

    assert route.called
    assert matches == SAMPLE_RESPONSE["matches"]
    assert route.calls.last.request.headers["X-Auth-Token"] == "fake-key"


@pytest.mark.external_api
@respx.mock
def test_get_matches_raises_rate_limit_exceeded_on_429_without_retry():
    route = respx.get(f"{BASE_URL}/competitions/BSA/matches").mock(
        return_value=httpx.Response(429, text="Too Many Requests")
    )
    client = FootballDataClient(api_key="fake-key")

    with pytest.raises(RateLimitExceededError):
        client.get_matches("BSA", 2025)

    assert route.call_count == 1


@pytest.mark.external_api
@respx.mock
def test_get_matches_raises_external_api_error_on_404():
    respx.get(f"{BASE_URL}/competitions/BSA/matches").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    client = FootballDataClient(api_key="fake-key")

    with pytest.raises(ExternalAPIError) as exc_info:
        client.get_matches("BSA", 2025)
    assert exc_info.value.context["status_code"] == 404


@pytest.mark.external_api
@respx.mock
def test_get_matches_retries_on_500_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.ingestion.football_data_client.time.sleep", lambda _seconds: None)
    route = respx.get(f"{BASE_URL}/competitions/BSA/matches").mock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=SAMPLE_RESPONSE),
        ]
    )
    client = FootballDataClient(api_key="fake-key")

    matches = client.get_matches("BSA", 2025)

    assert route.call_count == 2
    assert matches == SAMPLE_RESPONSE["matches"]
