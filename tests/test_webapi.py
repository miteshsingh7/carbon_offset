"""Unit and integration tests for CarbonVerify Web API and frontend server."""

from __future__ import annotations

import csv
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Generator
import urllib.request
import urllib.error

import pytest

from carbonverify.webapi import (
    build_project_payload,
    compute_crossing_t,
    create_server,
    get_first_high_year_areas,
)


def _get_free_port() -> int:
    """Find a random available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server() -> Generator[str, None, None]:
    """Start live background ThreadingHTTPServer for test duration."""
    port = _get_free_port()
    server = create_server(
        output_dir="output",
        data_dir="data/projects",
        web_dir="web",
        host="127.0.0.1",
        port=port,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)  # brief startup wait

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)


class TestWebAPIUnit:
    """Unit tests for payload generation and calculation helpers."""

    def test_compute_crossing_t(self) -> None:
        """Verify linear interpolation of crossing threshold T."""
        grid = {
            "0.60": {"obs_ha": 1505.62},
            "0.65": {"obs_ha": 1350.93},
            "0.70": {"obs_ha": 1179.06},
            "0.75": {"obs_ha": 1015.20},
        }
        claim = 1300.0
        crossing = compute_crossing_t(grid, claim)
        assert crossing == 0.665

        # Out of bounds
        assert compute_crossing_t(grid, 2000.0) is None
        assert compute_crossing_t(grid, 500.0) is None
        assert compute_crossing_t({}, 1300.0) is None

    def test_first_high_year_areas_2469(self) -> None:
        """Verify reproduction of exact first-high-NDVI cohort areas for 2469."""
        fhy = get_first_high_year_areas("2469", data_dir="data/projects")
        assert fhy is not None
        assert fhy["2019"] == 885.01
        assert fhy["2020"] == 653.36
        assert fhy["2021"] == 309.47
        assert fhy["2022"] == 125.94
        assert fhy["never"] == 338.21

    def test_build_project_payload_2469(self) -> None:
        """Verify full payload structure and values for real project 2469."""
        p = build_project_payload("2469", output_dir="output", data_dir="data/projects")
        assert p is not None

        # Required top-level keys
        required_keys = [
            "status",
            "confidence",
            "band",
            "claim",
            "span_pct",
            "detection_limit_pct",
            "scenes",
            "crossing_t",
            "break_even",
            "first_high_year_areas",
            "demo",
            "confidence_reasons",
            "area_test",
            "claims",
            "planting_schedule",
            "file_hashes",
            "recorded_files_count",
        ]
        for k in required_keys:
            assert k in p, f"Missing required payload key: {k}"

        assert p["status"] == "CONSISTENT"
        assert p["confidence"] == "LOW"
        assert p["demo"] is False
        assert p["claim"] == 1300.0
        assert p["band"] == [1015.2, 1505.62]
        assert p["span_pct"] == 37.7
        assert p["detection_limit_pct"] in (21.9, 1.0)
        assert p["crossing_t"] == 0.665

        # Scenes funnel
        assert p["scenes"] == {
            "fetched": 189,
            "excluded_ingest": 4,
            "in_timeseries": 185,
            "excluded_qc": 23,
            "passed": 162,
        }

        # Break even
        be = p["break_even"]
        assert be is not None
        assert set(be.keys()) == {
            "target_ha",
            "natural_forest_ha",
            "f_star_06_ha",
            "f_star_low_end_ha",
            "margin_06_ha",
            "margin_low_end_ha",
            "by_threshold",
        }
        assert be["target_ha"] == 1300.0
        assert be["natural_forest_ha"] == 541.0
        assert be["f_star_06_ha"] == 746.62
        assert be["f_star_low_end_ha"] == 256.2
        assert be["margin_06_ha"] == 205.62
        assert be["margin_low_end_ha"] == -284.8
        assert len(be["by_threshold"]) == 4
        assert be["by_threshold"][0] == {"t": 0.6, "a_2022_ha": 2046.62, "f_star_ha": 746.62, "margin_ha": 205.62}
        assert be["by_threshold"][1] == {"t": 0.65, "a_2022_ha": 1891.93, "f_star_ha": 591.93, "margin_ha": 50.93}
        assert be["by_threshold"][2] == {"t": 0.7, "a_2022_ha": 1720.06, "f_star_ha": 420.06, "margin_ha": -120.94}
        assert be["by_threshold"][3] == {"t": 0.75, "a_2022_ha": 1556.2, "f_star_ha": 256.2, "margin_ha": -284.8}
        assert "available_gap_ha" not in be
        assert "required_allowance_ha" not in be
        assert "covers" not in be

        # First high year
        fhy = p["first_high_year_areas"]
        assert fhy == {
            "2019": 885.01,
            "2020": 653.36,
            "2021": 309.47,
            "2022": 125.94,
            "never": 338.21,
        }

        assert p["recorded_files_count"] == 12
        assert p["limitations"]["pdf_sha256_document"] == "monitoring_report.pdf"

    def test_build_project_payload_demo(self) -> None:
        """Verify demo payload handling."""
        p = build_project_payload("demo", output_dir="output", data_dir="data/projects")
        assert p is not None
        assert p["demo"] is True
        assert p["status"] == "CONSISTENT"
        assert p["band"] is None
        assert p["scenes"] is None
        assert p["break_even"] is None
        assert p["limitations"]["pdf_sha256_document"] is None

    def test_break_even_derived_temporary_fixture(self, tmp_path: Path) -> None:
        """(a) Verify break_even is dynamically derived from custom estimate.json data."""
        proj_id = "test_custom_proj"
        out_dir = tmp_path / "output"
        data_dir = tmp_path / "data"
        (out_dir / proj_id).mkdir(parents=True)
        (data_dir / proj_id).mkdir(parents=True)

        report_content = {
            "project_id": proj_id,
            "demo": False,
            "status": "CONSISTENT",
            "confidence": "HIGH",
            "estimate": {
                "forest_allowance_check": {
                    "claimed_planted_ha": 1000.0,
                    "claimed_forest_allowance_ha": 200.0,
                },
                "grid_estimates": {
                    "0.60": {"a_2022_ha": 1600.0, "obs_ha": 1400.0},
                    "0.65": {"a_2022_ha": 1500.0, "obs_ha": 1300.0},
                    "0.70": {"a_2022_ha": 1400.0, "obs_ha": 1200.0},
                    "0.75": {"a_2022_ha": 1300.0, "obs_ha": 1100.0},
                },
            },
            "claims": {
                "claimed_area_ha": 1000.0,
                "natural_forest_ha": 200.0,
            },
        }
        with open(out_dir / proj_id / "report.json", "w", encoding="utf-8") as f:
            json.dump(report_content, f)

        p = build_project_payload(proj_id, output_dir=out_dir, data_dir=data_dir)
        assert p is not None
        be = p["break_even"]
        assert be is not None
        assert be["target_ha"] == 1000.0
        assert be["natural_forest_ha"] == 200.0
        assert be["f_star_06_ha"] == 600.0
        assert be["margin_06_ha"] == 400.0
        assert be["f_star_low_end_ha"] == 300.0
        assert be["margin_low_end_ha"] == 100.0
        assert be["by_threshold"] == [
            {"t": 0.6, "a_2022_ha": 1600.0, "f_star_ha": 600.0, "margin_ha": 400.0},
            {"t": 0.65, "a_2022_ha": 1500.0, "f_star_ha": 500.0, "margin_ha": 300.0},
            {"t": 0.7, "a_2022_ha": 1400.0, "f_star_ha": 400.0, "margin_ha": 200.0},
            {"t": 0.75, "a_2022_ha": 1300.0, "f_star_ha": 300.0, "margin_ha": 100.0},
        ]

    def test_break_even_none_without_forest_allowance_check(self, tmp_path: Path) -> None:
        """(b) Verify a project without forest_allowance_check returns break_even = None."""
        proj_id = "test_no_fac"
        out_dir = tmp_path / "output"
        data_dir = tmp_path / "data"
        (out_dir / proj_id).mkdir(parents=True)
        (data_dir / proj_id).mkdir(parents=True)

        report_content = {
            "project_id": proj_id,
            "demo": False,
            "status": "CONSISTENT",
            "estimate": {
                "grid_estimates": {
                    "0.60": {"a_2022_ha": 1600.0, "obs_ha": 1400.0},
                },
            },
            "claims": {
                "claimed_area_ha": 1000.0,
            },
        }
        with open(out_dir / proj_id / "report.json", "w", encoding="utf-8") as f:
            json.dump(report_content, f)

        p = build_project_payload(proj_id, output_dir=out_dir, data_dir=data_dir)
        assert p is not None
        assert p["break_even"] is None
        assert p["limitations"]["pdf_sha256_document"] is None

        # Also demo project has no forest_allowance_check
        p_demo = build_project_payload("demo", output_dir="output", data_dir="data/projects")
        assert p_demo is not None
        assert p_demo["break_even"] is None

    def test_webapi_code_hygiene(self) -> None:
        """(c) Ensure no hardcoded project_id branches or numeric get fallbacks in webapi.py."""
        code = Path("src/carbonverify/webapi.py").read_text(encoding="utf-8")
        assert "project_id ==" not in code, "Found 'project_id ==' branch in webapi.py"
        m = re.findall(r"get\([^)]*,\s*-?[0-9]", code)
        assert not m, f"Found numeric fallback in .get() calls: {m}"


class TestLiveEndpoints:
    """Integration tests running against the live ThreadingHTTPServer."""

    def test_api_projects_list(self, live_server: str) -> None:
        """Verify /api/projects lists existing projects."""
        url = f"{live_server}/api/projects"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert isinstance(data, list)
            assert "2469" in data
            assert "demo" in data

    def test_api_project_2469(self, live_server: str) -> None:
        """Verify GET /api/project/2469 returns valid payload."""
        url = f"{live_server}/api/project/2469"
        with urllib.request.urlopen(url) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["project_id"] == "2469"
            assert data["claim"] == 1300.0
            assert data["crossing_t"] == 0.665

    def test_api_project_not_found(self, live_server: str) -> None:
        """Verify unknown project returns 404 JSON."""
        url = f"{live_server}/api/project/unknown_project_999"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code == 404
        body = json.loads(exc_info.value.read().decode("utf-8"))
        assert "error" in body

    def test_path_traversal_rejected(self, live_server: str) -> None:
        """Verify path traversal attempts are rejected."""
        # Using raw socket or url with traversal
        url = f"{live_server}/api/project/..%2F..%2Fetc%2Fpasswd"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url)
        assert exc_info.value.code in (400, 403, 404)

    def test_geo_endpoints(self, live_server: str) -> None:
        """Verify GeoJSON endpoints serve valid boundary and ring."""
        url_b = f"{live_server}/api/project/2469/geo/boundary"
        with urllib.request.urlopen(url_b) as resp:
            assert resp.status == 200
            geo = json.loads(resp.read().decode("utf-8"))
            assert "type" in geo

        url_r = f"{live_server}/api/project/2469/geo/ring"
        with urllib.request.urlopen(url_r) as resp:
            assert resp.status == 200
            geo = json.loads(resp.read().decode("utf-8"))
            assert "type" in geo

        # Demo has no ring
        url_dr = f"{live_server}/api/project/demo/geo/ring"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url_dr)
        assert exc_info.value.code == 404

    def test_report_downloads(self, live_server: str) -> None:
        """Verify direct download endpoints for report.html and report.json."""
        url_html = f"{live_server}/report/2469/report.html"
        with urllib.request.urlopen(url_html) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("Content-Type", "")
            content = resp.read().decode("utf-8")
            assert len(content) > 1000

        url_json = f"{live_server}/report/2469/report.json"
        with urllib.request.urlopen(url_json) as resp:
            assert resp.status == 200
            assert "application/json" in resp.headers.get("Content-Type", "")
            data = json.loads(resp.read().decode("utf-8"))
            assert data["project_id"] == "2469"

    def test_new_module_endpoints(self, live_server: str) -> None:
        """Verify dedicated endpoints for imagery, canopy, and limitations."""
        for ep in ["imagery", "canopy", "limitations"]:
            url = f"{live_server}/api/project/2469/{ep}"
            with urllib.request.urlopen(url) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert isinstance(data, dict)

        # Demo returns null or 200 with null values for missing modules
        url_demo_img = f"{live_server}/api/project/demo/imagery"
        with urllib.request.urlopen(url_demo_img) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["funnel"] is None

        url_demo_can = f"{live_server}/api/project/demo/canopy"
        with urllib.request.urlopen(url_demo_can) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data is None

    def test_static_files(self, live_server: str) -> None:
        """Verify static files in web/ are properly served."""
        for path, expected_type in [
            ("/", "text/html"),
            ("/index.html", "text/html"),
            ("/app.js", "javascript"),
            ("/theme.css", "css"),
            ("/copy.json", "application/json"),
        ]:
            url = f"{live_server}{path}"
            with urllib.request.urlopen(url) as resp:
                assert resp.status == 200
                assert expected_type in resp.headers.get("Content-Type", "")


class TestForbiddenStrings:
    """Security audit ensuring no forbidden mock strings appear in web/ or copy.json."""

    def test_no_forbidden_strings_in_web(self) -> None:
        """Verify that forbidden strings do not appear anywhere in web/."""
        forbidden_tokens = [
            "verified",
            "validated",
            "confirmed",
            "proves",
            "because",
            "due to",
            "drought",
            "haze",
            "encroachment",
            "atmospheric",
            "contamination",
            "clear-sky",
            "cloud",
            "anomaly",
            "T36MYF",
            "32636",
            "Merkle",
            "IPFS",
            "Telemetry",
            "ISO 14064",
            "Ruvubu",
        ]

        web_dir = Path("web")
        assert web_dir.exists() and web_dir.is_dir()

        violations = []
        for root, _, files in os.walk(web_dir):
            for fname in files:
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

                for token in forbidden_tokens:
                    matches = list(re.finditer(re.escape(token), text, re.IGNORECASE))
                    if matches:
                        for m in matches:
                            snippet = text[max(0, m.start() - 25) : min(len(text), m.end() + 25)]
                            violations.append(f"{fpath}: found '{token}' in '...{snippet}...'")

        assert not violations, "Forbidden strings found in web/:\n" + "\n".join(violations)


class TestWebAppCodeHygiene:
    """Hygiene tests for web/app.js and web/copy.json."""

    def test_no_hardcoded_numeric_t_or_demo_values_in_app_js(self) -> None:
        """(a) app.js contains no match for \\b0\\.(60|65|70|75)\\b and no '1,179' or '120.9'."""
        code = Path("web/app.js").read_text(encoding="utf-8")
        assert not re.search(r"\b0\.(60|65|70|75)\b", code), "Found numeric T literal in web/app.js"
        assert "1,179" not in code, "Found '1,179' in web/app.js"
        assert "120.9" not in code, "Found '120.9' in web/app.js"

    def test_no_inline_string_fallbacks_in_app_js(self) -> None:
        """(b) Ensure web/app.js contains no || ["'`] fallback followed by any character except a closing quote."""
        code = Path("web/app.js").read_text(encoding="utf-8")
        match = re.search(r'\|\|\s*(["\'`])(?!\1)', code)
        assert match is None, f"Found inline string fallback in web/app.js: {match.group(0) if match else ''}"

    def test_app_js_strict_regex_and_no_project_numbers(self) -> None:
        """(c) app.js contains no \\b(2469|1300|541|885|1720|1555|162|189|185)\\b and no '|| \"' followed by a letter."""
        code = Path("web/app.js").read_text(encoding="utf-8")
        assert not re.search(r"\b(2469|1300|541|885|1720|1555|162|189|185)\b", code), "Found project number literal in app.js"
        assert not re.search(r'\|\|\s*"[a-zA-Z]', code), "Found || \" followed by a letter in app.js"

    def test_app_js_no_of_pattern(self) -> None:
        """Verify web/app.js has no `} of ${` pattern."""
        app_js = Path("web/app.js").read_text(encoding="utf-8")
        assert not re.search(r"\}\s*of\s*\$\{", app_js), "Found `} of ${` pattern in web/app.js"

    def test_no_error_color_in_break_even_rendering(self) -> None:
        """Ensure web/app.js contains no error colour class in break-even rendering."""
        code = Path("web/app.js").read_text(encoding="utf-8")
        idx_start = code.find("<!-- Break-Even Forest Allowance Cards -->")
        idx_end = code.find("const primaryRow = gridRows")
        assert idx_start != -1 and idx_end != -1
        break_even_section = code[idx_start:idx_end]

        idx_tbl_start = code.find("function renderBreakEvenRows")
        idx_tbl_end = code.find("// Render Sensitivity Curve SVG")
        assert idx_tbl_start != -1 and idx_tbl_end != -1
        break_even_table = code[idx_tbl_start:idx_tbl_end]

        combined = break_even_section + "\n" + break_even_table
        assert "error" not in combined.lower(), "Found 'error' colour class in break-even rendering"

    def test_copy_json_validity_and_coverage(self) -> None:
        """(c) Ensure web/copy.json is valid JSON with required keys and covered by forbidden strings."""
        copy_path = Path("web/copy.json")
        assert copy_path.exists()
        data = json.loads(copy_path.read_text(encoding="utf-8"))
        assert "units" in data
        assert "shell" in data
        assert "area_test" in data
        assert "imagery" in data
        assert "canopy" in data
        assert "limitations" in data
        assert "break_even_card_template" in data["area_test"]
        assert "allowance_label" in data["area_test"]
        assert "margin_label" in data["area_test"]
        assert "break_even_table_title" in data["area_test"]
        assert "generous_tag" in data["area_test"]
        assert "primary_tag" in data["area_test"]
        assert "strict_tag" in data["area_test"]
        assert "Shortfall at this T" in data["area_test"]["shortfall_display_label"]


class TestNewModulePayloads:
    """Test additive modules: imagery, canopy, limitations."""

    def test_temporary_project_with_custom_numbers(self, tmp_path: Path) -> None:
        """(a) Temporary project directory with custom files yields derived values with none equal to 2469."""
        from src.carbonverify.webapi import (
            build_imagery_payload,
            build_canopy_payload,
            build_limitations_payload,
        )

        proj_dir = tmp_path / "data" / "projects" / "custom_proj"
        out_proj = tmp_path / "output" / "custom_proj"
        proj_dir.mkdir(parents=True)
        out_proj.mkdir(parents=True)

        custom_report = {
            "project_id": "custom_proj",
            "status": "CONSISTENT",
            "confidence": "HIGH",
            "confidence_reasons": ["Custom limitation caveat 1", "Custom limitation caveat 2"],
            "claims": {
                "reporting_period_start": "2025-01-01",
                "reporting_period_end": "2025-12-31",
                "claimed_area_ha": 777.0,
            },
            "estimate": {
                "canopy_biomass": {
                    "thresholds": ["0.55", "0.65"],
                    "years": ["2024", "2025"],
                    "primary_threshold": "0.55",
                    "table": {
                        "0.55": {
                            "2024": {"area_ha": 333.3, "share_pct": 45.0},
                            "2025": {"area_ha": 444.4, "share_pct": 60.0},
                        }
                    },
                    "canopy_change_pct": 33.3,
                    "canopy_change_grid_range": [20.0, 40.0],
                    "biomass_proxy_by_year": {
                        "2024": {"mean": 0.51, "p90": 0.71},
                        "2025": {"mean": 0.61, "p90": 0.81},
                    },
                    "biomass_proxy_change_pct": 19.6,
                    "reference_buffer_raw_medians": {"2024": 0.42, "2025": 0.45},
                    "reference_buffer_change_pct": 7.1,
                },
                "saturation_share_pct": 12.34,
                "file_hashes": {"custom_boundary.geojson": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"},
            },
        }
        with open(out_proj / "report.json", "w", encoding="utf-8") as f:
            json.dump(custom_report, f)

        # Custom qc_scenes.csv
        qc_file = proj_dir / "qc_scenes.csv"
        with open(qc_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scene_id", "date", "proj_ndvi_median", "ring_ndvi_median", "qc_pass", "qc_reasons"])
            writer.writerow(["SCENE_1", "2025-06-15", "0.52", "0.41", "True", ""])
            writer.writerow(["SCENE_2", "2025-07-20", "0.58", "0.43", "True", ""])
            writer.writerow(["SCENE_3", "2025-08-10", "0.20", "0.30", "False", "custom_cloud_flag"])

        # Custom timeseries.csv
        ts_file = proj_dir / "timeseries.csv"
        with open(ts_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scene_id", "date", "zone", "ndvi_median"])
            writer.writerow(["SCENE_1", "2025-06-15", "project", "0.52"])
            writer.writerow(["SCENE_2", "2025-07-20", "project", "0.58"])
            writer.writerow(["SCENE_3", "2025-08-10", "project", "0.20"])

        img_p = build_imagery_payload("custom_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_p is not None
        assert img_p["funnel"]["in_timeseries"] == 3
        assert img_p["funnel"]["passed"] == 2
        assert img_p["funnel"]["excluded_qc"] == 1
        assert img_p["exclusion_counts_by_reason"] == [{"flags": ["custom_cloud_flag"], "count": 1}]
        assert img_p["dry_season_qc_pass_per_year"] == {"2025": 2}
        assert len(img_p["time_series"]) == 3
        assert img_p["reporting_period_start"] == "2025-01-01"

        vals_2469 = {185, 162, 23, 189, 4, 1300, 541, 885.01, 1720.06, 94.35, 44.12}
        assert img_p["funnel"]["passed"] not in vals_2469
        assert img_p["funnel"]["in_timeseries"] not in vals_2469

        can_p = build_canopy_payload("custom_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert can_p is not None
        assert can_p["canopy_change_pct"] == 33.3
        assert can_p["saturation_share_pct"] == 12.34
        assert can_p["canopy_change_pct"] not in vals_2469
        assert can_p["saturation_share_pct"] not in vals_2469

        lim_p = build_limitations_payload("custom_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert lim_p is not None
        assert lim_p["limitations"] == ["Custom limitation caveat 1", "Custom limitation caveat 2"]
        assert "custom_boundary.geojson" in lim_p["file_hashes"]

    def test_project_with_no_files_gives_nulls(self, tmp_path: Path) -> None:
        """(b) A project with none of those files gives nulls, no exception."""
        from src.carbonverify.webapi import (
            build_imagery_payload,
            build_canopy_payload,
            build_limitations_payload,
        )

        empty_proj = tmp_path / "output" / "empty_proj"
        empty_proj.mkdir(parents=True)
        with open(empty_proj / "report.json", "w", encoding="utf-8") as f:
            json.dump({"project_id": "empty_proj"}, f)

        img_empty = build_imagery_payload("empty_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_empty is not None
        assert img_empty["funnel"] is None
        assert img_empty["exclusion_counts_by_reason"] is None
        assert img_empty["time_series"] is None

        can_empty = build_canopy_payload("empty_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert can_empty is None

        lim_empty = build_limitations_payload("empty_proj", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert lim_empty is not None
        assert lim_empty["limitations"] is None
        assert lim_empty["file_hashes"] is None

    def test_exclusion_counts_sum_to_excluded_qc(self, tmp_path: Path) -> None:
        """(a) Exclusion counts sum to excluded_qc on temp project with its own qc_scenes.csv (including two-flag row)."""
        from carbonverify.webapi import build_imagery_payload

        proj_dir = tmp_path / "data" / "projects" / "test_excl" / "imagery"
        proj_dir.mkdir(parents=True)
        out_proj = tmp_path / "output" / "test_excl"
        out_proj.mkdir(parents=True)
        with open(out_proj / "report.json", "w", encoding="utf-8") as f:
            json.dump({"project_id": "test_excl"}, f)

        qc_file = proj_dir / "qc_scenes.csv"
        with open(qc_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scene_id", "date", "proj_ndvi_median", "ring_ndvi_median", "qc_pass", "qc_reasons"])
            writer.writerow(["SCENE_1", "2025-06-15", "0.52", "0.41", "True", ""])
            writer.writerow(["SCENE_2", "2025-07-20", "0.58", "0.43", "True", ""])
            writer.writerow(["SCENE_3", "2025-08-10", "0.20", "0.30", "False", "bad_red;low_valid"])
            writer.writerow(["SCENE_4", "2025-08-15", "0.15", "0.25", "False", "common_mode_outlier"])
            writer.writerow(["SCENE_5", "2025-08-20", "0.10", "0.20", "False", "bad_red;low_valid"])

        img_p = build_imagery_payload("test_excl", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_p is not None
        funnel = img_p["funnel"]
        assert funnel is not None
        assert funnel["in_timeseries"] == 5
        assert funnel["passed"] == 2
        assert funnel["excluded_qc"] == 3
        excl_list = img_p["exclusion_counts_by_reason"]
        assert excl_list is not None
        total_counts = sum(item["count"] for item in excl_list)
        assert total_counts == funnel["excluded_qc"] == 3

        # Verify two-flag item
        two_flag = [item for item in excl_list if len(item["flags"]) == 2]
        assert len(two_flag) == 1
        assert two_flag[0]["flags"] == ["bad_red", "low_valid"]
        assert two_flag[0]["count"] == 2

        # Also verify real project 2469
        p2469 = build_imagery_payload("2469", output_dir="output", data_dir="data/projects")
        assert p2469 is not None
        f2469 = p2469["funnel"]
        assert f2469 is not None
        excl_2469 = p2469["exclusion_counts_by_reason"]
        assert excl_2469 is not None
        assert sum(item["count"] for item in excl_2469) == f2469["excluded_qc"] == 23

    def test_funnel_nulls_without_stac_items(self, tmp_path: Path) -> None:
        """(b) Funnel fetched and excluded_ingest are null without stac_items.json or when dates < in_timeseries."""
        from carbonverify.webapi import build_imagery_payload

        proj_dir = tmp_path / "data" / "projects" / "test_funnel" / "imagery"
        proj_dir.mkdir(parents=True)
        out_proj = tmp_path / "output" / "test_funnel"
        out_proj.mkdir(parents=True)
        with open(out_proj / "report.json", "w", encoding="utf-8") as f:
            json.dump({"project_id": "test_funnel"}, f)

        qc_file = proj_dir / "qc_scenes.csv"
        with open(qc_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["scene_id", "date", "proj_ndvi_median", "ring_ndvi_median", "qc_pass", "qc_reasons"])
            writer.writerow(["SCENE_1", "2025-06-15", "0.52", "0.41", "True", ""])
            writer.writerow(["SCENE_2", "2025-07-20", "0.58", "0.43", "False", "low_valid"])

        # 1. Missing stac_items.json
        img_p1 = build_imagery_payload("test_funnel", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_p1 is not None
        f1 = img_p1["funnel"]
        assert f1 is not None
        assert f1["fetched"] is None
        assert f1["excluded_ingest"] is None
        assert f1["in_timeseries"] == 2
        assert f1["excluded_qc"] == 1
        assert f1["passed"] == 1

        # 2. Unreadable stac_items.json
        stac_file = proj_dir / "stac_items.json"
        with open(stac_file, "w", encoding="utf-8") as sf:
            sf.write("CORRUPTED NOT JSON")

        img_p2 = build_imagery_payload("test_funnel", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_p2 is not None
        f2 = img_p2["funnel"]
        assert f2 is not None
        assert f2["fetched"] is None
        assert f2["excluded_ingest"] is None
        assert f2["in_timeseries"] == 2

        # 3. stac_items.json has fewer dates than in_timeseries (1 < 2)
        with open(stac_file, "w", encoding="utf-8") as sf:
            json.dump([{"datetime": "2025-06-15T00:00:00Z"}], sf)

        img_p3 = build_imagery_payload("test_funnel", output_dir=tmp_path / "output", data_dir=tmp_path / "data" / "projects")
        assert img_p3 is not None
        f3 = img_p3["funnel"]
        assert f3 is not None
        assert f3["fetched"] is None
        assert f3["excluded_ingest"] is None
        assert f3["in_timeseries"] == 2

    def test_copy_json_no_4_digit_years(self) -> None:
        """(c) Verify copy.json canopy and limitations sections contain no 4-digit year."""
        copy_path = Path("web/copy.json")
        data = json.loads(copy_path.read_text(encoding="utf-8"))
        year_regex = re.compile(r"\b(19|20)\d\d\b")
        for section in ["canopy", "limitations"]:
            assert section in data, f"Missing section {section} in copy.json"
            sec_str = json.dumps(data[section])
            matches = year_regex.findall(sec_str)
            assert not matches, f"Found 4-digit years in copy.json['{section}']: {matches}"


