"""Streamlit interactive viewer for CarbonVerify verification reports.

Reads precomputed outputs directly from output/<project>/ with zero recomputation
and zero network requests. Displays verification verdicts, claims audit trails,
area test sensitivities, canopy/biomass timeseries, scene QC funnels, vector maps,
and rendered HTML reports.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import folium
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from carbonverify.viewer import (
    get_area_test_data,
    get_canopy_biomass_data,
    get_claims_table,
    get_verdict_summary,
    list_output_projects,
    load_extraction_report_json,
    load_imagery_qc_data,
    load_project_figures,
    load_project_geometries,
    load_report_html,
    load_report_json,
)

st.set_page_config(
    page_title="CarbonVerify Viewer",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom styles
st.markdown(
    """
    <style>
    .badge-status {
        font-size: 1.1rem;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 6px;
        display: inline-block;
    }
    .badge-CONSISTENT { background-color: #dcfce7; color: #166534; }
    .badge-DISCREPANCY_DETECTED { background-color: #fee2e2; color: #991b1b; }
    .badge-HIGH { background-color: #dcfce7; color: #166534; }
    .badge-MEDIUM { background-color: #fef3c7; color: #92400e; }
    .badge-LOW { background-color: #fee2e2; color: #991b1b; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Sidebar: Project Picker
st.sidebar.title("🛰️ CarbonVerify")
st.sidebar.caption("Remote Sensing Project Audit Viewer")

output_base = Path("output")
available_projects = list_output_projects(output_base)

if not available_projects:
    st.error("No project reports found under output/. Run `carbonverify run` first.")
    st.stop()

selected_project = st.sidebar.selectbox(
    "Select Project",
    options=available_projects,
    index=0,
)

# Load project report
report_data = load_report_json(output_base, selected_project)
if not report_data:
    st.error(f"Failed to load report.json for project '{selected_project}'.")
    st.stop()

extraction_data = load_extraction_report_json(output_base, selected_project)
html_content = load_report_html(output_base, selected_project)

# Demo Banner
is_demo = bool(report_data.get("demo", False) or report_data.get("claims", {}).get("demo", False))
if is_demo:
    st.warning("⚠️ **Demo Project Fixture** — Synthetic demonstration dataset. Results are illustrative only.")

verdict = get_verdict_summary(report_data)

st.title(f"Project Assessment: {selected_project}")
st.caption(f"Registry: {verdict['registry']} • Methodology: {verdict['methodology']}")

# Main Navigation Tabs
tabs = st.tabs(
    [
        "Verdict",
        "Claims",
        "Area Test",
        "Canopy and Biomass",
        "Imagery QC",
        "Figures",
        "Map",
        "Report",
    ]
)

# ---------------------------------------------------------
# Tab 1: Verdict
# ---------------------------------------------------------
with tabs[0]:
    st.header("Verification Verdict & Confidence")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Status", str(verdict["status"]))
    with col2:
        st.metric("Confidence", str(verdict["confidence"]))
    with col3:
        ca = verdict["claimed_area_ha"]
        st.metric("Claimed Area", f"{ca:,.1f} ha" if isinstance(ca, (int, float)) else str(ca))
    with col4:
        low = verdict["obs_low"]
        high = verdict["obs_high"]
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            band_str = f"[{low:,.1f}, {high:,.1f}] ha"
        else:
            band_str = "not available"
        st.metric("Planted-Area Band", band_str)

    st.subheader("Summary Notes")
    st.info(verdict["summary"])

    st.subheader("Confidence Assessment Reasons")
    reasons = verdict["confidence_reasons"]
    if reasons:
        for r in reasons:
            st.markdown(f"- {r}")
    else:
        st.write("No specific confidence flags recorded.")

    with st.expander("Additional Discrepancy Details", expanded=False):
        c_a, c_b, c_c = st.columns(3)
        c_a.metric("Estate Footprint", f"{verdict['estate_area_ha']} ha" if verdict['estate_area_ha'] != "not available" else "not available")
        c_b.metric("Central Shortfall", f"{verdict['shortfall_central_ha']} ha" if verdict['shortfall_central_ha'] != "not available" else "not available")
        c_c.metric("Lower-Bound Shortfall", f"{verdict['shortfall_low_ha']} ha" if verdict['shortfall_low_ha'] != "not available" else "not available")


# ---------------------------------------------------------
# Tab 2: Claims
# ---------------------------------------------------------
with tabs[1]:
    st.header("Documented Registry Claims")
    st.caption("Parameters extracted from project PDD and Monitoring Reports with source provenance.")

    claims_rows = get_claims_table(report_data, extraction_data)
    df_claims = pd.DataFrame(claims_rows)
    st.dataframe(df_claims, use_container_width=True)

    # Planting Schedule if present
    claims_dict = report_data.get("claims") or {}
    schedule = claims_dict.get("planting_schedule")
    if schedule and isinstance(schedule, list):
        st.subheader("Annual Planting Schedule by Stratum")
        df_sched = pd.DataFrame(schedule)
        st.dataframe(df_sched, use_container_width=True)


# ---------------------------------------------------------
# Tab 3: Area Test
# ---------------------------------------------------------
with tabs[2]:
    st.header("Satellite Area Verification & Sensitivity")
    area_data = get_area_test_data(report_data)

    grid_rows = area_data["grid_rows"]
    if grid_rows:
        st.subheader("Threshold Grid Evaluation: obs(T) = A2022(T) - Forest Allowance")

        # Matplotlib chart
        ts: List[float] = []
        obs_vals: List[float] = []
        for r in grid_rows:
            try:
                t_f = float(r["threshold"])
                o_f = float(r["obs_ha"])
                ts.append(t_f)
                obs_vals.append(o_f)
            except (ValueError, TypeError):
                continue

        if ts and obs_vals:
            fig, ax = plt.subplots(figsize=(9, 4.5))
            ax.plot(ts, obs_vals, marker="o", color="#1e40af", linewidth=2.2, label="Satellite Observed obs(T)")

            cl_area = area_data["claimed_area_ha"]
            if isinstance(cl_area, (int, float)):
                ax.axhline(cl_area, color="#dc2626", linestyle="--", linewidth=1.8, label=f"Claimed ({cl_area:,.1f} ha)")

            b_low = area_data["obs_low"]
            b_high = area_data["obs_high"]
            if isinstance(b_low, (int, float)) and isinstance(b_high, (int, float)):
                ax.axhspan(b_low, b_high, color="#bfdbfe", alpha=0.4, label=f"Observation Band [{b_low:,.1f}, {b_high:,.1f}] ha")

            ax.set_xlabel("Quantile-Mapped NDVI Threshold (T)", fontsize=11)
            ax.set_ylabel("Planted Forest Area (ha)", fontsize=11)
            ax.set_title("Planted Area Estimate vs Registry Claim", fontsize=12, fontweight="bold")
            ax.grid(True, linestyle=":", alpha=0.6)
            ax.legend(loc="best", frameon=True)
            st.pyplot(fig)
            plt.close(fig)

        # Table of A2022, Forest Allowance, obs(T), shortfall
        df_grid = pd.DataFrame(grid_rows)
        st.dataframe(df_grid, use_container_width=True)
    else:
        st.info("Multi-threshold grid estimates not available for this project.")

    # Sensitivity and Break-even
    col_raw, col_be = st.columns(2)
    with col_raw:
        st.subheader("RAW Normalisation Sensitivity (Without Ring Normalisation)")
        norm_sens = area_data.get("normalization_sensitivity")
        if norm_sens and isinstance(norm_sens, dict):
            raw_b = norm_sens.get("raw_band", {})
            st.write(f"- **RAW Band:** `[{raw_b.get('low', 'not available')}, {raw_b.get('high', 'not available')}]` ha")
            st.write(f"- **RAW Central:** `{raw_b.get('central', 'not available')}` ha")
            st.write(f"- **Span / Claim:** `{raw_b.get('span_pct', 'not available')}%`")
            st.write(f"- **Detection Limit:** `{raw_b.get('detection_limit_pct', 'not available')}%`")
        else:
            st.write("not available")

    with col_be:
        st.subheader("Natural Forest Break-Even Allowance")
        fa_check = area_data.get("forest_allowance_check")
        if fa_check and isinstance(fa_check, dict):
            st.write(f"- **Generous End (T = 0.60):** `{fa_check.get('break_even_generous_ha', 'not available')}` ha")
            st.write(f"- **Margin Above Claim:** `{fa_check.get('margin_generous_ha', 'not available')}` ha")
            st.write(f"- **Strict End (T = 0.75):** `{fa_check.get('break_even_strict_ha', 'not available')}` ha")
            st.write(f"- **Strict Shortfall:** `{fa_check.get('shortfall_strict_ha', 'not available')}` ha")
        else:
            st.write("not available")


# ---------------------------------------------------------
# Tab 4: Canopy and Biomass
# ---------------------------------------------------------
with tabs[3]:
    st.header("Independent Canopy-Cover & Biomass-Proxy Change")
    cb_data = get_canopy_biomass_data(report_data)

    if not cb_data["available"]:
        st.info("Canopy and biomass change estimates not available for this project.")
    else:
        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric("Primary Canopy Change (T = 0.70)", f"+{cb_data['canopy_change_pct']}%" if cb_data['canopy_change_pct'] != "not available" else "not available")
        c_m2.metric("Boundary Biomass Proxy Change", f"+{cb_data['biomass_proxy_change_pct']}%" if cb_data['biomass_proxy_change_pct'] != "not available" else "not available")
        c_m3.metric("Reference Ring Raw Median Change", f"+{cb_data['reference_buffer_change_pct']}%" if cb_data['reference_buffer_change_pct'] != "not available" else "not available")

        st.subheader("Per-Year Canopy Cover and Proxy Values")
        df_cb = pd.DataFrame(cb_data["table_rows"])
        st.dataframe(df_cb, use_container_width=True)

        if cb_data["p90_sentence"] != "not available":
            st.caption(f"ℹ️ {cb_data['p90_sentence']}")

        # Charts: Canopy area across thresholds & Biomass proxy over time
        tbl = cb_data.get("table", {})
        years = cb_data.get("years", [])
        thresholds = cb_data.get("thresholds", [])

        if years and thresholds and tbl:
            st.subheader("Canopy Cover & Biomass Proxy Trends")
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

            # Left: Canopy cover lines
            for t in thresholds:
                t_areas = [tbl.get(t, {}).get(y, {}).get("area_ha", 0.0) for y in years]
                ax1.plot(years, t_areas, marker="s", linewidth=2, label=f"T = {t}")
            ax1.set_xlabel("Year")
            ax1.set_ylabel("Canopy Area (ha)")
            ax1.set_title("Canopy Area by Threshold (2019-2022)")
            ax1.grid(True, linestyle=":", alpha=0.6)
            ax1.legend()

            # Right: Biomass proxy mean
            b_info = cb_data.get("biomass_proxy_by_year", {})
            means = [b_info.get(y, {}).get("mean", 0.0) for y in years]
            p90s = [b_info.get(y, {}).get("p90", 0.0) for y in years]
            ax2.plot(years, means, marker="o", color="#059669", linewidth=2.2, label="Mean qm NDVI")
            ax2.plot(years, p90s, marker="^", color="#10b981", linestyle="--", linewidth=1.8, label="p90 qm NDVI")
            ax2.set_xlabel("Year")
            ax2.set_ylabel("NDVI Proxy")
            ax2.set_title("Biomass Proxy Trajectory")
            ax2.grid(True, linestyle=":", alpha=0.6)
            ax2.legend()

            st.pyplot(fig)
            plt.close(fig)


# ---------------------------------------------------------
# Tab 5: Imagery QC
# ---------------------------------------------------------
with tabs[4]:
    st.header("Satellite Scene Ingestion & Quality Control Funnel")
    qc_info = load_imagery_qc_data(output_base, selected_project)

    q_c1, q_c2, q_c3 = st.columns(3)
    q_c1.metric("Total Scenes Analyzed", str(qc_info["total_scenes"]))
    q_c2.metric("QC Pass Scenes", str(qc_info["pass_scenes"]))
    q_c3.metric("Excluded Scenes", str(qc_info["excluded_scenes"]))

    if qc_info["reasons_breakdown"]:
        st.subheader("Exclusion Causes Breakdown")
        df_reasons = pd.DataFrame(
            list(qc_info["reasons_breakdown"].items()), columns=["Exclusion Reason", "Count"]
        )
        st.dataframe(df_reasons, use_container_width=True)

    st.subheader("Excluded Scenes Detail Table")
    if qc_info["excluded_records"]:
        df_ex = pd.DataFrame(qc_info["excluded_records"])
        st.dataframe(df_ex, use_container_width=True)
    else:
        st.write("No excluded scene records found.")


# ---------------------------------------------------------
# Tab 6: Figures
# ---------------------------------------------------------
with tabs[5]:
    st.header("Project Verification Figures")
    st.caption("Precomputed visual evidence artifacts from project and output directories (zero recomputation).")

    figs = load_project_figures(output_base, selected_project)

    st.subheader("Figure 1: Hysteresis Cohort Maps")
    cohort_fig = figs.get("cohort_maps")
    if cohort_fig and cohort_fig.exists():
        st.image(str(cohort_fig), use_container_width=True)
    else:
        st.write("not available")

    st.subheader("Figure 2: Sentinel-2 Zone NDVI Time Series")
    ts_fig = figs.get("zone_timeseries")
    if ts_fig and ts_fig.exists():
        st.image(str(ts_fig), use_container_width=True)
    else:
        st.write("not available")

    st.subheader("Figure 3: High-NDVI Decline & Hansen Classification")
    decline_fig = figs.get("decline_map")
    if decline_fig and decline_fig.exists():
        st.image(str(decline_fig), use_container_width=True)
    else:
        st.write("not available")


# ---------------------------------------------------------
# Tab 7: Map
# ---------------------------------------------------------
with tabs[6]:
    st.header("Geographic Project Footprint & Reference Ring")
    st.caption("Interactive vector overlay of project boundaries without rasterisation.")

    geoms = load_project_geometries(output_base, selected_project)
    b_geom = geoms.get("boundary")
    r_geom = geoms.get("reference_ring")

    if not b_geom:
        st.warning("Project boundary GeoJSON file not available for interactive map.")
    else:
        # Compute centroid from boundary coordinates
        try:
            coords = []
            features = b_geom.get("features", [])
            for feat in features:
                geom = feat.get("geometry", {})
                g_type = geom.get("type")
                g_coords = geom.get("coordinates", [])
                if g_type == "Polygon":
                    for ring in g_coords:
                        coords.extend(ring)
                elif g_type == "MultiPolygon":
                    for poly in g_coords:
                        for ring in poly:
                            coords.extend(ring)

            if coords:
                center_lat = sum(c[1] for c in coords) / len(coords)
                center_lon = sum(c[0] for c in coords) / len(coords)
            else:
                center_lat, center_lon = 0.0, 0.0
        except Exception:
            center_lat, center_lon = 0.0, 0.0

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles="CartoDB positron",
        )

        popup_html = (
            f"<div style='font-family: sans-serif; font-size: 13px;'>"
            f"<b>Project ID:</b> {selected_project}<br>"
            f"<b>Claimed Area:</b> {verdict['claimed_area_ha']} ha<br>"
            f"<b>Status:</b> {verdict['status']}<br>"
            f"<b>Confidence:</b> {verdict['confidence']}"
            f"</div>"
        )

        # Vector boundary overlay (not rasterised)
        folium.GeoJson(
            b_geom,
            name="Project Boundary",
            style_function=lambda x: {
                "fillColor": "#10b981",
                "color": "#059669",
                "weight": 2.5,
                "fillOpacity": 0.35,
            },
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"Project {selected_project} Boundary",
        ).add_to(m)

        # Reference ring overlay if available
        if r_geom:
            folium.GeoJson(
                r_geom,
                name="Reference Ring (10 km buffer)",
                style_function=lambda x: {
                    "fillColor": "#f59e0b",
                    "color": "#d97706",
                    "weight": 2.0,
                    "fillOpacity": 0.25,
                },
                tooltip="10 km External Reference Ring",
            ).add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width=1000, height=600)


# ---------------------------------------------------------
# Tab 8: Report
# ---------------------------------------------------------
with tabs[7]:
    st.header("Audit Verification Report")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button(
            label="📥 Download report.json",
            data=json.dumps(report_data, indent=2),
            file_name=f"report_{selected_project}.json",
            mime="application/json",
        )
    with col_d2:
        if html_content:
            st.download_button(
                label="📥 Download report.html",
                data=html_content,
                file_name=f"report_{selected_project}.html",
                mime="text/html",
            )

    if html_content:
        st.subheader("Embedded HTML Report")
        components.html(html_content, height=850, scrolling=True)
    else:
        st.info("report.html not found for this project.")
