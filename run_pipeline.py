"""
Residential GeoJSON ETL Pipeline (full flow only).

This script always runs all stages:
1. XML -> CSV batch conversion
2. Cadastre merge/classification with historical allowlist
3. Final merge to a single residential GeoJSON
4. Deduplication
5. Heating CSV fallback for missing building_data
6. Heat consumption enrichment
7. Energy class enrichment

Example:
    python run_pipeline.py
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
import shutil
from typing import Any, Dict, Optional


def run_step(cmd, cwd, title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print("Running:", " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {title}")


def _has_non_empty_building_data(props: Dict[str, Any]) -> bool:
    bd = props.get("building_data")
    return isinstance(bd, list) and len(bd) > 0


def _has_non_empty_heat_series(props: Dict[str, Any]) -> bool:
    ts = props.get("heat_consumption_timeseries")
    return isinstance(ts, dict) and len(ts) > 0


def compute_geojson_stats(path: Path) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "total_features": 0,
        "with_building_data": 0,
        "without_building_data": 0,
        "with_heat_series": 0,
        "without_heat_series": 0,
    }

    if not path.exists():
        return stats

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        stats["error"] = str(exc)
        return stats

    features = data.get("features", [])
    if not isinstance(features, list):
        stats["error"] = "Invalid GeoJSON: features is not a list"
        return stats

    stats["total_features"] = len(features)

    for feature in features:
        props = feature.get("properties", {})
        has_building_data = _has_non_empty_building_data(props)
        has_heat_series = _has_non_empty_heat_series(props)

        if has_building_data:
            stats["with_building_data"] += 1
        else:
            stats["without_building_data"] += 1

        if has_heat_series:
            stats["with_heat_series"] += 1
        else:
            stats["without_heat_series"] += 1

    return stats


def print_geojson_stats(label: str, stats: Dict[str, Any]) -> None:
    print(f"\n[METRICS] {label}")
    print(f"  file: {stats.get('path')}")

    if not stats.get("exists"):
        print("  status: missing")
        return

    if "error" in stats:
        print(f"  status: error ({stats['error']})")
        return

    print(f"  total features: {stats['total_features']}")
    print(
        "  building_data: "
        f"{stats['with_building_data']} with / {stats['without_building_data']} without"
    )
    print(
        "  heat series: "
        f"{stats['with_heat_series']} with / {stats['without_heat_series']} without"
    )


def print_geojson_delta(label: str, before: Dict[str, Any], after: Dict[str, Any]) -> None:
    print(f"\n[DELTA] {label}")

    if not before.get("exists") or not after.get("exists"):
        print("  delta unavailable (missing input or output file)")
        return

    if "error" in before or "error" in after:
        print("  delta unavailable (failed to read metrics)")
        return

    total_before = before["total_features"]
    total_after = after["total_features"]
    total_delta = total_after - total_before
    discarded = max(0, total_before - total_after)
    added = max(0, total_after - total_before)

    print(f"  input features:  {total_before}")
    print(f"  output features: {total_after}")
    print(f"  net change:      {total_delta:+d}")
    print(f"  discarded:       {discarded}")
    print(f"  added:           {added}")
    print(
        "  without building_data: "
        f"{before['without_building_data']} -> {after['without_building_data']} "
        f"({after['without_building_data'] - before['without_building_data']:+d})"
    )
    print(
        "  without heat series:   "
        f"{before['without_heat_series']} -> {after['without_heat_series']} "
        f"({after['without_heat_series'] - before['without_heat_series']:+d})"
    )


def count_features_in_geojson(path: Path) -> int:
    stats = compute_geojson_stats(path)
    if not stats.get("exists") or "error" in stats:
        return 0
    return int(stats.get("total_features", 0))


def summarize_geojson_folder(folder: Path) -> Dict[str, int]:
    files = sorted(folder.glob("*.geojson"))

    total_features = 0
    for file_path in files:
        total_features += count_features_in_geojson(file_path)

    return {
        "file_count": len(files),
        "total_features": total_features,
    }


def clean_output_geojson_files(folder: Path) -> int:
    """Remove prior pipeline GeoJSON outputs to avoid stale re-merges."""
    if not folder.exists():
        return 0

    removed = 0
    for pattern in ("merged_*.geojson", "ALL_*.geojson"):
        for path in folder.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                print(f"Warning: failed to delete stale file {path}: {exc}")
    return removed


def build_geojson_stats_lines(label: str, stats: Dict[str, Any]) -> list[str]:
    lines = [f"[METRICS] {label}", f"  file: {stats.get('path')}"]

    if not stats.get("exists"):
        lines.append("  status: missing")
        return lines

    if "error" in stats:
        lines.append(f"  status: error ({stats['error']})")
        return lines

    lines.append(f"  total features: {stats['total_features']}")
    lines.append(
        "  building_data: "
        f"{stats['with_building_data']} with / {stats['without_building_data']} without"
    )
    lines.append(
        "  heat series: "
        f"{stats['with_heat_series']} with / {stats['without_heat_series']} without"
    )
    return lines


def build_geojson_delta_lines(label: str, before: Dict[str, Any], after: Dict[str, Any]) -> list[str]:
    lines = [f"[DELTA] {label}"]

    if not before.get("exists") or not after.get("exists"):
        lines.append("  delta unavailable (missing input or output file)")
        return lines

    if "error" in before or "error" in after:
        lines.append("  delta unavailable (failed to read metrics)")
        return lines

    total_before = before["total_features"]
    total_after = after["total_features"]
    total_delta = total_after - total_before
    discarded = max(0, total_before - total_after)
    added = max(0, total_after - total_before)

    lines.append(f"  input features:  {total_before}")
    lines.append(f"  output features: {total_after}")
    lines.append(f"  net change:      {total_delta:+d}")
    lines.append(f"  discarded:       {discarded}")
    lines.append(f"  added:           {added}")
    lines.append(
        "  without building_data: "
        f"{before['without_building_data']} -> {after['without_building_data']} "
        f"({after['without_building_data'] - before['without_building_data']:+d})"
    )
    lines.append(
        "  without heat series:   "
        f"{before['without_heat_series']} -> {after['without_heat_series']} "
        f"({after['without_heat_series'] - before['without_heat_series']:+d})"
    )
    return lines


def write_metrics_report(
    report_path: Path,
    merged_folder_summary: Dict[str, int],
    stage_metrics: list[tuple[str, Dict[str, Any]]],
    step_deltas: list[tuple[str, Dict[str, Any], Dict[str, Any]]],
) -> None:
    lines: list[str] = []
    lines.append("PIPELINE METRICS REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append("[METRICS] Step 2 output summary")
    lines.append(f"  merged files found: {merged_folder_summary['file_count']}")
    lines.append(
        f"  total features across merged files: {merged_folder_summary['total_features']}"
    )
    lines.append("")

    if step_deltas:
        lines.append("STEP DELTAS")
        lines.append("-" * 80)
        for idx, (label, before, after) in enumerate(step_deltas):
            lines.extend(build_geojson_delta_lines(label, before, after))
            if idx < len(step_deltas) - 1:
                lines.append("")
        lines.append("")

    if stage_metrics:
        lines.append("STAGE METRICS")
        lines.append("-" * 80)
        for idx, (label, stats) in enumerate(stage_metrics):
            lines.extend(build_geojson_stats_lines(label, stats))
            if idx < len(stage_metrics) - 1:
                lines.append("")
        lines.append("")
        lines.append("PIPELINE METRICS SUMMARY")
        lines.append("-" * 80)
        for label, stats in stage_metrics:
            if not stats.get("exists") or "error" in stats:
                lines.append(f"- {label}: metrics unavailable")
                continue

            lines.append(
                f"- {label}: total={stats['total_features']}, "
                f"without_building_data={stats['without_building_data']}, "
                f"without_heat_series={stats['without_heat_series']}"
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def first_existing_path(*candidates: Path) -> Optional[Path]:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_geojson_stage(
    *,
    project_root: Path,
    stage_key: str,
    title: str,
    script_path: Path,
    extra_args: list[str],
    input_path: Path,
    output_path: Path,
    delta_label: str,
    metrics_label: str,
    step_deltas: list[tuple[str, Dict[str, Any], Dict[str, Any]]],
    stage_metrics: list[tuple[str, Dict[str, Any]]],
) -> None:
    before = compute_geojson_stats(input_path)
    run_step(
        [
            sys.executable,
            str(script_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            *extra_args,
        ],
        cwd=str(project_root),
        title=title,
    )

    after_target = output_path if output_path.exists() else input_path
    after = compute_geojson_stats(after_target)
    print_geojson_delta(delta_label, before, after)
    step_deltas.append((delta_label, before, after))
    print_geojson_stats(metrics_label, after)
    stage_metrics.append((stage_key, after))


def main():
    parser = argparse.ArgumentParser(
        description="Run the default full residential GeoJSON pipeline end-to-end."
    )
    parser.parse_args()

    # Prefer inputs placed in a central `data/` folder
    shape_base = "./data/0001000_kk_shp"
    building_base = "./data/building"
    output_base = "./merged_output_residential"
    heat_cache_file = "./data/building_heat_series.json"
    heating_fallback_csv = "./data/Heating_2017-2024.csv"
    energy_csv_url = (
        "https://data.gov.lv/dati/dataset/df5908be-3995-4a34-99a7-34e8d454b71b/"
        "resource/12b3dd61-42d3-4d28-9862-44e4481939bf/download/"
        "majas_energoefektivitates_raditaji.zip"
    )
    historical_cadastres_csv = "./data/historical_cadastre_lookup.csv"
    metrics_report = "./pipeline_metrics_report.txt"

    script_dir = Path(__file__).resolve().parent
    # Project root is the script directory (repo root)
    project_root = script_dir
    output_dir = script_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_base_dir = project_root / output_base
    final_merged_output = output_base_dir / "ALL_RESIDENTIAL_BUILDINGS.geojson"
    dedup_output = output_dir / "ALL_RESIDENTIAL_BUILDINGS_WITH_BUILDING_FIELDS_DEDUP.geojson"
    pipeline_final_copy = output_dir / "all_buildings_with_building_fields.json"
    enriched_output = output_dir / "all_buildings_with_building_fields_heat.json"
    energy_output = output_dir / "historical_residential_buildings_full_pipeline_heat_energy.json"

    batch_script = script_dir / "01_xml_to_csv" / "batch_xml2csv.py"
    merge_script = script_dir / "02_build_dataset" / "build_residential_dataset.py"
    final_merge_script = script_dir / "03_merge_and_dedup" / "combine_residential_groups.py"
    heat_script = script_dir / "04_enrich_heat" / "enrich_heat_timeseries.py"
    if not heat_script.exists():
        heat_script = script_dir / "utils" / "enrich_heat_consumption.py"
    heat_parallel_script = script_dir / "04_enrich_heat" / "enrich_heat_timeseries.py"
    dedup_script = script_dir / "03_merge_and_dedup" / "deduplicate_geojson.py"
    energy_script = script_dir / "05_enrich_energy" / "enrich_energy_class.py"
    heating_fallback_script = script_dir / "03_merge_and_dedup" / "heating_data_fallback.py"

    required_scripts = [
        batch_script,
        merge_script,
        final_merge_script,
        dedup_script,
        heat_script,
        heating_fallback_script,
        energy_script,
    ]

    missing = [str(p) for p in required_scripts if not p.exists()]
    if missing:
        print("Missing required script(s):")
        for m in missing:
            print(" -", m)
        sys.exit(1)

    print("Project root:", project_root)
    removed = clean_output_geojson_files(output_base_dir)
    print(f"\nCleaned stale output GeoJSON files in {output_base_dir}: removed {removed}")

    stage_metrics = []
    step_deltas = []

    run_step(
        [sys.executable, str(batch_script)],
        cwd=str(project_root),
        title="Step 1/3: XML -> CSV batch conversion",
    )

    run_step(
        [
            sys.executable,
            str(merge_script),
            shape_base,
            building_base,
            output_base,
            historical_cadastres_csv,
        ],
        cwd=str(project_root),
        title="Step 2/3: Merge and classify residential buildings",
    )

    merged_folder_summary = summarize_geojson_folder(output_base_dir)
    print("\n[METRICS] Step 2 output summary")
    print(f"  merged files found: {merged_folder_summary['file_count']}")
    print(f"  total features across merged files: {merged_folder_summary['total_features']}")

    run_step(
        [
            sys.executable,
            str(final_merge_script),
            "--input-folder",
            output_base,
            "--output-file",
            str(final_merged_output),
            "--include-pattern",
            "merged_ExportCadGroup_*_KKBuilding.geojson",
        ],
        cwd=str(project_root),
        title="Step 3/3: Merge to single final GeoJSON",
    )

    merged_final_stats = compute_geojson_stats(final_merged_output)
    print_geojson_stats("Step 3 merged final", merged_final_stats)
    stage_metrics.append(("merged final", merged_final_stats))

    final_path = final_merged_output

    if final_path.exists():
        dedup_before = compute_geojson_stats(final_path)
        run_step(
            [
                sys.executable,
                str(dedup_script),
                "--input",
                str(final_path),
                "--output",
                str(dedup_output),
            ],
            cwd=str(project_root),
            title="Step 3b: Deduplicate residential buildings",
        )
        dedup_after = compute_geojson_stats(dedup_output)
        print_geojson_delta("Step 3b deduplication", dedup_before, dedup_after)
        step_deltas.append(("Step 3b deduplication", dedup_before, dedup_after))
        print_geojson_stats("Step 3b deduplicated output", dedup_after)
        stage_metrics.append(("deduplicated", dedup_after))
        final_path = dedup_output
    else:
        print("Skipped deduplication: final merge output not found")

    if final_path.exists():
        shutil.copy2(final_path, pipeline_final_copy)
        print("Copied stage output to:", pipeline_final_copy)

        copy_stats = compute_geojson_stats(pipeline_final_copy)
        print_geojson_stats("Stage copy for enrichment", copy_stats)
        stage_metrics.append(("base for enrichment", copy_stats))
    else:
        print("Skipped copy: final output not found at", final_path)

    fallback_input = first_existing_path(pipeline_final_copy, final_path)
    if fallback_input:
        run_geojson_stage(
            project_root=project_root,
            stage_key="post fallback",
            title="Step 3d: Fill missing building_data from Heating fallback CSV",
            script_path=heating_fallback_script,
            extra_args=["--heating-csv", heating_fallback_csv],
            input_path=fallback_input,
            output_path=fallback_input,
            delta_label="Step 3c heating fallback",
            metrics_label="Step 3c post-fallback",
            step_deltas=step_deltas,
            stage_metrics=stage_metrics,
        )
    else:
        print("Skipped heating fallback: input final file not found")

    heat_input = first_existing_path(pipeline_final_copy, final_path)
    if heat_input:
        heat_extra_args: list[str] = []
        if heat_script == heat_parallel_script:
            heat_extra_args.extend([
                "--cache-file",
                heat_cache_file,
                "--rea-json",
                "./data/rea_all_features.json",
            ])

        run_geojson_stage(
            project_root=project_root,
            stage_key="post heat enrichment",
            title="Step 4/4: Enrich final GeoJSON with heat consumption",
            script_path=heat_script,
            extra_args=heat_extra_args,
            input_path=heat_input,
            output_path=enriched_output,
            delta_label="Step 4 heat enrichment",
            metrics_label="Step 4 heat-enriched output",
            step_deltas=step_deltas,
            stage_metrics=stage_metrics,
        )
    else:
        print("Skipped heat enrichment: input final file not found")

    # Keep each output stage separate: never overwrite prior outputs.
    energy_input = first_existing_path(enriched_output, pipeline_final_copy)
    if energy_input:
        run_geojson_stage(
            project_root=project_root,
            stage_key="post energy enrichment",
            title="Step 5/5: Enrich with energy class and reference area",
            script_path=energy_script,
            extra_args=["--url", energy_csv_url],
            input_path=energy_input,
            output_path=energy_output,
            delta_label="Step 5 energy enrichment",
            metrics_label="Step 5 energy-enriched output",
            step_deltas=step_deltas,
            stage_metrics=stage_metrics,
        )
    else:
        print("Skipped energy-class enrichment: input file not found")

    print("\nPipeline complete.")
    print("Final file:", final_path)
    if final_path.exists():
        print("Final file exists: yes")
    else:
        print("Final file exists: no (check logs above)")
    if enriched_output.exists():
        print("Heat-enriched file:", enriched_output)
    else:
        print("Heat-enriched file: not created")
    if energy_output.exists():
        print("Energy-enriched file:", energy_output)
    else:
        print("Energy-enriched file: not created")

    if stage_metrics:
        print("\n" + "=" * 80)
        print("PIPELINE METRICS SUMMARY")
        print("=" * 80)
        for label, stats in stage_metrics:
            if not stats.get("exists") or "error" in stats:
                print(f"- {label}: metrics unavailable")
                continue

            print(
                f"- {label}: total={stats['total_features']}, "
                f"without_building_data={stats['without_building_data']}, "
                f"without_heat_series={stats['without_heat_series']}"
            )

    metrics_report_path = project_root / metrics_report
    write_metrics_report(
        report_path=metrics_report_path,
        merged_folder_summary=merged_folder_summary,
        stage_metrics=stage_metrics,
        step_deltas=step_deltas,
    )
    print(f"\nMetrics report written to: {metrics_report_path}")


if __name__ == "__main__":
    main()
