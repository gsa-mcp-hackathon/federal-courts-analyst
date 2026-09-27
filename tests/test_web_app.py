"""Phase 8 backend: the web build served at /, and the endpoints the pages use."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from courts_analyst.api.web import IMMUTABLE, PAGE_CSP, REVALIDATE
from courts_analyst.pipeline.geo import crosswalk


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "geo").mkdir()
    (d / "index.html").write_text(
        "<!doctype html><title>FCA</title><div id=root></div>"
    )
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    (d / "geo" / "districts.topo.json").write_text("{}")
    (tmp_path / "secret.txt").write_text("outside the build")
    return d


@pytest.fixture
def web(server_data: None, no_courtlistener_token: None, dist: Path) -> Any:
    from courts_analyst.api.main import build_app
    from courts_analyst.config import Settings

    app = build_app(Settings(_env_file=None, web_dist_dir=dist))  # type: ignore[call-arg]
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def test_index_and_deep_links_get_the_spa(web: TestClient) -> None:
    for path in (
        "/",
        "/explore",
        "/editions/weighted-filings-per-judgeship/national/2020",
        "/courts/fl-n",
    ):
        r = web.get(path)
        assert r.status_code == 200, path
        assert "<div id=root>" in r.text
        assert r.headers["cache-control"] == REVALIDATE
        assert r.headers["content-security-policy"] == PAGE_CSP


def test_assets_are_immutable_and_other_files_revalidate(web: TestClient) -> None:
    js = web.get("/assets/index-abc123.js")
    assert js.status_code == 200 and js.headers["cache-control"] == IMMUTABLE
    geo = web.get("/geo/districts.topo.json")
    assert geo.status_code == 200 and geo.headers["cache-control"] == REVALIDATE


def test_missing_files_are_404_not_the_spa(web: TestClient) -> None:
    assert web.get("/assets/nope.js").status_code == 404
    assert web.get("/favicon.ico").status_code == 404


def test_no_path_traversal(web: TestClient) -> None:
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        r = web.get(path)
        assert "outside the build" not in r.text, path


def test_api_and_mcp_keep_their_own_routes_and_strict_csp(web: TestClient) -> None:
    api = web.get("/api/courts")
    assert api.status_code == 200
    assert (
        api.headers["content-security-policy"]
        == "default-src 'none'; frame-ancestors 'none'"
    )
    assert web.get("/health").json()["status"] == "healthy"
    # An unknown API path is the API's 404, never the SPA.
    assert "<div id=root>" not in web.get("/api/nope").text


def test_page_security_headers(web: TestClient) -> None:
    r = web.get("/")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_only_get_and_head(web: TestClient) -> None:
    assert web.post("/explore").status_code == 405


def test_no_build_no_spa(server_data: None, tmp_path: Path) -> None:
    from courts_analyst.api.main import build_app
    from courts_analyst.config import Settings

    app = build_app(Settings(_env_file=None, web_dist_dir=tmp_path / "none"))  # type: ignore[call-arg]
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/explore").status_code == 404
        assert c.get("/api/courts").status_code == 200


# ── endpoints the pages read ─────────────────────────────────────────────────


def test_methodology_and_glossary(api: TestClient) -> None:
    topics = api.get("/api/methodology").json()["topics"]
    assert {"weighted-filings", "editions"} <= {t["topic"] for t in topics}
    note = api.get("/api/methodology/editions").json()
    assert note["markdown"].startswith("# ")
    assert api.get("/api/methodology/%2e%2e%2fsecrets").status_code == 404
    terms = api.get("/api/glossary").json()["terms"]
    assert any(t["term"] == "weighted filings" for t in terms)


def test_edition_vintages(api: TestClient) -> None:
    r = api.get("/api/figures/weighted_civil_filings_per_judgeship/US/editions")
    assert r.status_code == 200
    body = r.json()
    eds = body["data"]["editions"]
    assert [e["edition"] for e in eds] == sorted(
        (e["edition"] for e in eds), key=[e["edition"] for e in eds].index
    )
    by_ed = {
        e["edition"]: {p["fiscal_year"]: p["value"] for p in e["points"]} for e in eds
    }
    assert by_ed["JB-2020"][2020] == 554
    assert by_ed["JFF-2025"][2020] == 322
    # One edition per line, so JB and JFF together carry the guardrail's label.
    assert any(w["code"] == "mixed_editions" for w in body["warnings"])
    assert len(body["provenance"]) == len(eds)
    assert api.get("/api/figures/nope/US/editions").status_code == 422


async def test_vintages_match_the_figure_chain(api: TestClient) -> None:
    """Every edition's value for FY2020 equals the figure's own edition history."""
    fig = api.get(
        "/api/figures",
        params={"measure": "weighted_civil_filings_per_judgeship", "fiscal_year": 2020},
    ).json()["data"]
    eds = api.get(
        "/api/figures/weighted_civil_filings_per_judgeship/US/editions"
    ).json()["data"]["editions"]
    from_vintages = {
        e["edition"]: p["value"]
        for e in eds
        for p in e["points"]
        if p["fiscal_year"] == 2020
    }
    assert from_vintages == {e["edition"]: e["value"] for e in fig["editions"]}


def test_case_mix_and_reconcile(api: TestClient) -> None:
    mix = api.get("/api/courts/FL-N/case-mix", params={"fiscal_year": 2020}).json()
    assert mix["status"] == "ok"
    assert mix["data"]["metric"] == "share_by_nos_group"
    rec = api.get("/api/courts/FL-N/reconcile", params={"fiscal_year": 2020}).json()
    assert rec["status"] == "ok"
    assert rec["data"]["badge"]["status"] in {
        "matched",
        "explained_variance",
        "unexplained",
    }
    assert (
        api.get("/api/courts/ZZ/case-mix", params={"fiscal_year": 2020}).status_code
        == 404
    )
    bad = api.get(
        "/api/courts/FL-N/reconcile", params={"fiscal_year": 2020, "measure": "judges"}
    )
    assert bad.status_code == 422


# ── the map's county → district crosswalk ────────────────────────────────────


def test_crosswalk_votes_within_the_state() -> None:
    rows = [
        # Alameda: mostly N.D. Cal., some elsewhere in California.
        ("06001", "CA-N", 900),
        ("06001", "CA-C", 100),
        # A Florida county whose residents also sue in Georgia: only Florida
        # districts count.
        ("12033", "GA-N", 5000),
        ("12033", "FL-N", 800),
        ("12033", "FL-M", 200),
        # Foreign residence code: ignored.
        ("88888", "NY-S", 10**6),
    ]
    cw = crosswalk(rows)
    assert cw["counties"]["06001"] == {"district": "CA-N", "cases": 1000, "share": 0.9}
    assert cw["counties"]["12033"]["district"] == "FL-N"
    assert cw["counties"]["12033"]["share"] == 0.8
    assert "88888" not in cw["counties"]
    assert cw["single_district_states"]["VT"] == "VT"
    assert "CA" not in cw["single_district_states"]


def test_committed_map_covers_every_district() -> None:
    import json

    root = Path(__file__).resolve().parents[1] / "web"
    topo = json.loads((root / "public" / "geo" / "districts.topo.json").read_text())
    ids = {g["id"] for g in topo["objects"]["districts"]["geometries"]}
    from courts_analyst.core.courts import COURTS, CourtLevel

    districts = {c for c, v in COURTS.items() if v.level is CourtLevel.DISTRICT}
    territories = {"PR", "VI", "GU", "MP"}
    # Every mainland, Alaska and Hawaii district is drawn; territories are tiles.
    assert ids == districts - territories
    report = json.loads((root / "src" / "geo" / "districts-report.json").read_text())
    assert report["unassigned"] == []
