"""Command-line interface for the carbonverify verification pipeline."""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import List, Optional

from carbonverify.claims.extractor import extract_claims
from carbonverify.pipeline import run

# Configure default logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("carbonverify.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="carbonverify",
        description="Remote sensing verification pipeline for carbon-offset project claims.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # 'run' subcommand
    run_parser = subparsers.add_parser("run", help="Run verification on a project folder")
    run_parser.add_argument(
        "--project",
        required=True,
        type=str,
        help="Path to project directory containing claims and boundary (e.g. data/projects/demo)",
    )
    run_parser.add_argument(
        "--config",
        default="config.yaml",
        type=str,
        help="Path to pipeline configuration YAML file (default: config.yaml)",
    )
    run_parser.add_argument(
        "--out-dir",
        default=None,
        type=str,
        help="Directory to save output reports (default: output/<project_id>)",
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    # 'extract' subcommand: parses document claims only (without satellite download/estimation)
    extract_parser = subparsers.add_parser("extract", help="Extract claims from project folder or PDF/JSON document")
    extract_parser.add_argument(
        "--project",
        default=None,
        type=str,
        help="Path to project directory containing docs/ (e.g. data/projects/2469)",
    )
    extract_parser.add_argument(
        "--doc",
        default=None,
        type=str,
        help="Path to project PDF document (PDD) or claims JSON file",
    )
    extract_parser.add_argument(
        "--config",
        default="config.yaml",
        type=str,
        help="Path to pipeline configuration YAML file (default: config.yaml)",
    )
    extract_parser.add_argument(
        "--out-dir",
        default=None,
        type=str,
        help="Directory to save extraction_report.json (default: output/<project_name>)",
    )
    extract_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    # 'fetch' subcommand: fetches satellite imagery and calculates NDVI zonal statistics
    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch satellite imagery and compute zonal NDVI statistics",
    )
    fetch_parser.add_argument(
        "--project",
        required=True,
        type=str,
        help="Path to project directory containing boundary.geojson (e.g. data/projects/2469)",
    )
    fetch_parser.add_argument(
        "--workers",
        default=8,
        type=int,
        help="Number of concurrent worker threads (default: 8)",
    )
    fetch_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    # 'serve' subcommand: start web API and evidence workbench server
    serve_parser = subparsers.add_parser("serve", help="Start CarbonVerify web API and evidence workbench server")
    serve_parser.add_argument(
        "--output-dir",
        default="output",
        type=str,
        help="Directory containing project outputs (default: output)",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        type=str,
        help="Host address to bind to (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        default=8765,
        type=int,
        help="Port to listen on (default: 8765)",
    )
    serve_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    return parser


