"""Generate zone_timeseries.png for project 2469."""

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd


def generate_timeseries_plot(
    qc_csv_path: Path,
    output_png_path: Path,
) -> None:
    df = pd.read_csv(qc_csv_path)
    df["dt"] = pd.to_datetime(df["date"])
    df = df.sort_values("dt").reset_index(drop=True)

    pass_df = df[df["qc_pass"] == True].copy()
    fail_df = df[df["qc_pass"] == False].copy()

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)

    # Plot QC-pass scenes
    ax.plot(
        pass_df["dt"],
        pass_df["proj_ndvi_median"],
        color="#10b981",
        linestyle="-",
        linewidth=1.8,
        marker="o",
        markersize=4,
        alpha=0.9,
        label="Project Zone (QC Pass, n=162)",
    )
    ax.plot(
        pass_df["dt"],
        pass_df["ring_ndvi_median"],
        color="#3b82f6",
        linestyle="--",
        linewidth=1.5,
        marker="s",
        markersize=3.5,
        alpha=0.8,
        label="Reference Ring (QC Pass, n=162)",
    )

    # Plot excluded scenes
    if len(fail_df) > 0:
        ax.scatter(
            fail_df["dt"],
            fail_df["proj_ndvi_median"],
            color="#ef4444",
            marker="x",
            s=45,
            linewidth=1.8,
            zorder=5,
            label=f"Excluded Scenes (Project, n={len(fail_df)})",
        )
        ax.scatter(
            fail_df["dt"],
            fail_df["ring_ndvi_median"],
            color="#f97316",
            marker="+",
            s=45,
            linewidth=1.8,
            zorder=5,
            label=f"Excluded Scenes (Ring, n={len(fail_df)})",
        )

    # Highlight dry seasons (Jun-Aug of 2019, 2020, 2021, 2022)
    for yr in [2019, 2020, 2021, 2022]:
        start_d = pd.to_datetime(f"{yr}-06-01")
        end_d = pd.to_datetime(f"{yr}-08-31")
        ax.axvspan(start_d, end_d, color="#fef3c7", alpha=0.35, label="Dry Season (Jun-Aug)" if yr == 2019 else "")

    ax.set_title("Project 2469: Sentinel-2 Zone NDVI Time Series (2019–2022)", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Acquisition Date", fontsize=11, labelpad=8)
    ax.set_ylabel("NDVI Median", fontsize=11, labelpad=8)
    ax.set_ylim(0.0, 1.0)

    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%b"))

    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower right", frameon=True, framealpha=0.9, facecolor="white", edgecolor="#cbd5e1", fontsize=9.5)

    plt.tight_layout()
    output_png_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png_path, dpi=150)
    plt.close()
    print(f"Generated {output_png_path} ({output_png_path.stat().st_size} bytes)")


if __name__ == "__main__":
    qc_csv = Path("data/projects/2469/imagery/qc_scenes.csv")
    out_png = Path("data/projects/2469/imagery/composites/zone_timeseries.png")
    generate_timeseries_plot(qc_csv, out_png)
