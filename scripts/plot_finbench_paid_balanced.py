#!/usr/bin/env python3
"""Plot sealed FinBench analysis values without recalculating statistics."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

BASELINES = ("fixed_hash", "fixed_bind")
LABELS = ("Paid / fixed hash", "Paid / fixed bind")
FAMILIES = ("f1_direct_transfer_control", "f2_temporal_path_control", "f3_aggregate_risk_ranking")
COLORS = ("#0072B2", "#D55E00", "#009E73")
QUERY_IDS = tuple(f"m15-fb-confirmatory-48-f{f}-{i:02d}" for f in (1, 2, 3) for i in range(1, 17))


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.analysis.is_symlink() or not args.analysis.is_file():
        parser.error("--analysis must be a regular analysis JSON file")
    payload = args.analysis.read_bytes()
    data = json.loads(payload)
    if data.get("status") != "analyzed" or data.get("statistical_results_withheld"):
        parser.error("Analysis is unavailable or its statistical results are withheld")
    comparisons = {(c["population"], c["comparison"]): c for c in data["comparisons"]}
    if len(comparisons) != len(data["comparisons"]):
        parser.error("Duplicate comparison identities")
    metadata = {}
    for row in data["per_query"]:
        identity = (row["family_id"], row["integration_exposed"])
        if row["query_id"] in metadata and metadata[row["query_id"]] != identity:
            parser.error("Query metadata differs across methods")
        metadata[row["query_id"]] = identity
    if set(metadata) != set(QUERY_IDS):
        parser.error("The original 48-query denominator is required")
    primary, ratios = [], []
    for baseline in BASELINES:
        name = "paid_selection/" + baseline
        primary.append(comparisons["original32_seen", name])
        combined = {}
        for population, ids in (("original32_seen", QUERY_IDS[:32]), ("original16_heldout", QUERY_IDS[32:])):
            comparison = comparisons[population, name]
            values = comparison["per_query_ratios"]
            if comparison["query_denominator"] != len(ids) or not set(values) <= set(ids):
                parser.error("Comparison population identity/denominator differs")
            if not all(_positive(value) for value in values.values()):
                parser.error("Only finite positive recorded ratios can be plotted")
            combined.update(values)
        ratios.append(combined)
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "semibold"})
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.8, 5.0), gridspec_kw={"width_ratios": [1, 1.65]})
    fig.subplots_adjust(left=.12, right=.98, bottom=.25, top=.80, wspace=.30)
    fig.suptitle("FinBench prepared-plan methods: balanced mixed-cache sequence", y=.97, fontsize=14)
    left.set_title("(a) Original 32 seen: geometric means", loc="left", pad=18)
    left.set_xscale("log")
    left.axvline(1, color=".35", linestyle="--", linewidth=1)
    left.set_yticks([1, 0], LABELS)
    left.set_ylim(-.5, 1.5)
    left.set_xlabel("Paid / fixed wall-time ratio (log scale)")
    left.grid(axis="x", color=".90", linewidth=.6)
    for index, summary in enumerate(primary):
        value, interval, y = summary["gmean_ratio"], summary["percentile_interval_97_5"], 1 - index
        if value is None:
            left.text(.03, y, "Population estimate unavailable", transform=left.get_yaxis_transform(), fontsize=9)
            continue
        if not _positive(value) or not isinstance(interval, list) or len(interval) != 2 or not all(map(_positive, interval)) or interval[0] > interval[1]:
            raise ValueError("Recorded primary estimate/97.5% interval is invalid")
        left.hlines(y, *interval, color="#374151", linewidth=1.8)
        left.vlines(interval, y - .06, y + .06, color="#374151", linewidth=1.2)
        left.plot(value, y, "o", color="#111827", markersize=6)
        left.annotate(f"{value:.3f} [{interval[0]:.3f}, {interval[1]:.3f}]", (value, y),
                      xytext=(0, 13), textcoords="offset points", ha="center", fontsize=9)
    left.margins(x=.30)
    right.set_title("(b) All 48 queries; F3 descriptive", loc="left", pad=18)
    right.set_yscale("log")
    right.axhline(1, color=".35", linestyle="--", linewidth=1)
    right.axvspan(32.5, 48.5, color=COLORS[2], alpha=.045)
    for boundary in (16.5, 32.5):
        right.axvline(boundary, color=".8", linewidth=.7)
    for index, values in enumerate(ratios):
        for position, query_id in enumerate(QUERY_IDS, 1):
            if query_id not in values:
                continue
            family, exposed = metadata[query_id]
            color = COLORS[FAMILIES.index(family)]
            right.scatter(position + (-.17 if index == 0 else .17), values[query_id],
                          marker=("o", "D")[index], s=24, facecolors="none" if exposed else color,
                          edgecolors=color, linewidths=1, zorder=3)
    right.set(xlim=(.2, 48.8), xticks=[1, 8, 16, 24, 32, 40, 48],
              xlabel="Original query index (F1: 1–16; F2: 17–32; F3: 33–48)",
              ylabel="Paid / fixed median wall-time ratio")
    right.grid(axis="y", color=".90", linewidth=.6)
    handles = [Line2D([], [], color=c, marker="o", linestyle="none", label=f"F{i + 1}") for i, c in enumerate(COLORS)]
    handles += [Line2D([], [], color=".3", marker=m, linestyle="none", label=label)
                for m, label in zip(("o", "D"), ("vs hash", "vs bind"))]
    right.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, 1.05), ncol=5, fontsize=8, frameon=False)
    coverage = ", ".join(f"{label}: {len(values)}/48" for label, values in zip(("hash", "bind"), ratios))
    fig.text(.12, .11, "Ratios < 1 favor paid. Method wall includes acquisition and online persistence. Hollow markers: integration-exposed.", fontsize=9)
    fig.text(.12, .06, "97.5% intervals: conditional stratified query bootstrap. F3 is descriptive. Recorded pair coverage — " + coverage + ".", fontsize=9)
    files = []
    for extension in ("png", "svg"):
        path = output / ("paid_cost." + extension)
        fig.savefig(path, dpi=220, facecolor="white")
        raw = path.read_bytes()
        files.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
    plt.close(fig)
    script = Path(__file__).resolve()
    receipt = {"schema_version": "xgap-finbench-paid-balanced-plot-v1", "analysis_path": str(args.analysis.resolve()),
               "analysis_sha256": hashlib.sha256(payload).hexdigest(), "script_path": str(script),
               "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "matplotlib_version": matplotlib.__version__,
               "statistics_recomputed": False, "primary_denominator": 32, "query_denominator": 48, "files": files}
    (output / "plot_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(output / "plot_receipt.json")


if __name__ == "__main__":
    main()