def main(args: Optional[List[str]] = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if parsed_args.command == "run":
        project_path = Path(parsed_args.project)
        config_path = Path(parsed_args.config) if parsed_args.config else None

        logger.info("Initializing carbonverify pipeline run...")
        logger.info("Target project: %s", project_path)

        try:
            report = run(
                project_dir=project_path,
                out_dir=parsed_args.out_dir,
                config=config_path if config_path and config_path.exists() else None,
            )

            out_folder = (
                Path(parsed_args.out_dir)
                if parsed_args.out_dir
                else Path("output") / project_path.name
            )

            print("\n" + "=" * 64)
            print("  CARBONVERIFY VERIFICATION SUMMARY")
            print("=" * 64)
            print(f"  Project ID:           {report.project_id}")
            print(f"  Registry:             {report.claims.registry.value if hasattr(report.claims.registry, 'value') else report.claims.registry}")
            print(f"  Methodology:          {report.claims.methodology}")
            area_str = f"{report.claims.claimed_area_ha:,.1f} ha" if report.claims.claimed_area_ha is not None else "Missing/Unverified"
            print(f"  Claimed Area:         {area_str}")
            est_footprint_str = f"{report.estimate.area_ha:,.1f} ha" if report.estimate.area_ha is not None else "not available"
            reg_estate_str = f"{report.claims.estate_area_ha:,.1f} ha" if report.claims.estate_area_ha is not None else "not available"
            print(f"  Estate footprint (boundary):   {est_footprint_str} (registry estate {reg_estate_str})")

            if (
                report.estimate.planted_area_obs_low is not None
                and report.estimate.planted_area_obs_high is not None
                and report.estimate.planted_area_obs_central is not None
            ):
                low_str = f"{report.estimate.planted_area_obs_low:,.2f}"
                high_str = f"{report.estimate.planted_area_obs_high:,.2f}"
                cen_str = f"{report.estimate.planted_area_obs_central:,.2f}"
                claim_str = f"{report.claims.claimed_area_ha:,.1f} ha" if report.claims.claimed_area_ha is not None else "not available"
                print(f"  Planted-area band:             [{low_str}, {high_str}] ha, central {cen_str} ha (claim {claim_str})")
            else:
                print("  Planted-area band:             not available")

            if report.planted_area_discrepancy_pct is not None:
                print(f"  Shortfall at generous end:     {report.planted_area_discrepancy_pct:.2f}%")
            else:
                print("  Shortfall at generous end:     not available")
            if report.canopy_discrepancy_pct is not None:
                print(f"  Canopy Discrepancy:   {report.canopy_discrepancy_pct:+.2f}%")
            print(f"  Demo Fixture:         {'Yes' if report.demo else 'No'}")
            print("-" * 64)
            print(f"  STATUS:               {report.status.value if hasattr(report.status, 'value') else report.status}")
            print(f"  CONFIDENCE:           {report.confidence.value if hasattr(report.confidence, 'value') else report.confidence}")
            if report.confidence_reasons:
                print("  Confidence Flags:")
                for reason in report.confidence_reasons:
                    print(f"    - {reason}")
            print("-" * 64)
            print("  Reports Generated:")
            print(f"    - JSON:  {out_folder / 'report.json'}")
            print(f"    - HTML:  {out_folder / 'report.html'}")
            if (out_folder / "extraction_report.json").exists():
                print(f"    - Audit: {out_folder / 'extraction_report.json'}")
            print("=" * 64 + "\n")

            return 0
        except Exception as exc:
            logger.error("Pipeline run failed: %s", exc, exc_info=parsed_args.verbose)
            return 1

    elif parsed_args.command == "extract":
        if parsed_args.project:
            target_path = Path(parsed_args.project)
        elif parsed_args.doc:
            target_path = Path(parsed_args.doc)
        else:
            logger.error("Either --project or --doc must be specified for claim extraction.")
            return 1

        config_path = Path(parsed_args.config) if parsed_args.config else None
        out_folder = (
            Path(parsed_args.out_dir)
            if parsed_args.out_dir
            else (target_path if target_path.is_dir() else target_path.parent)
        )

        logger.info("Extracting document claims from: %s", target_path)

        try:
            claims = extract_claims(
                doc_path=target_path,
                config=config_path if config_path and config_path.exists() else None,
                out_dir=out_folder,
            )

            report_file = out_folder / "extraction_report.json"

            print("\n" + "=" * 64)
            print("  CARBONVERIFY DOCUMENT CLAIMS EXTRACTION")
            print("=" * 64)
            print(f"  Target:               {target_path}")
            print(f"  Project ID:           {claims.project_id}")
            print(f"  Registry:             {claims.registry.value if hasattr(claims.registry, 'value') else claims.registry}")
            print(f"  Methodology:          {claims.methodology}")
            print(f"  Claimed Area:         {claims.claimed_area_ha} ha")
            print(f"  Reporting Period:     {claims.reporting_period_start} to {claims.reporting_period_end}")
            print(f"  Canopy Change:        {claims.claimed_canopy_change_pct}%")
            print(f"  Credits Issued:       {claims.credits_issued}")
            print(f"  Source Pages:         {claims.source_pages}")
            print(f"  Demo Fixture:         {'Yes' if claims.demo else 'No'}")
            print("-" * 64)
            print(f"  Extraction Audit:     {report_file}")
            print("=" * 64 + "\n")

            return 0
        except Exception as exc:
            logger.error("Claim extraction failed: %s", exc, exc_info=parsed_args.verbose)
            return 1

    if parsed_args.command == "fetch":
        project_path = Path(parsed_args.project)
        workers = getattr(parsed_args, "workers", 8)
        logger.info("Initializing carbonverify satellite imagery fetch...")
        logger.info("Target project: %s", project_path)

        try:
            from carbonverify.imagery.fetch import execute_imagery_verification

            report = execute_imagery_verification(
                project_dir=project_path, max_workers=workers
            )

            print("\n" + "=" * 64)
            print("  CARBONVERIFY SATELLITE IMAGERY ACQUISITION & STATS")
            print("=" * 64)
            print(f"  Target:               {project_path}")
            print(f"  Scenes Processed:     {report.get('total_scenes_processed')}")
            val_frac = report.get("mean_valid_fraction")
            frac_str = f"{val_frac:.2%}" if val_frac is not None else "N/A"
            print(f"  Mean Valid Fraction:  {frac_str}")
            print(f"  Runtime:              {report.get('total_runtime_seconds', 0.0):.2f}s")
            print("-" * 64)
            print(f"  Report:               {project_path / 'imagery' / 'imagery_report.json'}")
            print(f"  Timeseries:           {project_path / 'imagery' / 'timeseries.csv'}")
            print("=" * 64 + "\n")

            return 0
        except Exception as exc:
            logger.error("Imagery fetching failed: %s", exc, exc_info=parsed_args.verbose)
            return 1

    if parsed_args.command == "serve":
        output_dir = parsed_args.output_dir
        host = parsed_args.host
        port = parsed_args.port
        try:
            from carbonverify.webapi import run_server

            run_server(output_dir=output_dir, host=host, port=port)
            return 0
        except Exception as exc:
            logger.error("Serve command failed: %s", exc, exc_info=parsed_args.verbose)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
