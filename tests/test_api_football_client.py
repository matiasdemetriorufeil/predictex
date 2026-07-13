import httpx
import pytest
import respx

from src.exceptions import ExternalAPIError, RateLimitExceededError
from src.ingestion.api_football_client import (
    BASE_URL,
    DAILY_QUOTA_REMAINING_HEADER,
    APIFootballClient,
)
from src.ingestion.quota_guard import DailyQuotaGuard

# Realistic payload shapes confirmed with real calls against v3.football.api-sports.io for
# Paso 2.3 (league=71 is Campeonato Brasileiro Série A, season=2023 - allowed on the free tier).
SAMPLE_TEAMS_RESPONSE = {
    "results": 1,
    "response": [
        {
            "team": {
                "id": 118,
                "name": "Bahia",
                "code": "BAH",
                "country": "Brazil",
                "founded": 1931,
                "national": False,
                "logo": "https://media.api-sports.io/football/teams/118.png",
            },
            "venue": {
                "id": 216,
                "name": "Arena Fonte Nova",
                "city": "Salvador, Bahia",
                "capacity": 56500,
            },
        }
    ],
}

SAMPLE_STATISTICS_RESPONSE = {
    "results": 1,
    "response": {
        "league": {"id": 71, "name": "Serie A", "country": "Brazil", "season": 2023},
        "team": {"id": 118, "name": "Bahia"},
        "form": "LLWWLLDLDD",
        "fixtures": {"played": {"home": 19, "away": 19, "total": 38}},
        "goals": {"for": {"total": {"total": 50}}, "against": {"total": {"total": 53}}},
        "cards": {"yellow": {}, "red": {}},
    },
}

QUOTA_HEADERS = {
    "x-ratelimit-limit": "10",
    "x-ratelimit-remaining": "9",
    DAILY_QUOTA_REMAINING_HEADER: "97",
    "x-ratelimit-requests-limit": "100",
}


@pytest.mark.external_api
@respx.mock
def test_get_teams_returns_raw_team_list():
    route = respx.get(f"{BASE_URL}/teams", params={"league": "71", "season": "2023"}).mock(
        return_value=httpx.Response(200, json=SAMPLE_TEAMS_RESPONSE, headers=QUOTA_HEADERS)
    )
    client = APIFootballClient(api_key="fake-key")

    teams = client.get_teams(71, 2023)

    assert route.called
    assert teams == SAMPLE_TEAMS_RESPONSE["response"]
    assert route.calls.last.request.headers["x-apisports-key"] == "fake-key"


@pytest.mark.external_api
@respx.mock
def test_get_team_statistics_returns_raw_dict_and_updates_quota():
    respx.get(f"{BASE_URL}/teams/statistics").mock(
        return_value=httpx.Response(200, json=SAMPLE_STATISTICS_RESPONSE, headers=QUOTA_HEADERS)
    )
    client = APIFootballClient(api_key="fake-key")

    stats = client.get_team_statistics(71, 2023, 118)

    assert stats == SAMPLE_STATISTICS_RESPONSE["response"]
    assert client.quota_guard._remaining == 97


@pytest.mark.external_api
@respx.mock
def test_get_teams_raises_rate_limit_exceeded_on_429_without_retry():
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(429, text="Too Many Requests")
    )
    client = APIFootballClient(api_key="fake-key")

    with pytest.raises(RateLimitExceededError):
        client.get_teams(71, 2023)

    assert route.call_count == 1


@pytest.mark.external_api
@respx.mock
def test_get_teams_raises_external_api_error_on_application_level_error():
    payload = {"results": 0, "errors": {"plan": "Free plans do not have access to this season"}}
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(200, json=payload, headers=QUOTA_HEADERS)
    )
    client = APIFootballClient(api_key="fake-key")

    with pytest.raises(ExternalAPIError) as exc_info:
        client.get_teams(71, 2025)
    assert "errors" in exc_info.value.context


@pytest.mark.external_api
@respx.mock
def test_get_teams_retries_on_500_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.ingestion.api_football_client.time.sleep", lambda _seconds: None)
    route = respx.get(f"{BASE_URL}/teams").mock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=SAMPLE_TEAMS_RESPONSE, headers=QUOTA_HEADERS),
        ]
    )
    client = APIFootballClient(api_key="fake-key")

    teams = client.get_teams(71, 2023)

    assert route.call_count == 2
    assert teams == SAMPLE_TEAMS_RESPONSE["response"]


def test_daily_quota_guard_raises_when_remaining_below_buffer():
    guard = DailyQuotaGuard(safety_buffer=10)
    guard.update_from_remaining(9)

    with pytest.raises(RateLimitExceededError):
        guard.check_before_request()


def test_daily_quota_guard_allows_when_remaining_above_buffer():
    guard = DailyQuotaGuard(safety_buffer=10)
    guard.update_from_remaining(50)

    guard.check_before_request()  # should not raise
