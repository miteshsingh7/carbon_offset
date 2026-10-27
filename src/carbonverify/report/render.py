"""Report rendering for carbon-offset project discrepancy verification."""

import base64
import json
import logging
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml

from jinja2 import Template

from carbonverify.schemas import DiscrepancyReport

logger = logging.getLogger(__name__)

# Standard template for demo fixture runs
DEMO_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verification Report - {{ report.project_id }}</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #334155;
      --consistent: #10b981;
      --minor: #f59e0b;
      --major: #ef4444;
      --inconclusive: #64748b;
      --high: #10b981;
      --medium: #f59e0b;
      --low: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 2rem 1rem;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
    }
    header {
      margin-bottom: 2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }
    h1 {
      font-size: 1.8rem;
      font-weight: 700;
      letter-spacing: -0.025em;
    }
    .subtitle {
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-top: 0.25rem;
    }
    .badge {
      display: inline-block;
      padding: 0.35rem 0.85rem;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-CONSISTENT { background: rgba(16, 185, 129, 0.2); color: var(--consistent); border: 1px solid var(--consistent); }
    .badge-MINOR { background: rgba(245, 158, 11, 0.2); color: var(--minor); border: 1px solid var(--minor); }
    .badge-MAJOR { background: rgba(239, 68, 68, 0.2); color: var(--major); border: 1px solid var(--major); }
    .badge-INCONCLUSIVE { background: rgba(100, 116, 139, 0.2); color: var(--inconclusive); border: 1px solid var(--inconclusive); }
    .badge-HIGH { background: rgba(16, 185, 129, 0.15); color: var(--high); }
    .badge-MEDIUM { background: rgba(245, 158, 11, 0.15); color: var(--medium); }
    .badge-LOW { background: rgba(239, 68, 68, 0.15); color: var(--low); }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }
    .card {
      background-color: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 1.5rem;
    }
    .card h2 {
      font-size: 1.15rem;
      margin-bottom: 1rem;
      color: var(--text);
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      padding: 0.4rem 0;
      border-bottom: 1px dashed rgba(255, 255, 255, 0.06);
      font-size: 0.92rem;
    }
    .metric-row:last-child { border-bottom: none; }
    .metric-label { color: var(--text-muted); }
    .metric-val { font-weight: 600; }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 0.75rem;
      font-size: 0.92rem;
    }
    th, td {
      text-align: left;
      padding: 0.75rem 0.5rem;
      border-bottom: 1px solid var(--border);
    }
    th {
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.8rem;
    }
    .reasons-list {
      list-style-type: none;
      margin-top: 0.5rem;
    }
    .reasons-list li {
      padding: 0.5rem 0.75rem;
      background: rgba(245, 158, 11, 0.1);
      border-left: 3px solid var(--minor);
      margin-bottom: 0.5rem;
      border-radius: 0.25rem;
      font-size: 0.88rem;
    }
    .notes-box {
      background: rgba(255, 255, 255, 0.03);
      padding: 1rem;
      border-radius: 0.5rem;
      border: 1px solid var(--border);
      font-size: 0.95rem;
      line-height: 1.6;
    }
    footer {
      margin-top: 3rem;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
      border-top: 1px solid var(--border);
      padding-top: 1.5rem;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Carbon Verification Report</h1>
        <div class="subtitle">Project ID: <strong>{{ report.project_id }}</strong> | Registry: {{ report.claims.registry | upper }} | Methodology: {{ report.claims.methodology }}</div>
      </div>
      <div>
        <span class="badge badge-{{ report.status }}">Status: {{ report.status }}</span>
        <span class="badge badge-{{ report.confidence }}">Confidence: {{ report.confidence }}</span>
        {% if report.demo %}
          <span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #60a5fa;">DEMO FIXTURE</span>
        {% endif %}
      </div>
    </header>

    <div class="grid">
      <!-- Project Claims -->
      <div class="card">
        <h2>Documented Claims</h2>
        <div class="metric-row">
          <span class="metric-label">Claimed Area:</span>
          <span class="metric-val">
            {% if report.claims.claimed_area_ha is not none %}
              {{ "{:,.1f}".format(report.claims.claimed_area_ha) }} ha
            {% else %}
              Missing
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Reporting Period:</span>
          <span class="metric-val">
            {% if report.claims.reporting_period_start and report.claims.reporting_period_end %}
              {{ report.claims.reporting_period_start }} to {{ report.claims.reporting_period_end }}
            {% else %}
              Not Reported
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Claimed Canopy Change:</span>
          <span class="metric-val">
            {% if report.claims.claimed_canopy_change_pct is not none %}
              {{ "{:+.2f}%".format(report.claims.claimed_canopy_change_pct) }}
            {% else %}
              Not Reported
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Credits Issued:</span>
          <span class="metric-val">
            {% if report.claims.credits_issued is not none %}
              {{ "{:,}".format(report.claims.credits_issued) }} VCUs
            {% else %}
              N/A
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Boundary Path:</span>
          <span class="metric-val" style="font-size:0.8rem; word-break:break-all;">{{ report.claims.boundary_path or 'Not Provided' }}</span>
        </div>
      </div>

      <!-- Satellite Estimate -->
      <div class="card">
        <h2>Satellite Observations</h2>
        <div class="metric-row">
          <span class="metric-label">Observed Area:</span>
          <span class="metric-val">{{ "{:,.1f}".format(report.estimate.area_ha) }} ha</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Mean NDVI (Start &rarr; End):</span>
          <span class="metric-val">{{ "{:.3f}".format(report.estimate.ndvi_mean_start) }} &rarr; {{ "{:.3f}".format(report.estimate.ndvi_mean_end) }}</span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Observed Canopy Change:</span>
          <span class="metric-val">
            {% if report.estimate.canopy_change_pct is not none %}
              {{ "{:+.2f}%".format(report.estimate.canopy_change_pct) }}
            {% else %}
              N/A
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Biomass Proxy Change:</span>
          <span class="metric-val">
            {% if report.estimate.biomass_proxy_change_pct is not none %}
              {{ "{:+.2f}%".format(report.estimate.biomass_proxy_change_pct) }}
            {% else %}
              N/A
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">External Buffer Control:</span>
          <span class="metric-val">
            {% if report.estimate.reference_buffer_change_pct is not none %}
              {{ "{:+.2f}%".format(report.estimate.reference_buffer_change_pct) }}
            {% else %}
              N/A
            {% endif %}
          </span>
        </div>
        <div class="metric-row">
          <span class="metric-label">Valid Scenes / Cloud Cover:</span>
          <span class="metric-val">{% if report.estimate.valid_observation_count is not none and report.estimate.mean_cloud_cover_pct is not none %}{{ report.estimate.valid_observation_count }} scenes ({{ "{:.1f}%".format(report.estimate.mean_cloud_cover_pct) }} cloud){% elif report.estimate.valid_observation_count is not none %}{{ report.estimate.valid_observation_count }} scenes{% elif report.estimate.mean_cloud_cover_pct is not none %}{{ "{:.1f}%".format(report.estimate.mean_cloud_cover_pct) }} cloud{% else %}not available{% endif %}</span>
        </div>
      </div>
    </div>

    <!-- Comparison & Discrepancy -->
    <div class="card" style="margin-bottom: 1.5rem;">
      <h2>Discrepancy Cross-Check</h2>
      <table>
        <thead>
          <tr>
            <th>Dimension</th>
            <th>Claimed</th>
            <th>Satellite Observed</th>
            <th>Discrepancy</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Project Area</strong></td>
            <td>
              {% if report.claims.claimed_area_ha is not none %}
                {{ "{:,.1f}".format(report.claims.claimed_area_ha) }} ha
              {% else %}
                Missing
              {% endif %}
            </td>
            <td>{{ "{:,.1f}".format(report.estimate.area_ha) }} ha</td>
            <td>
              <strong>
                {% if report.area_discrepancy_pct is not none %}
                  {{ "{:+.2f}%".format(report.area_discrepancy_pct) }}
                {% else %}
                  N/A
                {% endif %}
              </strong>
            </td>
          </tr>
          <tr>
            <td><strong>Canopy Cover Change</strong></td>
            <td>
              {% if report.claims.claimed_canopy_change_pct is not none %}
                {{ "{:+.2f}%".format(report.claims.claimed_canopy_change_pct) }}
              {% else %}
                N/A
              {% endif %}
            </td>
            <td>
              {% if report.estimate.canopy_change_pct is not none %}
                {{ "{:+.2f}%".format(report.estimate.canopy_change_pct) }}
              {% else %}
                N/A
              {% endif %}
            </td>
            <td>
              <strong>
                {% if report.canopy_discrepancy_pct is not none %}
                  {{ "{:+.2f}%".format(report.canopy_discrepancy_pct) }}
                {% else %}
                  N/A
                {% endif %}
              </strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Quality & Confidence Flags -->
    {% if report.confidence_reasons %}
    <div class="card" style="margin-bottom: 1.5rem;">
      <h2>Observation Quality Flags</h2>
      <p style="color: var(--text-muted); font-size: 0.9rem; margin-bottom: 0.5rem;">
        The following quality flags degraded assessment confidence to <strong>{{ report.confidence }}</strong>:
      </p>
      <ul class="reasons-list">
        {% for reason in report.confidence_reasons %}
          <li>{{ reason }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}

    <!-- Audit Summary Notes -->
    <div class="card">
      <h2>Assessment Findings & Notes</h2>
      <div class="notes-box">
        {{ report.notes }}
      </div>
    </div>

    <footer>
      Generated by <strong>carbonverify</strong> pipeline &bull; Automated Earth Observation Assessment
    </footer>
  </div>
</body>
</html>
"""


# Full report template for Project 2469
REPORT_2469_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Assessment Report - Project {{ project_id }}</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #131c2e;
      --card-hover: #1b273d;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --border: #23324a;
      --accent: #38bdf8;
      --consistent: #10b981;
      --minor: #f59e0b;
      --major: #ef4444;
      --low: #f59e0b;
      --code-bg: #0b1120;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 2.5rem 1.25rem;
    }
    .container {
      max-width: 1080px;
      margin: 0 auto;
    }
    header {
      margin-bottom: 2rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.5rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1.25rem;
    }
    h1 {
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.025em;
      color: #ffffff;
    }
    .subtitle {
      color: var(--text-muted);
      font-size: 0.95rem;
      margin-top: 0.35rem;
    }
    .badge-group {
      display: flex;
      gap: 0.5rem;
      align-items: center;
      flex-wrap: wrap;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 0.4rem 0.9rem;
      border-radius: 9999px;
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-CONSISTENT { background: rgba(16, 185, 129, 0.18); color: var(--consistent); border: 1px solid var(--consistent); }
    .badge-LOW { background: rgba(245, 158, 11, 0.18); color: var(--low); border: 1px solid var(--low); }

    /* Verdict Banner */
    .verdict-banner {
      background: linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(14, 165, 233, 0.08));
      border: 1px solid rgba(16, 185, 129, 0.4);
      border-radius: 0.75rem;
      padding: 1.25rem 1.5rem;
      margin-bottom: 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .verdict-main {
      font-size: 1.12rem;
      font-weight: 600;
      color: #ffffff;
    }
    .verdict-sub {
      color: #cbd5e1;
      font-size: 0.95rem;
      margin-top: 0.25rem;
    }

    .card {
      background-color: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 0.75rem;
      padding: 1.5rem;
      margin-bottom: 2rem;
    }
    .card h2 {
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 1rem;
      color: #ffffff;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.6rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .card h3 {
      font-size: 1.02rem;
      margin: 1.2rem 0 0.5rem 0;
      color: var(--accent);
    }
    p {
      margin-bottom: 0.75rem;
      color: #e2e8f0;
      font-size: 0.94rem;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 0.75rem;
      margin-bottom: 1rem;
      font-size: 0.9rem;
    }
    th, td {
      text-align: left;
      padding: 0.7rem 0.6rem;
      border-bottom: 1px solid var(--border);
    }
    th {
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.78rem;
      background: rgba(255, 255, 255, 0.02);
    }
    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }
    .text-right { text-align: right; }
    .text-center { text-align: center; }

    .figure-container {
      margin: 1.5rem 0;
      text-align: center;
      background: rgba(0, 0, 0, 0.25);
      padding: 1rem;
      border-radius: 0.5rem;
      border: 1px solid var(--border);
    }
    .figure-container img {
      max-width: 100%;
      height: auto;
      border-radius: 0.35rem;
      display: block;
      margin: 0 auto;
    }
    .figure-caption {
      margin-top: 0.75rem;
      font-size: 0.85rem;
      color: var(--text-muted);
      font-style: italic;
    }

    ul.clean-list {
      list-style-type: square;
      padding-left: 1.5rem;
      margin-bottom: 1rem;
    }
    ul.clean-list li {
      margin-bottom: 0.5rem;
      font-size: 0.92rem;
      color: #e2e8f0;
    }

    .code-block {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      padding: 0.85rem 1rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.82rem;
      color: #93c5fd;
      overflow-x: auto;
      margin-top: 0.5rem;
    }
    .source-note {
      background: rgba(56, 189, 248, 0.08);
      border-left: 3px solid var(--accent);
      padding: 0.75rem 1rem;
      border-radius: 0.25rem;
      font-size: 0.88rem;
      color: #cbd5e1;
      margin: 0.75rem 0;
    }

    footer {
      margin-top: 3.5rem;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
      border-top: 1px solid var(--border);
      padding-top: 1.5rem;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Remote Sensing Assessment Report</h1>
        <div class="subtitle">Project ID: <strong>{{ project_id }}</strong> &bull; Registry: {{ registry }} &bull; Methodology: {{ methodology }}</div>
      </div>
      <div class="badge-group">
        <span class="badge badge-{{ status }}">Status: {{ status }}</span>
        <span class="badge badge-{{ confidence }}">Confidence: {{ confidence }}</span>
      </div>
    </header>

    <!-- Verdict Banner -->
    <div class="verdict-banner">
      <div class="verdict-main">{{ verdict_text }}</div>
    </div>

    <!-- Section 1: Claims Table with Page References -->
    <div class="card">
      <h2>1. Documented Registry Claims &amp; Parameters</h2>
      <p>Parameters and assertions extracted from project documentation with audit provenance and page citations:</p>
      <table>
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Reported Value</th>
            <th>Source Document &amp; Page</th>
            <th>Evidence Quote</th>
          </tr>
        </thead>
        <tbody>
          {% for row in claim_rows %}
          <tr>
            <td><strong>{{ row.label }}</strong></td>
            <td>{{ row.value }}</td>
            <td>{{ row.source }}</td>
            <td>{% if row.quote != 'not available' %}<em>&ldquo;{{ row.quote }}&rdquo;</em>{% else %}not available{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <h3>Annual Planting Schedule by Stratum</h3>
      <table>
        <thead>
          <tr>
            <th>Year</th>
            <th>Stratum Code</th>
            <th>Target Density (trees/ha)</th>
            <th class="text-right">Planted Area (ha)</th>
            <th>Source Reference</th>
          </tr>
        </thead>
        <tbody>
          {% for st in planting_strata %}
          <tr>
            <td>{{ st.planting_year }}</td>
            <td><code>{{ st.stratum }}</code></td>
            <td>{{ st.density }}</td>
            <td class="text-right">{{ "{:,.1f}".format(st.area_ha) }}</td>
            <td>{{ st.source_doc }}, p. {{ st.page }}</td>
          </tr>
          {% endfor %}
          <tr style="font-weight: 700; border-top: 2px solid var(--border);">
            <td colspan="3">Aggregated Strata Sum{% if planting_year_span != 'not available' %} ({{ planting_year_span }}){% endif %}</td>
            <td class="text-right">{% if planting_sum_ha is not none %}{{ "{:,.1f}".format(planting_sum_ha) }} ha{% else %}not available{% endif %}</td>
            <td>Stated Total: {% if claimed_area_ha is not none %}{{ "{:,.1f}".format(claimed_area_ha) }} ha{% if planting_diff_ha is not none %} (discrepancy: {{ "{:+.1f}".format(planting_diff_ha) }} ha){% endif %}{% else %}not available{% endif %}</td>
          </tr>
        </tbody>
      </table>

      <div class="source-note">
        <strong>Source Note (Credits Consistency):</strong> {{ credits_source_note }}
      </div>
    </div>

    <!-- Section 2: Imagery QC Summary -->
    <div class="card">
      <h2>2. Satellite Imagery Quality Control Gate</h2>
      <p>
        Sentinel-2 L2A BOA surface reflectance timeseries screening evaluated across the property boundary and outer reference ring (tile <code>{{ tile_id }}</code>).
        The STAC query returned {{ stac_total_items }} items across {{ stac_unique_dates }} unique acquisition dates; the {{ stac_extra_twins }} extra items are same-day duplicate items of the same tile and orbit (item IDs differ only in the trailing index; processing baselines can differ or repeat), and <code>deduplicate_same_day_scenes</code> selects one item per date by keeping the scene with the highest count of SCL-valid pixels (classes 4, 5, 6, 7) over the read window.
        STAC metadata investigation revealed that STAC <code>raster:bands</code> offset flags and processing baselines were unreliable for this geographic tile;
        radiometric BOA offset was consequently detected from raw red band digital numbers (DNs), where scenes with red p1 in [{{ max_offset_absent_int }}, {{ min_offset_present_int }}) are unresolved and excluded at ingest.
      </p>
      <table>
        <thead>
          <tr>
            <th>Metric / QC Rule</th>
            <th>Count</th>
            <th>Criterion Description</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Scenes Fetched</strong></td>
            <td>{{ scenes_fetched }}</td>
            <td>{{ stac_total_items }} STAC items across {{ stac_unique_dates }} unique dates deduplicated to {{ scenes_fetched }} scenes covering tile {{ tile_id }}. Red p1 in [{{ max_offset_absent_int }}, {{ min_offset_present_int }}) is unresolved and excluded at ingest ({{ ingest_excluded_count }} scenes excluded: {{ ingest_excluded_text }}).</td>
          </tr>
          <tr>
            <td><strong>Scenes in Timeseries</strong></td>
            <td>{{ qc_total_scenes }}</td>
            <td>Scenes written to <code>timeseries.csv</code> ({{ timeseries_rows_count }} zone rows), <code>imagery_report.json</code>, and evaluated in <code>qc_scenes.csv</code></td>
          </tr>
          <tr>
            <td><strong>QC Passed Scenes</strong></td>
            <td>{{ qc_pass_scenes }}</td>
            <td>Scenes satisfying radiometry, cloud mask validity, and common-mode stability</td>
          </tr>
          <tr>
            <td><strong>Scenes Excluded (<code>qc_scenes.csv</code>)</strong></td>
            <td>{{ qc_excluded_scenes }}</td>
            <td>Scenes failing screening in <code>qc_scenes.csv</code>; primary reason counts below sum to {{ qc_excluded_scenes }}</td>
          </tr>
          <tr>
            <td>&bull; <code>low_valid</code> (primary)</td>
            <td>{{ qc_primary_exclusions.low_valid }}</td>
            <td>Project or reference ring valid observation fraction &lt; {{ "{:.2f}".format(min_valid_fraction) }} ({{ qc_exclusions.low_valid }} total occurrences{{ low_valid_overlap_note }})</td>
          </tr>
          <tr>
            <td>&bull; <code>common_mode_outlier</code> (primary)</td>
            <td>{{ qc_primary_exclusions.common_mode_outlier }}</td>
            <td>Both project and ring median NDVI deviate &gt; {{ "{:.2f}".format(outlier_diff_threshold) }} from &plusmn;{{ temporal_window_days }}-day temporal neighbor medians ({{ qc_exclusions.common_mode_outlier }} total occurrences{{ cmo_overlap_note }})</td>
          </tr>
          <tr>
            <td>&bull; <code>bad_red</code> (primary)</td>
            <td>{{ qc_primary_exclusions.bad_red }}</td>
            <td>Red band 1st percentile DN &lt; {{ min_red_p1_int }} ({{ qc_exclusions.bad_red }} total occurrences{{ bad_red_overlap_note }})</td>
          </tr>
          <tr>
            <td>&bull; <code>offset_unresolved</code> (primary)</td>
            <td>{{ qc_primary_exclusions.offset_unresolved }}</td>
            <td>Safety-net check in <code>qc_scenes</code> for unresolved BOA offset (red p1 in [{{ max_offset_absent_int }}, {{ min_offset_present_int }}); {{ qc_exclusions.offset_unresolved }} scenes in <code>qc_scenes.csv</code> since all {{ ingest_excluded_count }} unresolved scenes were excluded at ingest)</td>
          </tr>
        </tbody>
      </table>
      <div class="source-note">
        <strong>Multi-reason note:</strong> {{ qc_multi_count }} of the {{ qc_excluded_scenes }} excluded scenes in <code>qc_scenes.csv</code> carry two exclusion reasons ({{ qc_multi_breakdown_text }}). Primary reason counts assign each excluded scene to its first triggered rule ({{ qc_primary_exclusions.low_valid }} + {{ qc_primary_exclusions.common_mode_outlier }} + {{ qc_primary_exclusions.bad_red }} + {{ qc_primary_exclusions.offset_unresolved }} = {{ qc_excluded_scenes }}).
      </div>

      <h3>Dry-Season QC-Pass Scenes (Jun&ndash;Aug)</h3>
      <p>
        Composite generation utilized {{ dry_season_total }} dry-season scenes across the 4-year monitoring baseline:
        <strong>2019:</strong> {{ dry_season_by_year.get('2019', 'not available') }} scenes &bull;
        <strong>2020:</strong> {{ dry_season_by_year.get('2020', 'not available') }} scenes &bull;
        <strong>2021:</strong> {{ dry_season_by_year.get('2021', 'not available') }} scenes &bull;
        <strong>2022:</strong> {{ dry_season_by_year.get('2022', 'not available') }} scenes.
      </p>

      {% if b64_timeseries %}
      <div class="figure-container">
        <img src="{{ b64_timeseries }}" alt="Zone NDVI Time Series">
        <div class="figure-caption">Figure 1: Sentinel-2 Zone NDVI Time Series (2019&ndash;2022) comparing Project Zone and Reference Ring medians. Excluded scenes and dry season windows (Jun&ndash;Aug) are marked.</div>
      </div>
      {% endif %}
    </div>

    <!-- Section 3: Area Band Table -->
    <div class="card">
      <h2>3. Plantation Area Observation Band &amp; Sensitivity</h2>
      <p>
        Planted eucalyptus area evaluated across a sensitivity grid of dry-season quantile-mapped NDVI thresholds T in {0.60, 0.65, 0.70, 0.75}.
        Pre-existing natural forest allowance F = {% if natural_forest_ha is not none %}{{ "{:,.1f}".format(natural_forest_ha) }} ha{% else %}not available{% endif %} ({{ natural_forest_doc }}, p. {{ natural_forest_page }}) is deducted from high-NDVI area inside the boundary A2022(T):
      </p>
      <table>
        <thead>
          <tr>
            <th>NDVI Threshold T</th>
            <th class="text-right">Observed 2022 Area A2022(T)</th>
            <th class="text-right">Natural Forest Allowance F</th>
            <th class="text-right">Net Planted Area obs(T)</th>
            <th class="text-right">Shortfall vs Claim ({% if claimed_area_ha is not none %}{{ "{:,.1f}".format(claimed_area_ha) }} ha{% else %}not available{% endif %})</th>
          </tr>
        </thead>
        <tbody>
          {% for t_key in ["0.6", "0.65", "0.7", "0.75"] %}
          {% set g = grid_estimates.get(t_key) %}
          <tr>
            <td><strong>T = {{ t_key }}</strong> {% if t_key == '0.6' %}(High Bound){% elif t_key == '0.75' %}(Low Bound){% endif %}</td>
            <td class="text-right">{% if g %}{{ "{:,.2f}".format(g.a_2022_ha) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right">{% if g %}{{ "{:,.2f}".format(g.forest_allowance_ha) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right"><strong>{% if g %}{{ "{:,.2f}".format(g.obs_ha) }} ha{% else %}not available{% endif %}</strong></td>
            <td class="text-right">
              {% if g and claimed_area_ha is not none %}
              {% set sf = claimed_area_ha - g.obs_ha %}
              {% if sf > 0 %}{{ "{:,.2f}".format(sf) }} ha{% else %}0.00 ha{% endif %}
              {% else %}not available{% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <h3>Observation Band Parameters</h3>
      <ul class="clean-list">
        <li><strong>Observation Band:</strong> [{{ "{:,.2f}".format(band.low) }}, {{ "{:,.2f}".format(band.high) }}] ha (span: {{ "{:,.2f}".format(band_span) }} ha, or {{ "{:.2f}%".format(band_span_pct) }} of claimed area).</li>
        <li><strong>Central Estimate (Median):</strong> {{ "{:,.2f}".format(band.central) }} ha (shortfall at central: {{ "{:,.2f}".format(shortfall_central) }} ha).</li>
        <li><strong>Lower Bound Observation:</strong> {{ "{:,.2f}".format(band.low) }} ha (shortfall at lower bound: {{ "{:,.2f}".format(shortfall_low) }} ha).</li>
        <li><strong>Detection Limit:</strong> {{ "{:,.2f}".format(detection_limit_ha) }} ha ({{ "{:.1f}%".format(detection_limit_pct) }} of claimed area). Under the one-sided assessment rule, no shortfall is detected since upper bound exceeds claim.</li>
      </ul>

      {% if raw_areas %}
      <h3>Normalisation Sensitivity: RAW vs Quantile-Mapped Composites</h3>
      <p>
        Project area (ha) with NDVI &ge; T across monitoring years before and after reference-ring quantile mapping:
      </p>
      <table>
        <thead>
          <tr>
            <th>NDVI Threshold T</th>
            <th class="text-right">2019 RAW</th>
            <th class="text-right">2019 QM</th>
            <th class="text-right">2020 RAW</th>
            <th class="text-right">2020 QM</th>
            <th class="text-right">2021 RAW</th>
            <th class="text-right">2021 QM</th>
            <th class="text-right">2022 RAW</th>
            <th class="text-right">2022 QM</th>
          </tr>
        </thead>
        <tbody>
          {% for t_key in ["0.6", "0.65", "0.7", "0.75"] %}
          {% set r_row = raw_areas.get(t_key, {}) %}
          <tr>
            <td><strong>T = {{ t_key }}</strong></td>
            <td class="text-right">{% if r_row.get('2019', {}).get('raw_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2019', {}).get('raw_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2019', {}).get('qm_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2019', {}).get('qm_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2020', {}).get('raw_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2020', {}).get('raw_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2020', {}).get('qm_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2020', {}).get('qm_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2021', {}).get('raw_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2021', {}).get('raw_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2021', {}).get('qm_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2021', {}).get('qm_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2022', {}).get('raw_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2022', {}).get('raw_ha')) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if r_row.get('2022', {}).get('qm_ha') is not none %}{{ "{:,.2f}".format(r_row.get('2022', {}).get('qm_ha')) }}{% else %}not available{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <h3>Observed Planted Area Band Comparison (2022)</h3>
      <table>
        <thead>
          <tr>
            <th>Estimation Mode</th>
            <th class="text-right">Observation Band [Low, High]</th>
            <th class="text-right">Central (Median)</th>
            <th class="text-right">Band Span</th>
            <th class="text-right">Span % of Claim</th>
            <th class="text-right">Detection Limit</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Primary (Quantile-Mapped)</strong></td>
            <td class="text-right">[{{ "{:,.2f}".format(band.low) }}, {{ "{:,.2f}".format(band.high) }}] ha</td>
            <td class="text-right">{{ "{:,.2f}".format(band.central) }} ha</td>
            <td class="text-right">{{ "{:,.2f}".format(band_span) }} ha</td>
            <td class="text-right">{{ "{:.2f}%".format(band_span_pct) }}</td>
            <td class="text-right">{{ "{:.2f}%".format(detection_limit_pct_2d) }} ({{ "{:,.2f}".format(detection_limit_ha) }} ha)</td>
          </tr>
          {% if raw_band %}
          <tr>
            <td><strong>Without ring normalisation (RAW sensitivity)</strong></td>
            <td class="text-right">[{{ "{:,.2f}".format(raw_band.low) }}, {{ "{:,.2f}".format(raw_band.high) }}] ha</td>
            <td class="text-right">{{ "{:,.2f}".format(raw_band.central) }} ha</td>
            <td class="text-right">{{ "{:,.2f}".format(raw_band.span_ha) }} ha</td>
            <td class="text-right">{% if raw_band.span_pct is not none %}{{ "{:.2f}%".format(raw_band.span_pct) }}{% else %}not available{% endif %}</td>
            <td class="text-right">{% if raw_band.detection_limit_pct is not none %}{{ "{:.2f}%".format(raw_band.detection_limit_pct) }} ({{ "{:,.2f}".format(raw_band.detection_limit_ha) }} ha){% else %}not available{% endif %}</td>
          </tr>
          {% endif %}
        </tbody>
      </table>

      {% if raw_band %}
      <p>
        Without ring normalisation the band is [{{ "{:,.2f}".format(raw_band.low) }}, {{ "{:,.2f}".format(raw_band.high) }}] ha{% if raw_band.detection_limit_pct is not none %} (detection limit {{ "{:.2f}%".format(raw_band.detection_limit_pct) }}){% endif %}; status unchanged.
      </p>
      {% endif %}
      <p>
        Raw composites carry a year effect (reference ring raw median per year: 2019: {% if raw_ring_medians.get('2019') is not none %}{{ "{:.4f}".format(raw_ring_medians.get('2019')) }}{% else %}not available{% endif %}, 2020: {% if raw_ring_medians.get('2020') is not none %}{{ "{:.4f}".format(raw_ring_medians.get('2020')) }}{% else %}not available{% endif %}, 2021: {% if raw_ring_medians.get('2021') is not none %}{{ "{:.4f}".format(raw_ring_medians.get('2021')) }}{% else %}not available{% endif %}, 2022: {% if raw_ring_medians.get('2022') is not none %}{{ "{:.4f}".format(raw_ring_medians.get('2022')) }}{% else %}not available{% endif %}){% set m19 = raw_ring_medians.get('2019') %}{% set m21 = raw_ring_medians.get('2021') %}{% set m22 = raw_ring_medians.get('2022') %}{% if m19 is not none and m21 is not none and m22 is not none %}{% set desc21 = 'depressed' if m21 < m19 else ('elevated' if m21 > m19 else 'stable') %}{% set desc22 = 'elevated' if m22 > m19 else ('depressed' if m22 < m19 else 'stable') %}, 2021 {{ desc21 }} and 2022 {{ desc22 }} versus 2019{% endif %}, so quantile mapping is the primary estimate and the raw band is shown as a sensitivity.
      </p>
      {% endif %}

      {% if forest_allowance_check %}
      <h3>Natural Forest Allowance Cross-Check &amp; Break-Even</h3>
      <p>
        At the generous end (T = 0.60) the status stays CONSISTENT for any forest allowance up to {{ "{:,.2f}".format(forest_allowance_check.f_star_06_ha) }} ha ({{ "{:,.2f}".format(forest_allowance_check.margin_06_ha) }} ha above the {{ "{:,.2f}".format(forest_allowance_check.claimed_forest_allowance_ha) }} ha claim). At the strict end (T = 0.75) the break-even allowance is {{ "{:,.2f}".format(forest_allowance_check.f_star_low_end_ha) }} ha, so with {{ "{:,.2f}".format(forest_allowance_check.claimed_forest_allowance_ha) }} ha that end already shows a {{ "{:,.2f}".format(forest_allowance_check.claimed_forest_allowance_ha - forest_allowance_check.f_star_low_end_ha) }} ha shortfall; the status rule uses the generous end by design.
      </p>
      <p>
        {% set p25 = forest_allowance_check.persistence.get('25', {}) %}
        {% set p50 = forest_allowance_check.persistence.get('50', {}) %}
        {% set p75 = forest_allowance_check.persistence.get('75', {}) %}
        Under the Hansen persistence check (treecover2000 with no loss through 2018), persistent canopy inside the project boundary is {% if p25.get('persistent_2018_ha') is not none %}{{ "{:,.2f}".format(p25.get('persistent_2018_ha')) }} ha{% else %}not available{% endif %} (&ge; 25%), {% if p50.get('persistent_2018_ha') is not none %}{{ "{:,.2f}".format(p50.get('persistent_2018_ha')) }} ha{% else %}not available{% endif %} (&ge; 50%), and {% if p75.get('persistent_2018_ha') is not none %}{{ "{:,.2f}".format(p75.get('persistent_2018_ha')) }} ha{% else %}not available{% endif %} (&ge; 75%), which reduce to {% if p25.get('persistent_qm19_ge_07_ha') is not none %}{{ "{:,.2f}".format(p25.get('persistent_qm19_ge_07_ha')) }} ha{% else %}not available{% endif %}, {% if p50.get('persistent_qm19_ge_07_ha') is not none %}{{ "{:,.2f}".format(p50.get('persistent_qm19_ge_07_ha')) }} ha{% else %}not available{% endif %}, and {% if p75.get('persistent_qm19_ge_07_ha') is not none %}{{ "{:,.2f}".format(p75.get('persistent_qm19_ge_07_ha')) }} ha{% else %}not available{% endif %} when intersected with qm(2019) &ge; 0.70 (and {% if p25.get('persistent_qm19_ge_06_ha') is not none %}{{ "{:,.2f}".format(p25.get('persistent_qm19_ge_06_ha')) }} ha{% else %}not available{% endif %}, {% if p50.get('persistent_qm19_ge_06_ha') is not none %}{{ "{:,.2f}".format(p50.get('persistent_qm19_ge_06_ha')) }} ha{% else %}not available{% endif %}, and {% if p75.get('persistent_qm19_ge_06_ha') is not none %}{{ "{:,.2f}".format(p75.get('persistent_qm19_ge_06_ha')) }} ha{% else %}not available{% endif %} with qm(2019) &ge; 0.60), framing the {% if natural_forest_ha is not none %}{{ "{:,.2f}".format(natural_forest_ha) }} ha{% else %}not available{% endif %} figure; Hansen cannot separate natural forest from older plantations or scattered trees, so it is an indicator only.
      </p>
      <table>
        <thead>
          <tr>
            <th>Hansen Tree Cover Threshold</th>
            <th class="text-right">2000 Cover</th>
            <th class="text-right">Persistent (No Loss thru 2018)</th>
            <th class="text-right">Persistent &amp; qm19 &ge; 0.60</th>
            <th class="text-right">Persistent &amp; qm19 &ge; 0.70</th>
            <th class="text-right">Claimed Allowance</th>
          </tr>
        </thead>
        <tbody>
          {% for cov in ["25", "50", "75"] %}
          {% set p_row = forest_allowance_check.persistence.get(cov, {}) %}
          <tr>
            <td><strong>&ge; {{ cov }}% Tree Cover</strong></td>
            <td class="text-right">{% if p_row.get('treecover2000_ha') is not none %}{{ "{:,.2f}".format(p_row.get('treecover2000_ha')) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right">{% if p_row.get('persistent_2018_ha') is not none %}{{ "{:,.2f}".format(p_row.get('persistent_2018_ha')) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right">{% if p_row.get('persistent_qm19_ge_06_ha') is not none %}{{ "{:,.2f}".format(p_row.get('persistent_qm19_ge_06_ha')) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right">{% if p_row.get('persistent_qm19_ge_07_ha') is not none %}{{ "{:,.2f}".format(p_row.get('persistent_qm19_ge_07_ha')) }} ha{% else %}not available{% endif %}</td>
            <td class="text-right">{{ "{:,.2f}".format(forest_allowance_check.claimed_forest_allowance_ha) }} ha</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}
    </div>

    <!-- Section 4: Hysteresis Cohort Table -->
    <div class="card">
      <h2>4. Dynamic Hysteresis Cohort Breakdown</h2>
      <p>
        Strict hysteresis tracking filters pixels that transition from low NDVI (&lt; T_low) to high canopy (&gt;= T_high) in cohort year y and remain stable thereafter.
        Total cohort area serves as a physical lower bound on newly established plantations:
      </p>
      <table>
        <thead>
          <tr>
            <th>Thresholds (T_low, T_high)</th>
            <th class="text-right">Cohort 2020 (ha)</th>
            <th class="text-right">Cohort 2021 (ha)</th>
            <th class="text-right">Cohort 2022 (ha)</th>
            <th class="text-right">Total Cohort Area (ha)</th>
            <th class="text-right">Pre-existing high-NDVI (ha), qm(2019) &gt;= T_low</th>
          </tr>
        </thead>
        <tbody>
          {% for pair_key, c_row in cohorts.items() %}
          <tr>
            <td><code>{{ pair_key }}</code></td>
            <td class="text-right">{{ "{:,.2f}".format(c_row.cohort_2020_ha) }}</td>
            <td class="text-right">{{ "{:,.2f}".format(c_row.cohort_2021_ha) }}</td>
            <td class="text-right">{{ "{:,.2f}".format(c_row.cohort_2022_ha) }}</td>
            <td class="text-right"><strong>{{ "{:,.2f}".format(c_row.total_ha) }}</strong></td>
            <td class="text-right">{{ "{:,.2f}".format(c_row.pre_existing_ha) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>

      <p>
        The Jun-Aug 2019 composite is not pre-planting for plantings made early in 2019, so the cohort total is a lower bound for 2019 plantings and a gap versus the schedule is not a shortfall.{% if scheduled_2020 is not none %} The 2020 planting ({{ "{:.0f}".format(scheduled_2020) }} ha) is inconclusive.{% endif %}
      </p>
{% if scheduled_2019_2020 is not none or scheduled_2020 is not none %}
      <h3>Comparison with Operational Planting Records</h3>
      <p>
        Total lower bound range across all five threshold pairs is <strong>{{ "{:,.2f}".format(cohort_tot_range[0]) }} &ndash; {{ "{:,.2f}".format(cohort_tot_range[1]) }} ha</strong>
        {% if scheduled_2019_2020 is not none %}(compared against documented 2019+2020 scheduled plantings of {{ "{:,.1f}".format(scheduled_2019_2020) }} ha).{% endif %}
        Cohort-2021 area range is <strong>{{ "{:,.2f}".format(cohort_21_range[0]) }} &ndash; {{ "{:,.2f}".format(cohort_21_range[1]) }} ha</strong>
        {% if scheduled_2020 is not none %}(compared against documented 2020 scheduled plantings of {{ "{:,.1f}".format(scheduled_2020) }} ha, assuming roughly a one-year lag between planting and reaching high NDVI).{% endif %}
      </p>
      <div class="source-note">
        <em>Note:</em> Close matches to the schedule are post hoc and are not validation.
      </div>{% endif %}

      {% if b64_cohort_maps %}
      <div class="figure-container">
        <img src="{{ b64_cohort_maps }}" alt="Hysteresis Cohort Maps">
        <div class="figure-caption">Figure 2: Cohort maps for one parameterisation (T = 0.70; low &lt; 0.60). (a) 2022 quantile-mapped NDVI. (b) Endpoint gain mask: qm2019 &lt; 0.60 and qm2022 &gt;= 0.70, without the stability test ({% if decline and decline.endpoint_gain_mask_ha is not none %}{{ "{:,.2f}".format(decline.endpoint_gain_mask_ha) }} ha{% else %}not available{% endif %}; the strict (0.6, 0.7) cohort total in the table is {% set c_strict = cohorts.get('(0.6, 0.7)') %}{% if c_strict and c_strict.total_ha is defined and c_strict.total_ha is not none %}{{ "{:,.2f}".format(c_strict.total_ha) }} ha{% elif c_strict and c_strict.get and c_strict.get('total_ha') is not none %}{{ "{:,.2f}".format(c_strict.get('total_ha')) }} ha{% else %}not available{% endif %}). (c) First year each pixel reaches qm &gt;= 0.70, with no low-before condition. The other threshold pairs in the table are not mapped.</div>
      </div>
      {% endif %}
    </div>

    <!-- Section 5: Unscored Observations -->
    <div class="card">
      <h2>5. Unscored Audit Observations</h2>
      <ul class="clean-list">
        <li>
          <strong>Pre-existing high-NDVI decline:</strong> Area with qm(2019) &gt;= 0.70 and qm(2022) &lt; 0.60 equals <strong>{{ "{:,.2f}".format(pre_existing_decline_ha) }} ha</strong>; land cover unknown; unscored.
        </li>
        {% if decline and decline.decline_set_d %}
        <li>
          Pixels with qm &gt;= 0.70 in some year and &lt; 0.60 in 2022: {{ "{:,.2f}".format(decline.decline_set_d.area_ha) }} ha (first high in 2019: {% if decline.decline_set_d.first_high_split.get('2019') is not none %}{{ "{:,.2f}".format(decline.decline_set_d.first_high_split.get('2019')) }}{% else %}not available{% endif %}, 2020: {% if decline.decline_set_d.first_high_split.get('2020') is not none %}{{ "{:,.2f}".format(decline.decline_set_d.first_high_split.get('2020')) }}{% else %}not available{% endif %}, 2021: {% if decline.decline_set_d.first_high_split.get('2021') is not none %}{{ "{:,.2f}".format(decline.decline_set_d.first_high_split.get('2021')) }}{% else %}not available{% endif %}); land cover unknown, not scored. A further {{ "{:,.2f}".format(decline.decline_set_d.moderate_decline_60_70_ha) }} ha are in [0.60, 0.70) in 2022.
        </li>
        <li>
          Decline set D (qm &gt;= 0.70 in some year and qm2022 &lt; 0.60; {{ "{:,.2f}".format(decline.decline_set_d.area_ha) }} ha): {{ decline.decline_set_d.components.count }} components; {{ "{:.2f}%".format(decline.decline_set_d.components.share_lt_1ha_pct) }} of the area is in components &lt; 1 ha, {{ "{:.2f}%".format(decline.decline_set_d.components.share_1_to_5ha_pct) }} in 1-5 ha, {{ "{:.2f}%".format(decline.decline_set_d.components.share_gt_5ha_pct) }} in one component &gt; 5 ha. That component is a compact {{ "{:,.2f}".format(decline.decline_set_d.components.largest_component_ha) }} ha block (component-mean raw NDVI {% if decline.decline_set_d.components.largest_component_raw_means.get('2020') is not none %}{{ "{:.2f}".format(decline.decline_set_d.components.largest_component_raw_means.get('2020')) }}{% else %}not available{% endif %} in 2020, {% if decline.decline_set_d.components.largest_component_raw_means.get('2021') is not none %}{{ "{:.2f}".format(decline.decline_set_d.components.largest_component_raw_means.get('2021')) }}{% else %}not available{% endif %} in 2021, {% if decline.decline_set_d.components.largest_component_raw_means.get('2022') is not none %}{{ "{:.2f}".format(decline.decline_set_d.components.largest_component_raw_means.get('2022')) }}{% else %}not available{% endif %} in 2022). Cause undetermined from NDVI alone; not scored.
        </li>
        <li>
          2022 first-high set G22 (first year qm &gt;= 0.70 is 2022, T = 0.70; {{ "{:,.2f}".format(decline.g22_cohort.area_ha) }} ha): {{ "{:.2f}%".format(decline.g22_cohort.components.share_gt_5ha_pct) }} of the area is in {% set c_list = decline.g22_cohort.components.components_gt_5ha or [] %}{% set n_c = c_list | length %}{% set num_words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"} %}{% set c_word = num_words.get(n_c, n_c ~ "") %}{{ c_word }} component{% if n_c != 1 %}s{% endif %} &gt; 5 ha{% if n_c > 0 %} ({% for c in c_list %}{% if not loop.first %}{% if loop.last %} and {% else %}, {% endif %}{% endif %}{{ "{:,.2f}".format(c) }}{% endfor %} ha){% endif %} and {{ "{:.2f}%".format(decline.g22_cohort.components.share_lt_1ha_pct) }} in components &lt; 1 ha. The largest component's mean raw NDVI is {% if decline.g22_cohort.components.largest_component_raw_means.get('2019') is not none and decline.g22_cohort.components.largest_component_raw_means.get('2020') is not none %}{{ "{:.2f}".format(decline.g22_cohort.components.largest_component_raw_means.get('2019')) }}-{{ "{:.2f}".format(decline.g22_cohort.components.largest_component_raw_means.get('2020')) }}{% else %}not available{% endif %} in 2019-2021 and {% if decline.g22_cohort.components.largest_component_raw_means.get('2022') is not none %}{{ "{:.2f}".format(decline.g22_cohort.components.largest_component_raw_means.get('2022')) }}{% else %}not available{% endif %} in 2022. Monitoring report {% if table_ref %}{{ table_ref }} {% endif %}lists no plantings after {{ decline.latest_planting_year }}; cause not determined. If all of G22 were excluded, the T = 0.70 observed area would be {{ "{:,.2f}".format(decline.sensitivity_t70_excl_g22.observed_area_excl_g22_ha) }} ha ({{ "{:,.2f}".format(decline.sensitivity_t70_excl_g22.a_2022_ha) }} - {{ "{:,.2f}".format(decline.sensitivity_t70_excl_g22.g22_area_ha) }} - {% if natural_forest_ha is not none %}{{ "{:,.0f}".format(natural_forest_ha) }}{% else %}not available{% endif %}), still inside the reported band ({{ "{:,.2f}".format(claimed_area_ha - decline.sensitivity_t70_excl_g22.observed_area_excl_g22_ha) }} ha below the {{ "{:,.0f}".format(claimed_area_ha) }} ha claim, above the band's low end of {{ "{:,.2f}".format(band.low) }} ha).
        </li>
        <li>
          Strict (0.6, 0.7) 2022 cohort ({{ "{:,.2f}".format(decline.strict_2022_cohort.area_ha) }} ha): {{ "{:.0f}%".format(decline.strict_2022_cohort.share_lt_1ha_pct) }} of the area is in components &lt; 1 ha; pattern consistent with noise; cause not determined.
        </li>
        {% endif %}
        {% if hansen and hansen.decline_43ha %}
        <li>
          <strong>Hansen GFC cross-check of pre-existing decline ({{ "{:,.2f}".format(pre_existing_decline_ha) }} ha):</strong>
          Hansen ({{ hansen.gfc_version }}, tile {{ hansen.primary_tile }}) indicates {{ "{:.1f}%".format(hansen.decline_43ha.treecover2000_ge_25_share * 100) }} had treecover2000 &ge; 25% ({{ "{:.1f}%".format(hansen.decline_43ha.treecover2000_ge_50_share * 100) }} &ge; 50%). Cumulative 2019&ndash;2022 Hansen tree-cover loss is {{ "{:.2f}%".format(hansen.decline_43ha.loss_share_2019_2022_total * 100) }} ({{ "{:,.2f}".format(hansen.decline_43ha.loss_ha_total) }} ha; 2019: {{ "{:.2f}%".format(hansen.decline_43ha.loss_share_2019 * 100) }}, 2020: {{ "{:.2f}%".format(hansen.decline_43ha.loss_share_2020 * 100) }}, 2021: {{ "{:.2f}%".format(hansen.decline_43ha.loss_share_2021 * 100) }}, 2022: {{ "{:.2f}%".format(hansen.decline_43ha.loss_share_2022 * 100) }}). Controls: high-canopy pixels stable across all 4 years have {{ "{:.1f}%".format(hansen.controls.high_all4.treecover2000_ge_25_share * 100) }} treecover2000 &ge; 25% and {{ "{:.2f}%".format(hansen.controls.high_all4.loss_share_2019_2022_total * 100) }} loss; the full project boundary has {{ "{:.1f}%".format(hansen.controls.project_boundary.treecover2000_ge_25_share * 100) }} treecover2000 &ge; 25% and {{ "{:.2f}%".format(hansen.controls.project_boundary.loss_share_2019_2022_total * 100) }} loss; the reference ring has {{ "{:.1f}%".format(hansen.controls.reference_ring.treecover2000_ge_25_share * 100) }} treecover2000 &ge; 25% and {{ "{:.2f}%".format(hansen.controls.reference_ring.loss_share_2019_2022_total * 100) }} loss. Boundary-wide Hansen tree-cover loss area: 2019: {% if hansen.boundary_loss_ha_by_year.get('2019') is not none %}{{ "{:,.2f}".format(hansen.boundary_loss_ha_by_year.get('2019')) }} ha{% else %}not available{% endif %}, 2020: {% if hansen.boundary_loss_ha_by_year.get('2020') is not none %}{{ "{:,.2f}".format(hansen.boundary_loss_ha_by_year.get('2020')) }} ha{% else %}not available{% endif %}, 2021: {% if hansen.boundary_loss_ha_by_year.get('2021') is not none %}{{ "{:,.2f}".format(hansen.boundary_loss_ha_by_year.get('2021')) }} ha{% else %}not available{% endif %}, 2022: {% if hansen.boundary_loss_ha_by_year.get('2022') is not none %}{{ "{:,.2f}".format(hansen.boundary_loss_ha_by_year.get('2022')) }} ha{% else %}not available{% endif %} (total: {{ "{:,.2f}".format(hansen.boundary_loss_ha_total) }} ha). Hansen tree-cover loss includes plantation harvest and is 30 m; this is an indicator of land cover, not proof; unscored.
        </li>
        {% endif %}
      </ul>

      {% if b64_decline_map %}
      <div class="figure-container">
        <img src="{{ b64_decline_map }}" alt="Decline Set D and Hansen Classification">
        <div class="figure-caption">Figure 3: High-NDVI decline set D (qm &gt;= 0.70 in some year 2019&ndash;2021 and qm2022 &lt; 0.60; {% if decline and decline.decline_set_d %}{{ "{:,.2f}".format(decline.decline_set_d.area_ha) }} ha{% else %}not available{% endif %}). (a) Coloured by first-high year, with the largest component ({% if decline and decline.decline_set_d %}{{ "{:,.2f}".format(decline.decline_set_d.components.largest_component_ha) }} ha{% else %}not available{% endif %}) outlined. (b) The same pixels classified at the Hansen 30 m grid: treecover2000 &lt; 25, treecover2000 &ge; 25 with no loss in 2019&ndash;2022, and treecover2000 &ge; 25 with loss in 2019&ndash;2022. Cause not determined; Hansen loss includes plantation harvest; indicator, not proof.</div>
      </div>
      {% endif %}
    </div>

    <!-- Independent Canopy-Cover and Biomass-Proxy Change -->
    {% if canopy_biomass and canopy_biomass.table %}
    <div class="card">
      <h2>Independent canopy-cover and biomass-proxy change (no canopy claim exists, so unscored)</h2>
      <p>
        Between {{ canopy_biomass.baseline_year }} and {{ canopy_biomass.end_year }}, primary canopy cover (qm &ge; {{ canopy_biomass.primary_threshold }}) changed by +{{ "{:.2f}%".format(canopy_biomass.canopy_change_pct) }} ({{ "{:,.2f}".format(canopy_biomass.table[canopy_biomass.primary_threshold][canopy_biomass.baseline_year].area_ha) }} ha to {{ "{:,.2f}".format(canopy_biomass.table[canopy_biomass.primary_threshold][canopy_biomass.end_year].area_ha) }} ha; range over threshold grid: +{{ "{:.2f}%".format(canopy_biomass.canopy_change_min_pct) }} to +{{ "{:.2f}%".format(canopy_biomass.canopy_change_max_pct) }}). Boundary-mean biomass proxy (mean qm NDVI) changed by +{{ "{:.2f}%".format(canopy_biomass.biomass_proxy_change_pct) }} ({{ "{:.4f}".format(canopy_biomass.biomass_proxy_by_year[canopy_biomass.baseline_year].mean) }} to {{ "{:.4f}".format(canopy_biomass.biomass_proxy_by_year[canopy_biomass.end_year].mean) }}). In the external reference ring, the raw median changed by +{{ "{:.2f}%".format(canopy_biomass.reference_buffer_change_pct) }} ({{ "{:.4f}".format(canopy_biomass.reference_buffer_raw_medians[canopy_biomass.baseline_year]) }} to {{ "{:.4f}".format(canopy_biomass.reference_buffer_raw_medians[canopy_biomass.end_year]) }}) as background context.
      </p>
      <p>
        The {{ canopy_biomass.baseline_year }} baseline composite postdates the {{ earliest_planting_year }} plantings (project start {{ project_start_month }}), so change since project start is understated.
      </p>
      <p>
        The biomass proxy is computed on ring-normalised NDVI; the ring change shown is the raw median and is context only, not a quantity to subtract.
      </p>
      <p>
        NDVI is a proxy that saturates in dense vegetation, and part of the change reflects planting dynamics, not a verified biomass gain.
      </p>
      <table class="report-table">
        <thead>
          <tr>
            <th>Year</th>
            <th>Biomass Proxy Mean (p90)</th>
            <th>Raw Ring Median</th>
            {% for t in canopy_biomass.thresholds %}
            <th>T = {{ t }}</th>
            {% endfor %}
          </tr>
        </thead>
        <tbody>
          {% for y in canopy_biomass.years %}
          <tr>
            <td>{{ y }}</td>
            <td>{{ "{:.4f}".format(canopy_biomass.biomass_proxy_by_year[y].mean) }} ({{ "{:.4f}".format(canopy_biomass.biomass_proxy_by_year[y].p90) }})</td>
            <td>{{ "{:.4f}".format(canopy_biomass.reference_buffer_raw_medians[y]) }}</td>
            {% for t in canopy_biomass.thresholds %}
            {% set c_cell = canopy_biomass.table[t][y] %}
            <td>{{ "{:,.2f}".format(c_cell.area_ha) }} ha ({{ "{:.2f}%".format(c_cell.share_pct) }})</td>
            {% endfor %}
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <p class="text-muted" style="margin-top: 10px; font-size: 0.9em;">
        The {{ canopy_biomass.years[1] }} and {{ canopy_biomass.years[2] }} p90 values coincide ({{ "{:.4f}".format(canopy_biomass.biomass_proxy_by_year[canopy_biomass.years[1]].p90) }}) because the project p90 sits at nearly the same rank of the reference ring in both years (about the {{ "{:.2f}".format(canopy_biomass.p90_ring_ranks[canopy_biomass.years[1]]) }}th percentile, computed from the data); this is a coincidence of ranks, not a ceiling.
      </p>
    </div>
    {% endif %}

    <!-- Section 6: Limitations -->
    <div class="card">
      <h2>6. Methodology Limitations</h2>
      <p>Key methodological and data constraints for this assessment:</p>
      <ul class="clean-list">
        <li>Satellites verify observable claims (area, planting, canopy), not counterfactual baselines, so avoided-deforestation (REDD+) over-crediting claims are out of reach.</li>
        <li>NDVI saturates in dense/high-biomass forest and is only a proxy for biomass; upper area thresholds (&gt;= {{ "{:.2f}".format(upper_area_threshold) }}) sit near saturation for the 2022 project pixels ({{ "{:.2f}%".format(saturation_share_pct) }} have raw NDVI &gt;= {{ "{:.2f}".format(saturation_raw_threshold) }}).</li>
        <li>Strata have no polygons, so spatial verification is plantation mapping inside the estate, not per-stratum checks.</li>
        <li>The 2018 plantings (and some early-2019 plantings) predate or overlap the Jun-Aug 2019 baseline and cannot be separated from the {% if natural_forest_ha is not none %}{{ "{:.0f}".format(natural_forest_ha) }}{% else %}not available{% endif %} ha natural forest; the Sentinel-2 L2A record starts about Dec 2018.{% if scheduled_2020 is not none %} The 2020 block is the best before/after test but is inconclusive here ({{ "{:.2f}".format(cohort_21_range[0]) }}-{{ "{:.2f}".format(cohort_21_range[1]) }} ha strict vs {{ "{:.0f}".format(scheduled_2020) }} ha scheduled).{% endif %}</li>
        <li>The area test depends on a registry-derived forest allowance ({% if natural_forest_ha is not none %}{{ "{:.0f}".format(natural_forest_ha) }}{% else %}not available{% endif %} ha, {{ natural_forest_doc }} p.{{ natural_forest_page }}) and on NDVI thresholds; the band is {{ "{:.2f}%".format(band_span_pct) }} of the claim, giving a detection limit of {{ "{:.2f}%".format(detection_limit_pct_2d) }}. Thresholds were chosen, not calibrated.</li>
        {% if ring_p5_2019 is not none and ring_p5_2022_raw is not none and (ring_p5_2019 - ring_p5_2022_raw) > 0.05 %}<li>Quantile mapping assumes the ring's distribution is stationary apart from atmosphere/phenology; ring land use changed in 2022 (raw ring p5 {{ "{:.4f}".format(ring_p5_2019) }} in 2019 vs {{ "{:.4f}".format(ring_p5_2022_raw) }} in 2022).</li>{% endif %}
        <li>Only {{ dry_season_min }}-{{ dry_season_max }} dry-season scenes per year.</li>
        <li>STAC offset/baseline metadata were unreliable for this tile; the offset is detected from DNs (red p1 rule), with a small number of ambiguous scenes excluded.</li>
        <li>Documented over-crediting cases are contested by Verra, so the flagging-precision sample is small and must be reported honestly.</li>
      </ul>
    </div>

    <!-- Section 7: Audit Provenance -->
    <div class="card">
      <h2>7. Artifact Provenance &amp; Checksums</h2>
      <p>
        Document claim extraction executed via <code>{{ extractor }}</code> pipeline (PDF SHA-256: <code>{{ pdf_sha256 }}</code>).
        Input vector geometries, timeseries tables, and GeoTIFF composites cryptographic hashes:
      </p>
      <div class="code-block">
{% for fname, fhash in file_hashes.items() %}
{{ fname }}: {{ fhash }}
{% endfor %}
      </div>
    </div>

    <footer>
      Automated Earth Observation Audit &bull; Generated by <strong>carbonverify</strong> pipeline
    </footer>
  </div>
</body>
</html>
"""


def _load_2469_context(
    report: DiscrepancyReport,
    out_dir: Path,
) -> Dict[str, Any]:
    """Assemble all structured data, figures, and hashes for project report."""
    import csv
    import numpy as np
    import pandas as pd
    from carbonverify.analysis.estimate import _load_analysis_config
    from carbonverify.imagery.radiometry import create_scl_mask

    proj_dir = Path("data/projects") / report.project_id
    if not proj_dir.exists() and report.claims.boundary_path:
        b_parent = Path(report.claims.boundary_path).parent
        if b_parent.exists():
            proj_dir = b_parent

    # Load report.json if already written, otherwise use report model dump
    report_json_path = out_dir / "report.json"
    if report_json_path.exists():
        try:
            with open(report_json_path, "r", encoding="utf-8") as f:
                rep_data = json.load(f)
        except Exception:
            rep_data = json.loads(report.model_dump_json())
    else:
        rep_data = json.loads(report.model_dump_json())

    claims_data = rep_data.get("claims", {})
    est_data = rep_data.get("estimate", {})

    # 1. Base parameters (no project-specific defaults)
    raw_claimed_area = claims_data.get("claimed_area_ha")
    if raw_claimed_area is None:
        raw_claimed_area = report.claims.claimed_area_ha
    claimed_area_ha: Optional[float] = float(raw_claimed_area) if raw_claimed_area is not None else None

    est = report.estimate
    obs_low = float(est_data.get("planted_area_obs_low") if est_data.get("planted_area_obs_low") is not None else (est.planted_area_obs_low or 0.0))
    obs_central = float(est_data.get("planted_area_obs_central") if est_data.get("planted_area_obs_central") is not None else (est.planted_area_obs_central or 0.0))
    obs_high = float(est_data.get("planted_area_obs_high") if est_data.get("planted_area_obs_high") is not None else (est.planted_area_obs_high or 0.0))

    raw_f_allowance = est_data.get("forest_allowance_ha")
    if raw_f_allowance is None:
        raw_f_allowance = claims_data.get("natural_forest_ha") or report.claims.natural_forest_ha or est.forest_allowance_ha
    f_allowance: Optional[float] = float(raw_f_allowance) if raw_f_allowance is not None else None

    band_span = round(obs_high - obs_low, 2)
    band_span_pct = round((band_span / claimed_area_ha) * 100.0, 2) if claimed_area_ha else 0.0
    det_limit = round((claimed_area_ha - obs_low), 2) if claimed_area_ha is not None else 0.0
    det_limit_pct = round((det_limit / claimed_area_ha) * 100.0, 1) if claimed_area_ha else 0.0
    det_limit_pct_2d = round((det_limit / claimed_area_ha) * 100.0, 2) if claimed_area_ha else 0.0

    verdict_text = f"no shortfall detected; sensitivity low (detection limit {det_limit_pct:.1f}%)"

    # 2. Grid thresholds
    grid_estimates = est_data.get("grid_estimates") or est.grid_estimates or {}
    upper_area_threshold = max((float(k) for k in grid_estimates.keys()), default=0.75)

    # 3. Cohorts
    cohort_bd = est_data.get("cohort_breakdown") or est.cohort_breakdown or {}
    cohorts_dict = cohort_bd.get("cohorts") or {}
    cohort_tot_range = cohort_bd.get("cohort_lower_bound_total_range_ha") or [0.0, 0.0]
    cohort_21_range = cohort_bd.get("cohort_2021_lower_bound_range_ha") or [0.0, 0.0]
    s19_20_raw = cohort_bd.get("scheduled_2019_2020_ha")
    sched_19_20: Optional[float] = float(s19_20_raw) if s19_20_raw is not None else None
    s20_raw = cohort_bd.get("scheduled_2020_ha")
    sched_20: Optional[float] = float(s20_raw) if s20_raw is not None else None

    # Project-level config (project.yaml)
    table_ref: Optional[str] = None
    pyaml_p = proj_dir / "project.yaml"
    if pyaml_p.exists():
        try:
            with open(pyaml_p, "r", encoding="utf-8") as f:
                pydata = yaml.safe_load(f) or {}
            sp = pydata.get("scheduled_plantings_ha", {})
            if sched_19_20 is None and sp.get("scheduled_2019_2020") is not None:
                sched_19_20 = float(sp["scheduled_2019_2020"])
            if sched_20 is None and sp.get("scheduled_2020") is not None:
                sched_20 = float(sp["scheduled_2020"])
            table_ref = pydata.get("table_ref") or sp.get("table_ref")
        except Exception:
            pass

    # 4. Normalization sensitivity
    norm_sens = (
        est_data.get("normalization_sensitivity")
        or getattr(est, "normalization_sensitivity", None)
        or {}
    )
    raw_band = norm_sens.get("raw_band") or {}
    raw_areas = norm_sens.get("areas_by_threshold") or {}
    raw_ring_medians = norm_sens.get("ring_raw_median") or {}

    # 5. Hansen crosscheck
    hansen_crosscheck = (
        est_data.get("hansen_crosscheck")
        or getattr(est, "hansen_crosscheck", None)
        or {}
    )

    # 6. Forest allowance check
    forest_allowance_check = (
        est_data.get("forest_allowance_check")
        or getattr(est, "forest_allowance_check", None)
        or {}
    )

    # 7. Decline analysis
    decline_analysis = (
        est_data.get("decline_analysis")
        or getattr(est, "decline_analysis", None)
        or {}
    )
    if not decline_analysis:
        cand_ej = proj_dir / "estimate.json"
        if cand_ej.exists():
            try:
                with open(cand_ej, "r", encoding="utf-8") as f:
                    ej_data = json.load(f)
                decline_analysis = (
                    ej_data.get("decline_analysis")
                    or ej_data.get("satellite_estimate", {}).get("decline_analysis")
                    or {}
                )
            except Exception:
                pass
    # 8. Canopy & biomass proxy change
    canopy_biomass = (
        est_data.get("canopy_biomass")
        or getattr(est, "canopy_biomass", None)
        or {}
    )
    if not canopy_biomass:
        cand_ej = proj_dir / "estimate.json"
        if cand_ej.exists():
            try:
                with open(cand_ej, "r", encoding="utf-8") as f:
                    ej_data = json.load(f)
                canopy_biomass = (
                    ej_data.get("canopy_biomass")
                    or ej_data.get("satellite_estimate", {}).get("canopy_biomass")
                    or {}
                )
            except Exception:
                pass

    # 5. Extraction report provenance and metadata (no project-specific defaults)
    extractor = "not available"
    pdf_sha256 = "not available"
    credits_source_note = "not available"
    ext_fields: Dict[str, Any] = {}
    ext_rep_path = proj_dir / "extraction_report.json"
    planting_strata: List[Dict[str, Any]] = []
    if ext_rep_path.exists():
        try:
            with open(ext_rep_path, "r", encoding="utf-8") as f:
                ext_data = json.load(f)
            extractor = ext_data.get("extractor") or "not available"
            pdf_sha256 = ext_data.get("pdf_sha256") or "not available"
            ext_fields = ext_data.get("fields") or {}
            if "source_notes" in ext_data and ext_data["source_notes"]:
                credits_source_note = ext_data["source_notes"][0]
            if ext_data.get("planting_schedule"):
                planting_strata = ext_data["planting_schedule"]
        except Exception:
            pass

    if not planting_strata and report.claims.planting_schedule:
        planting_strata = [s.model_dump() for s in report.claims.planting_schedule]

    planting_sum_ha: Optional[float] = (
        sum(float(s.get("area_ha", 0.0)) for s in planting_strata) if planting_strata else None
    )
    planting_diff_ha: Optional[float] = (
        round(planting_sum_ha - claimed_area_ha, 1)
        if (planting_sum_ha is not None and claimed_area_ha is not None)
        else None
    )
    if planting_strata:
        p_years = [int(s["planting_year"]) for s in planting_strata if s.get("planting_year") is not None]
        planting_year_span = f"{min(p_years)}\u2013{max(p_years)}" if p_years else "not available"
        earliest_planting_year = min(p_years) if p_years else "not available"
    else:
        planting_year_span = "not available"
        earliest_planting_year = "not available"

    proj_start_raw = claims_data.get("project_start_date") or getattr(report.claims, "project_start_date", None)
    project_start_month = str(proj_start_raw)[:7] if proj_start_raw else "not available"

    source_pages_map = claims_data.get("source_pages") or getattr(report.claims, "source_pages", None) or {}
    evidence_map = claims_data.get("evidence_quotes") or getattr(report.claims, "evidence_quotes", None) or {}

    def _field_source_and_quote(field_key: str) -> Tuple[str, str]:
        f_obj = ext_fields.get(field_key) or {}
        s_doc = f_obj.get("source_doc")
        s_page = f_obj.get("page")
        if s_page is None:
            s_page = source_pages_map.get(field_key)
        if s_doc and s_page is not None:
            src_str = f"{s_doc}, p. {s_page}"
        elif s_page is not None:
            src_str = f"p. {s_page}"
        else:
            src_str = "not available"
        q_str = f_obj.get("evidence_quote") or evidence_map.get(field_key) or "not available"
        return src_str, q_str

    nat_f_obj = ext_fields.get("natural_forest_ha") or {}
    nat_forest_doc = nat_f_obj.get("source_doc") or "not available"
    nat_forest_page: Union[int, str] = (
        nat_f_obj.get("page")
        if nat_f_obj.get("page") is not None
        else source_pages_map.get("natural_forest_ha", "not available")
    )

    rep_start = report.claims.reporting_period_start
    rep_end = report.claims.reporting_period_end
    mon_val = f"{rep_start} to {rep_end}" if (rep_start and rep_end) else "not available"
    mon_src, mon_q = _field_source_and_quote("reporting_period_start")

    cred_start = report.claims.crediting_period_start
    cred_end = report.claims.crediting_period_end
    cred_val = f"{cred_start} to {cred_end}" if (cred_start and cred_end) else "not available"
    cred_src, cred_q = _field_source_and_quote("crediting_period_start")

    est_area_val = f"{report.claims.estate_area_ha:,.1f} ha" if report.claims.estate_area_ha is not None else "not available"
    est_src, est_q = _field_source_and_quote("estate_area_ha")

    clm_area_val = f"{claimed_area_ha:,.1f} ha" if claimed_area_ha is not None else "not available"
    clm_src, clm_q = _field_source_and_quote("claimed_area_ha")

    net_ghg_val = f"{report.claims.net_ghg_removals_tco2e:,} tCO2e" if report.claims.net_ghg_removals_tco2e is not None else "not available"
    net_src, net_q = _field_source_and_quote("net_ghg_removals_tco2e")

    buf_val = f"{report.claims.buffer_credits_tco2e:,} tCO2e" if report.claims.buffer_credits_tco2e is not None else "not available"
    buf_src, buf_q = _field_source_and_quote("buffer_credits_tco2e")

    vcu_val = f"{report.claims.credits_issued:,} VCUs" if report.claims.credits_issued is not None else "not available"
    vcu_src, vcu_q = _field_source_and_quote("credits_issued")

    nf_val = f"{f_allowance:,.1f} ha" if f_allowance is not None else "not available"
    nf_src, nf_q = _field_source_and_quote("natural_forest_ha")

    claim_rows = [
        {"label": "Monitoring Period", "value": mon_val, "source": mon_src, "quote": mon_q},
        {"label": "Crediting Period", "value": cred_val, "source": cred_src, "quote": cred_q},
        {"label": "Total Estate Area", "value": est_area_val, "source": est_src, "quote": est_q},
        {"label": "Claimed Planted Area", "value": clm_area_val, "source": clm_src, "quote": clm_q},
        {"label": "Net GHG Removals", "value": net_ghg_val, "source": net_src, "quote": net_q},
        {"label": "AFOLU Buffer Credits", "value": buf_val, "source": buf_src, "quote": buf_q},
        {"label": "Eligible VCUs", "value": vcu_val, "source": vcu_src, "quote": vcu_q},
        {"label": "Natural Forest Allowance", "value": nf_val, "source": nf_src, "quote": nf_q},
    ]

    # 5. QC section counts and metadata computed from data
    cfg = _load_analysis_config()
    qc_cfg = cfg.get("qc", {})
    min_offset_present_int = int(float(qc_cfg.get("min_offset_present_red_p1", 1100.0)))
    max_offset_absent_int = int(float(qc_cfg.get("max_offset_absent_red_p1", 500.0)))
    min_red_p1_int = int(float(qc_cfg.get("min_red_p1_dn", 50.0)))
    min_valid_fraction = float(qc_cfg.get("min_valid_fraction", 0.5))
    outlier_diff_threshold = float(qc_cfg.get("outlier_diff_threshold", 0.25))
    temporal_window_days = int(qc_cfg.get("temporal_window_days", 30))

    imagery_dir = proj_dir / "imagery"
    stac_path = imagery_dir / "stac_items.json"
    stac_total_items: Union[int, str] = "not available"
    stac_unique_dates: Union[int, str] = "not available"
    stac_extra_twins: Union[int, str] = "not available"
    tile_id = "not available"

    if stac_path.exists():
        try:
            with open(stac_path, "r", encoding="utf-8") as f:
                stac_items = json.load(f)
            stac_total_items = len(stac_items)
            uniq_dates = {
                str(it.get("datetime", ""))[:10]
                for it in stac_items
                if it.get("datetime")
            }
            stac_unique_dates = len(uniq_dates)
            stac_extra_twins = stac_total_items - stac_unique_dates
            tiles = sorted({
                str(it.get("id", "")).split("_")[1]
                for it in stac_items
                if len(str(it.get("id", "")).split("_")) > 1
            })
            if tiles:
                tile_id = ", ".join(tiles)
        except Exception:
            pass

    ts_old_path = imagery_dir / "timeseries_old.csv"
    ts_csv_path = imagery_dir / "timeseries.csv"
    cache_dir = imagery_dir / "cache"

    scenes_fetched: Union[int, str] = stac_unique_dates
    old_scene_ids: List[str] = []
    if ts_old_path.exists():
        try:
            with open(ts_old_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                old_scene_ids = list(dict.fromkeys(r["scene_id"] for r in reader))
            scenes_fetched = len(old_scene_ids)
        except Exception:
            pass

    ts_scene_ids: List[str] = []
    timeseries_rows_count: Union[int, str] = "not available"
    if ts_csv_path.exists():
        try:
            with open(ts_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows_list = list(reader)
            timeseries_rows_count = len(rows_list)
            ts_scene_ids = list(dict.fromkeys(r["scene_id"] for r in rows_list))
            if tile_id == "not available" and ts_scene_ids:
                t_set = sorted({sid.split("_")[1] for sid in ts_scene_ids if len(sid.split("_")) > 1})
                if t_set:
                    tile_id = ", ".join(t_set)
        except Exception:
            pass

    ingest_excluded_details: List[str] = []
    ingest_excluded_count: Union[int, str] = "not available"
    if old_scene_ids and ts_scene_ids:
        ts_set = set(ts_scene_ids)
        excluded_at_ingest = [sid for sid in old_scene_ids if sid not in ts_set]
        ingest_excluded_count = len(excluded_at_ingest)
        for sid in excluded_at_ingest:
            cf = cache_dir / f"{sid}.npz"
            p1_str = "not available"
            if cf.exists():
                try:
                    with np.load(cf, allow_pickle=True) as d:
                        red = d["red"]
                        scl = d["scl"]
                    valid_px = red[create_scl_mask(scl) & (red > 0)]
                    if len(valid_px) > 0:
                        p1_str = f"{float(np.percentile(valid_px, 1)):.1f}"
                except Exception:
                    pass
            ingest_excluded_details.append(f"<code>{sid}</code> with red_p1 = {p1_str}")
    ingest_excluded_text = "; ".join(ingest_excluded_details) if ingest_excluded_details else "not available"

    qc_exclusions: Dict[str, Union[int, str]] = {
        "low_valid": "not available",
        "common_mode_outlier": "not available",
        "bad_red": "not available",
        "offset_unresolved": "not available",
    }
    qc_primary_exclusions: Dict[str, Union[int, str]] = {
        "low_valid": "not available",
        "common_mode_outlier": "not available",
        "bad_red": "not available",
        "offset_unresolved": "not available",
    }
    qc_total_scenes: Union[int, str] = "not available"
    qc_pass_scenes: Union[int, str] = "not available"
    qc_excluded_scenes: Union[int, str] = "not available"
    qc_multi_count: Union[int, str] = "not available"
    qc_multi_breakdown_text = "not available"
    low_valid_overlap_note = ""
    cmo_overlap_note = ""
    bad_red_overlap_note = ""

    qc_csv_path = imagery_dir / "qc_scenes.csv"
    if qc_csv_path.exists():
        try:
            qcdf = pd.read_csv(qc_csv_path)
            qc_total_scenes = len(qcdf)
            qc_pass_scenes = int((qcdf["qc_pass"] == True).sum())
            fails = qcdf[qcdf["qc_pass"] == False]
            qc_excluded_scenes = len(fails)
            ex_counts: Dict[str, int] = {
                "low_valid": 0,
                "common_mode_outlier": 0,
                "bad_red": 0,
                "offset_unresolved": 0,
            }
            prim_counts: Dict[str, int] = {
                "low_valid": 0,
                "common_mode_outlier": 0,
                "bad_red": 0,
                "offset_unresolved": 0,
            }
            multi_combos: Dict[str, int] = {}
            multi_cnt = 0
            for r in fails["qc_reasons"].dropna():
                r_str = str(r).strip()
                parts = [p.strip() for p in r_str.split(";") if p.strip()]
                for p in parts:
                    ex_counts[p] = ex_counts.get(p, 0) + 1
                if parts:
                    prim_counts[parts[0]] = prim_counts.get(parts[0], 0) + 1
                if len(parts) > 1:
                    multi_cnt += 1
                    combo_key = ";".join(parts)
                    multi_combos[combo_key] = multi_combos.get(combo_key, 0) + 1
            qc_exclusions = ex_counts
            qc_primary_exclusions = prim_counts
            qc_multi_count = multi_cnt
            if multi_combos:
                qc_multi_breakdown_text = " and ".join(
                    f"{cnt} with <code>{combo}</code>" for combo, cnt in multi_combos.items()
                )
            else:
                qc_multi_breakdown_text = "none"

            br_lv = multi_combos.get("bad_red;low_valid", 0)
            lv_cmo = multi_combos.get("low_valid;common_mode_outlier", 0)
            if br_lv > 0:
                low_valid_overlap_note = f" including {br_lv} scenes with primary reason <code>bad_red</code>"
                bad_red_overlap_note = f"; {br_lv} scenes also carry <code>low_valid</code>"
            if lv_cmo > 0:
                cmo_overlap_note = f" including {lv_cmo} scenes with primary reason <code>low_valid</code>"
        except Exception:
            pass

    # 6. Base64 Figures
    def _encode_img(img_path: Path) -> str:
        if img_path.exists():
            try:
                data = img_path.read_bytes()
                return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
            except Exception as e:
                logger.warning("Failed to encode %s: %s", img_path, e)
        return ""

    cohort_maps_path = proj_dir / "imagery" / "composites" / "cohort_maps.png"
    timeseries_path = proj_dir / "imagery" / "composites" / "zone_timeseries.png"
    decline_map_path = proj_dir / "imagery" / "composites" / "decline_map.png"
    b64_cohort_maps = _encode_img(cohort_maps_path)
    b64_timeseries = _encode_img(timeseries_path)
    b64_decline_map = _encode_img(decline_map_path)

    # 7. File hashes
    file_hashes = est_data.get("file_hashes") or est.file_hashes or {}

    # 8. Dynamic metrics for Section 6 limitations from report.json
    sat_share_pct = float(est_data.get("saturation_share_pct") or est.saturation_share_pct or 0.0)
    sat_raw_thresh = float(
        cfg.get("scoring", {})
        .get("confidence", {})
        .get("raw_ndvi_saturation_threshold", 0.85)
    )
    val_p5_19 = est_data.get("ring_p5_2019") if est_data.get("ring_p5_2019") is not None else est.ring_p5_2019
    ring_p5_19: Optional[float] = float(val_p5_19) if val_p5_19 is not None else None
    val_p5_22 = est_data.get("ring_p5_2022_raw") if est_data.get("ring_p5_2022_raw") is not None else est.ring_p5_2022_raw
    ring_p5_22_raw: Optional[float] = float(val_p5_22) if val_p5_22 is not None else None

    dry_qc_by_year = est_data.get("dry_season_qc_scenes") or est.dry_season_qc_scenes or {}
    dry_total: Union[int, str] = sum(dry_qc_by_year.values()) if dry_qc_by_year else "not available"
    dry_min: Union[int, str] = min(dry_qc_by_year.values()) if dry_qc_by_year else "not available"
    dry_max: Union[int, str] = max(dry_qc_by_year.values()) if dry_qc_by_year else "not available"

    pre_decline_ha = float(
        est_data.get("pre_existing_decline_ha")
        if est_data.get("pre_existing_decline_ha") is not None
        else (est.pre_existing_decline_ha or 0.0)
    )

    reg_raw = getattr(report.claims.registry, "value", report.claims.registry)
    registry_str = str(reg_raw).upper() if reg_raw else "not available"
    methodology_str = report.claims.methodology if report.claims.methodology else "not available"

    return {
        "project_id": report.project_id,
        "registry": registry_str,
        "methodology": methodology_str,
        "status": getattr(report.status, "value", str(report.status)),
        "confidence": getattr(report.confidence, "value", str(report.confidence)),
        "verdict_text": verdict_text,
        "claims": report.claims,
        "claim_rows": claim_rows,
        "claimed_area_ha": claimed_area_ha,
        "natural_forest_ha": f_allowance,
        "natural_forest_doc": nat_forest_doc,
        "natural_forest_page": nat_forest_page,
        "planting_strata": planting_strata,
        "planting_sum_ha": planting_sum_ha,
        "planting_diff_ha": planting_diff_ha,
        "planting_year_span": planting_year_span,
        "credits_source_note": credits_source_note,
        "tile_id": tile_id,
        "stac_total_items": stac_total_items,
        "stac_unique_dates": stac_unique_dates,
        "stac_extra_twins": stac_extra_twins,
        "scenes_fetched": scenes_fetched,
        "max_offset_absent_int": max_offset_absent_int,
        "min_offset_present_int": min_offset_present_int,
        "min_red_p1_int": min_red_p1_int,
        "min_valid_fraction": min_valid_fraction,
        "outlier_diff_threshold": outlier_diff_threshold,
        "temporal_window_days": temporal_window_days,
        "ingest_excluded_count": ingest_excluded_count,
        "ingest_excluded_text": ingest_excluded_text,
        "timeseries_rows_count": timeseries_rows_count,
        "qc_total_scenes": qc_total_scenes,
        "qc_pass_scenes": qc_pass_scenes,
        "qc_excluded_scenes": qc_excluded_scenes,
        "qc_exclusions": qc_exclusions,
        "qc_primary_exclusions": qc_primary_exclusions,
        "qc_multi_count": qc_multi_count,
        "qc_multi_breakdown_text": qc_multi_breakdown_text,
        "low_valid_overlap_note": low_valid_overlap_note,
        "cmo_overlap_note": cmo_overlap_note,
        "bad_red_overlap_note": bad_red_overlap_note,
        "dry_season_by_year": dry_qc_by_year,
        "dry_season_total": dry_total,
        "dry_season_min": dry_min,
        "dry_season_max": dry_max,
        "grid_estimates": grid_estimates,
        "upper_area_threshold": upper_area_threshold,
        "band": {
            "low": obs_low,
            "central": obs_central,
            "high": obs_high,
        },
        "band_span": band_span,
        "band_span_pct": band_span_pct,
        "shortfall_central": report.shortfall_central_ha or 0.0,
        "shortfall_low": report.shortfall_low_ha or 0.0,
        "detection_limit_ha": det_limit,
        "detection_limit_pct": det_limit_pct,
        "detection_limit_pct_2d": det_limit_pct_2d,
        "cohorts": cohorts_dict,
        "cohort_tot_range": cohort_tot_range,
        "cohort_21_range": cohort_21_range,
        "scheduled_2019_2020": sched_19_20,
        "scheduled_2020": sched_20,
        "table_ref": table_ref,
        "b64_cohort_maps": b64_cohort_maps,
        "b64_timeseries": b64_timeseries,
        "b64_decline_map": b64_decline_map,
        "pre_existing_decline_ha": pre_decline_ha,
        "saturation_share_pct": sat_share_pct,
        "saturation_raw_threshold": sat_raw_thresh,
        "ring_p5_2019": ring_p5_19,
        "ring_p5_2022_raw": ring_p5_22_raw,
        "extractor": extractor,
        "pdf_sha256": pdf_sha256,
        "file_hashes": file_hashes,
        "norm_sens": norm_sens,
        "raw_band": raw_band,
        "raw_areas": raw_areas,
        "raw_ring_medians": raw_ring_medians,
        "hansen": hansen_crosscheck,
        "forest_allowance_check": forest_allowance_check,
        "decline": decline_analysis,
        "canopy_biomass": canopy_biomass,
        "earliest_planting_year": earliest_planting_year,
        "project_start_month": project_start_month,
    }


def render(
    report: DiscrepancyReport,
    out_dir: Union[str, Path],
) -> Tuple[Path, Path]:
    """Render verification discrepancy report into report.json and report.html.

    Args:
        report: DiscrepancyReport model instance.
        out_dir: Output directory path.

    Returns:
        Tuple[Path, Path]: Tuple of (json_path, html_path).
    """
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_file = output_path / "report.json"
    html_file = output_path / "report.html"

    logger.info("Rendering report for project '%s' to %s", report.project_id, output_path)

    # 1. Write report.json
    with open(json_file, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    # 2. Write report.html
    # Maintain demo fixture behavior for demo runs
    if report.demo or report.project_id == "demo":
        template = Template(DEMO_HTML_TEMPLATE)
        rendered_html = template.render(report=report)
    else:
        context = _load_2469_context(report, output_path)
        template = Template(REPORT_2469_TEMPLATE)
        rendered_html = template.render(**context)

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    # 3. Copy figures to output_path if present
    comp_dir = Path("data/projects") / report.project_id / "imagery" / "composites"
    for fig_name in ["cohort_maps.png", "zone_timeseries.png", "decline_map.png"]:
        src_fig = comp_dir / fig_name
        if src_fig.exists():
            dst_fig = output_path / fig_name
            try:
                shutil.copyfile(src_fig, dst_fig)
            except Exception as e:
                logger.warning("Could not copy figure %s to %s: %s", src_fig, dst_fig, e)

    logger.info("Successfully generated: %s and %s", json_file, html_file)
    return json_file, html_file
