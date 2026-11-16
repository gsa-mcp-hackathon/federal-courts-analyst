"""REST contracts: status codes, validation errors, ETag caching, and the
Phase 6 hardening on /api."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from courts_analyst.http_security import SECURITY_HEADERS

FIG = "/api/figures"
W2020 = {"measure": "weighted_civil_filings_per_judgeship", "fiscal_year": 2020}


def test_ok(api: Any) -> None:
    r = api.get(FIG, params=W2020)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["data"]["value"] == 322
    assert body["provenance"][0]["edition"] == "JFF-2025"


def test_ambiguous_measure_is_an_answer(api: Any) -> None:
    r = api.get(FIG, params={"measure": "filings_per_judgeship", "fiscal_year": 2020})
    assert r.status_code == 200
    assert r.json()["status"] == "needs_clarification"


def test_declined_is_200(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from courts_analyst.api.routes import figures
    from courts_analyst.core.guardrails.policy import policy_decline
    from courts_analyst.core.official import OfficialFigure
    from courts_analyst.core.results import decline

    monkeypatch.setattr(
        figures,
        "get_official_figure",
        lambda *a, **k: decline(policy_decline("small_cell"), OfficialFigure),
    )
    r = api.get(FIG, params=W2020)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "declined" and body["declined"]["reason"] == "small_cell"


@pytest.mark.parametrize(
    ("path", "params", "status", "code"),
    [
        (FIG, {"measure": "nope", "fiscal_year": 2020}, 422, "unknown_measure"),
        (FIG, {**W2020, "court": "ZZ-Q"}, 422, "unknown_court"),
        (FIG, {**W2020, "edition": "JB-1901"}, 422, "unknown_edition"),
        (
            FIG,
            {**W2020, "period_ending": "june_30"},
            422,
            "out_of_scope",
        ),
        (
            "/api/figures/weighted_civil_filings_per_judgeship/US/series",
            {"from": 1990, "to": 2025},
            422,
            "mixed_editions",
        ),
        (
            "/api/explain-change",
            {"measure": "civil_cases_filed", "from": 2020, "to": 2019},
            422,
            "invalid_cohort",
        ),
        ("/api/courts/ZZ/profile", {}, 404, "unknown_court"),
        ("/api/eval/runs/no-such-run", {}, 404, "not_found"),
        ("/api/eval/runs/..%2Fsecrets", {}, 404, None),
    ],
)
def test_error_statuses(
    api: Any, path: str, params: dict[str, Any], status: int, code: str | None
) -> None:
    r = api.get(path, params=params)
    assert r.status_code == status, r.text
    if code:
        body = r.json()
        assert body["error"] == code
        assert body.get("message")


def test_mixed_series_allowed_when_asked(api: Any) -> None:
    r = api.get(
        "/api/figures/weighted_civil_filings_per_judgeship/US/series",
        params={"from": 1990, "to": 2025, "allow_mixed": "true"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["consistent"] is False


def test_consistent_series(api: Any) -> None:
    r = api.get(
        "/api/figures/weighted_civil_filings_per_judgeship/US/series",
        params={"from": 2016, "to": 2025},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["consistent"] is True
    # One publication series (each year from its own JB edition), not a mix.
    assert {p["edition"].split("-")[0] for p in data["points"]} == {"JB"}


@pytest.mark.parametrize(
    "params",
    [
        {"measure": "civil_cases_filed"},  # missing fiscal_year
        {"measure": "civil_cases_filed", "fiscal_year": 1800},
        {"measure": "civil cases; drop", "fiscal_year": 2020},
        {"measure": "x" * 100, "fiscal_year": 2020},
    ],
)
def test_validation_errors(api: Any, params: dict[str, Any]) -> None:
    r = api.get(FIG, params=params)
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "invalid_request" and body["details"]


def test_etag_round_trip(api: Any) -> None:
    r1 = api.get(FIG, params=W2020)
    tag = r1.headers["etag"]
    assert r1.headers["cache-control"].endswith("max-age=3600")
    r2 = api.get(FIG, params=W2020, headers={"if-none-match": tag})
    assert r2.status_code == 304 and r2.content == b""
    # A different request has a different tag.
    r3 = api.get(FIG, params={**W2020, "fiscal_year": 2019})
    assert r3.headers["etag"] != tag


def test_etag_changes_with_the_data_build(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from courts_analyst.api import common

    tag = api.get(FIG, params=W2020).headers["etag"]
    monkeypatch.setattr(common, "build_hash", lambda: "rebuilt")
    r = api.get(FIG, params=W2020, headers={"if-none-match": tag})
    assert r.status_code == 200 and r.headers["etag"] != tag


def test_errors_are_not_cached(api: Any) -> None:
    r = api.get(FIG, params={"measure": "nope", "fiscal_year": 2020})
    assert "etag" not in r.headers


def test_courts_and_revisions(api: Any) -> None:
    courts = api.get("/api/courts").json()["courts"]
    codes = {c["code"] for c in courts}
    assert {"US", "FL-N", "NY-S", "CIR-11"} <= codes
    revs = api.get(
        "/api/revisions",
        params={"measure": "weighted_civil_filings_per_judgeship", "court": "US"},
    ).json()["revisions"]
    fy2020 = next(r for r in revs if r["fiscal_year"] == 2020)
    assert (fy2020["first_value"], fy2020["latest_value"]) == (554, 322)


def test_eval_runs(api: Any) -> None:
    runs = api.get("/api/eval/runs").json()["runs"]
    gold = next(r for r in runs if r["run_id"] == "phase3-gold-all")
    assert gold["accuracy"] == 1.0
    one = api.get("/api/eval/runs/phase4-engine").json()
    assert one["summary"]["run_id"] == "phase4-engine"
    assert one["items"] and all("correct" in i for i in one["items"])


def test_openapi(api: Any) -> None:
    spec = api.get("/api/openapi.json").json()
    for path in (
        "/figures",
        "/figures/{measure}/{court}/series",
        "/compare",
        "/revisions",
        "/courts",
        "/courts/{court}/profile",
        "/explain-change",
        "/eval/runs",
        "/ask",
        "/ask/{turn_id}/clarify",
    ):
        assert path in spec["paths"], path


def test_security_headers_on_api(api: Any) -> None:
    r = api.get(FIG, params=W2020)
    for k, v in SECURITY_HEADERS:
        assert r.headers[k.decode()] == v.decode()


def test_ask_validation(api: Any) -> None:
    assert api.post("/api/ask", json={"question": ""}).status_code == 422
    assert api.post("/api/ask", json={"question": "x" * 2001}).status_code == 422
    assert api.post("/api/ask", json={}).status_code == 422


def test_clarify_unknown_turn(api: Any) -> None:
    r = api.post(
        "/api/ask/nosuchturn/clarify", json={"clarify_id": "0" * 12, "choice": "x"}
    )
    assert r.status_code == 404
    bad = api.post("/api/ask/t/clarify", json={"clarify_id": "../x", "choice": "x"})
    assert bad.status_code == 422


def _app(server_data: None, **overrides: Any) -> Any:
    from courts_analyst.api.main import build_app
    from courts_analyst.config import Settings

    return build_app(Settings(_env_file=None, **overrides))  # type: ignore[call-arg]


def test_bearer_token_covers_api(server_data: None) -> None:
    app = _app(server_data, http_bearer_token=SecretStr("s3cret-token-value"))
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get(FIG, params=W2020).status_code == 401
        assert c.post("/api/ask", json={"question": "hi"}).status_code == 401
        ok = c.get(
            FIG,
            params=W2020,
            headers={"authorization": "Bearer s3cret-token-value"},
        )
        assert ok.status_code == 200
        assert ok.headers["cache-control"].startswith("private")
        assert c.get("/health").status_code == 200


def test_ask_rate_limit(api_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from courts_analyst.agent.loop import Agent
    from courts_analyst.agent.providers.scripted import ScriptedProvider, Step
    from courts_analyst.api.routes import ask
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "http_ask_rate_limit_per_minute", 2)
    monkeypatch.setattr(ask, "_limiter", None)
    api_app.state.api.state.agent_factory = lambda: Agent(
        ScriptedProvider([Step("ok")]), courtlistener="off"
    )
    with TestClient(api_app, base_url="http://localhost") as c:
        codes = [
            c.post("/api/ask", json={"question": "What data?"}).status_code
            for _ in range(3)
        ]
    assert codes == [200, 200, 429]
