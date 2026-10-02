import argparse
import csv
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen


CADASTRE_COL_CANDIDATES = [
    "Objektu_identificejosie_kadastra_apzimejumi",
    "cadastrena",
]

ENERGY_CLASS_COL_CANDIDATES = [
    "Ekas_energoefektivitates_klase",
    "enef_klase",
]

REFERENCE_AREA_COL_CANDIDATES = [
    "References_platiba_m2",
    "lietd_plat",
]

EXPL_GADS_COL_CANDIDATES = [
    "ekspl_gads",
]

IPATN_SILT_COL_CANDIDATES = [
    "ipatn_silt",
]

RENOVATION_COL_CANDIDATES = [
    "renovacija",
    "Renovacija",
]


def normalize_cadastre(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 14:
        digits = digits.zfill(14)
    return digits


def parse_reference_area(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # Support both decimal separators: 1234.5 and 1234,5
    s = s.replace(" ", "")
    if "," in s and "." in s:
        # Handle values like 1.234,56 -> remove thousands separator first
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")

    try:
        return float(s)
    except ValueError:
        return None


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value: Any) -> Optional[int]:
    f = parse_float(value)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None


def parse_renovation_year(value: Any) -> Any:
    """Extract a four-digit renovation year, or preserve missing values as ''."""
    if value is None:
        return ""
    match = re.search(r"\b(\d{4})\b", str(value).strip())
    return int(match.group(1)) if match else ""


def split_cadastre_values(raw: Any) -> List[str]:
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []

    # Some rows may contain multiple cadastral numbers in one cell.
    parts = re.split(r"[|;,\n\r\t ]+", s)
    out: List[str] = []
    for part in parts:
        if part:
            out.append(part)
    return out


def get_first_value(row: Dict[str, Any], candidates: List[str]) -> Any:
    for col in candidates:
        if col in row:
            return row.get(col)
    return None


def first_present_column(fieldnames: Iterable[str], candidates: List[str]) -> Optional[str]:
    fieldset = set(fieldnames)
    for col in candidates:
        if col in fieldset:
            return col
    return None



def parse_csv_bytes(raw: bytes) -> Tuple[List[Dict[str, str]], List[str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        # Common in EU exports
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = list(reader)
    fieldnames = reader.fieldnames or []
    return rows, fieldnames


def parse_rows_from_shp_zip(raw: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    try:
        import shapefile  # pyshp
    except ImportError as exc:
        raise RuntimeError(
            "SHP input requires 'pyshp'. Install it with: pip install pyshp"
        ) from exc

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()

        # Prefer embedded CSV if available.
        csv_members = [n for n in names if n.lower().endswith(".csv")]
        if csv_members:
            with zf.open(csv_members[0]) as f:
                return parse_csv_bytes(f.read())

        shp_members = [n for n in names if n.lower().endswith(".shp")]
        if not shp_members:
            raise ValueError("ZIP does not contain CSV or SHP files")

        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            shp_path = Path(tmpdir) / shp_members[0]
            if not shp_path.exists():
                raise FileNotFoundError(f"Extracted SHP not found: {shp_path}")

            # Latvian DBF exports are often CP1257 encoded; try fallback encodings.
            encodings = ["utf-8", "cp1257", "cp1252", "latin1"]
            last_err: Optional[Exception] = None

            for enc in encodings:
                reader = None
                try:
                    reader = shapefile.Reader(str(shp_path), encoding=enc)
                    fieldnames = [f[0] for f in reader.fields[1:]]
                    rows: List[Dict[str, Any]] = []
                    for rec in reader.iterRecords():
                        rows.append(dict(zip(fieldnames, rec)))
                    return rows, fieldnames
                except Exception as exc:
                    last_err = exc
                finally:
                    if reader is not None:
                        try:
                            reader.close()
                        except Exception:
                            pass

            raise RuntimeError(f"Failed to read SHP DBF with tested encodings: {last_err}")


def fetch_table_rows(url: str, timeout: int) -> Tuple[List[Dict[str, Any]], List[str], str]:
    req = Request(url, headers={"User-Agent": "EGuard-ETL/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()

    is_zip = url.lower().endswith(".zip")
    if not is_zip:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        is_zip = "zip" in ctype

    if is_zip:
        rows, fieldnames = parse_rows_from_shp_zip(raw)
        return rows, fieldnames, "zip"

    rows, fieldnames = parse_csv_bytes(raw)
    return rows, fieldnames, "csv"


def build_lookup(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        cad_raw = get_first_value(row, CADASTRE_COL_CANDIDATES)
        cls = (get_first_value(row, ENERGY_CLASS_COL_CANDIDATES) or "").strip() or None
        area = parse_reference_area(get_first_value(row, REFERENCE_AREA_COL_CANDIDATES))
        ekspl_gads = parse_int(get_first_value(row, EXPL_GADS_COL_CANDIDATES))
        ipatn_silt = parse_float(get_first_value(row, IPATN_SILT_COL_CANDIDATES))
        renovation = parse_renovation_year(
            get_first_value(row, RENOVATION_COL_CANDIDATES)
        )

        cad_values = split_cadastre_values(cad_raw)
        for one in cad_values:
            cad = normalize_cadastre(one)
            if not cad:
                continue

            # Keep the first non-empty classification encountered.
            if cad not in lookup:
                lookup[cad] = {
                    "energy_perf_class": cls,
                    "energy_class": cls,
                    "reference_area_m2": area,
                    "manufacture_year": ekspl_gads,
                    "heating_indicator": ipatn_silt,
                    "renovation": renovation,
                }
            else:
                if lookup[cad].get("energy_perf_class") is None and cls is not None:
                    lookup[cad]["energy_perf_class"] = cls
                if lookup[cad].get("energy_class") is None and cls is not None:
                    lookup[cad]["energy_class"] = cls
                if lookup[cad].get("reference_area_m2") is None and area is not None:
                    lookup[cad]["reference_area_m2"] = area
                if lookup[cad].get("manufacture_year") is None and ekspl_gads is not None:
                    lookup[cad]["manufacture_year"] = ekspl_gads
                if lookup[cad].get("heating_indicator") is None and ipatn_silt is not None:
                    lookup[cad]["heating_indicator"] = ipatn_silt
                if lookup[cad].get("renovation", "") == "" and renovation != "":
                    lookup[cad]["renovation"] = renovation

    return lookup


def normalize_empty_to_null(value: Any) -> Any:
    if isinstance(value, str):
        return None if value.strip() == "" else value
    if isinstance(value, list):
        return [normalize_empty_to_null(item) for item in value]
    if isinstance(value, dict):
        return {k: normalize_empty_to_null(v) for k, v in value.items()}
    return value


def has_required_energy_fields(props: Dict[str, Any]) -> bool:
    energy_class = props.get("energy_class")
    reference_area = props.get("reference_area_m2")

    if energy_class is None:
        return False
    if isinstance(energy_class, str) and energy_class.strip() == "":
        return False
    if reference_area is None:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read CSV or ZIP(SHP/CSV) from URL and enrich GeoJSON with English keys: "
            "energy_class and reference_area_m2"
        )
    )
    parser.add_argument(
        "--url",
        required=True,
        help="HTTP(S) URL to CSV or ZIP file containing SHP/CSV",
    )
    parser.add_argument(
        "--input",
        default="./script_pipeline/output/all_buildings_with_building_fields_heat.json",
        help="Input GeoJSON path",
    )
    parser.add_argument(
        "--output",
        default="./script_pipeline/output/historical_residential_buildings_full_pipeline_heat_energy.json",
        help="Output GeoJSON path",
    )
    parser.add_argument(
        "--cadastre-field",
        default="CODE",
        help="GeoJSON feature property used as cadastre number",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input GeoJSON not found: {input_path}")

    print(f"Downloading source: {args.url}")
    rows, fieldnames, source_type = fetch_table_rows(args.url, args.timeout)
    print(f"Loaded rows: {len(rows)} (source={source_type})")

    cad_col = first_present_column(fieldnames, CADASTRE_COL_CANDIDATES)
    cls_col = first_present_column(fieldnames, ENERGY_CLASS_COL_CANDIDATES)
    area_col = first_present_column(fieldnames, REFERENCE_AREA_COL_CANDIDATES)
    ekspl_col = first_present_column(fieldnames, EXPL_GADS_COL_CANDIDATES)
    ipatn_col = first_present_column(fieldnames, IPATN_SILT_COL_CANDIDATES)
    renovation_col = first_present_column(fieldnames, RENOVATION_COL_CANDIDATES)

    missing_cols = []
    if cad_col is None:
        missing_cols.append("Objektu_identificejosie_kadastra_apzimejumi|cadastrena")
    if cls_col is None:
        missing_cols.append("Ekas_energoefektivitates_klase|enef_klase")
    if area_col is None:
        missing_cols.append("References_platiba_m2|lietd_plat")

    if missing_cols:
        raise ValueError(
            "CSV is missing required column(s): " + ", ".join(missing_cols)
        )

    print("Using columns:")
    print(f"  cadastre: {cad_col}")
    print(f"  energy class: {cls_col}")
    print(f"  reference area: {area_col}")
    print(f"  ekspl_gads: {ekspl_col or 'missing (will be null)'}")
    print(f"  ipatn_silt: {ipatn_col or 'missing (will be null)'}")
    print(f"  renovation: {renovation_col or 'missing (will be empty)'}")

    print("Building lookup from CSV...")
    lookup = build_lookup(rows)
    print(f"Unique cadastral keys in CSV: {len(lookup)}")

    print(f"Reading GeoJSON: {input_path}")
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Invalid GeoJSON: features is not a list")

    matched = 0
    unmatched = 0
    dropped_missing_energy = 0
    kept_features: List[Dict[str, Any]] = []

    for feat in features:
        props = feat.setdefault("properties", {})
        cad = normalize_cadastre(props.get(args.cadastre_field))

        if cad and cad in lookup:
            props["energy_perf_class"] = lookup[cad].get("energy_perf_class")
            props["energy_class"] = lookup[cad].get("energy_class")
            props["reference_area_m2"] = lookup[cad].get("reference_area_m2")
            props["manufacture_year"] = lookup[cad].get("manufacture_year")
            props["heating_indicator"] = lookup[cad].get("heating_indicator")
            props["renovation"] = lookup[cad].get("renovation", "")
            matched += 1
        else:
            props["energy_perf_class"] = None
            props["energy_class"] = None
            props["reference_area_m2"] = None
            props["manufacture_year"] = None
            props["heating_indicator"] = None
            props["renovation"] = ""
            unmatched += 1

        renovation = props.get("renovation", "")
        feat["properties"] = normalize_empty_to_null(props)
        # Renovation intentionally uses an empty string for missing values.
        feat["properties"]["renovation"] = renovation
        if not has_required_energy_fields(feat["properties"]):
            dropped_missing_energy += 1
            continue
        kept_features.append(feat)

    data["features"] = kept_features

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Done")
    print(f"Features before filter: {len(features)}")
    print(f"Removed missing energy class/reference area: {dropped_missing_energy}")
    print(f"Features after filter: {len(kept_features)}")
    print(f"Matched: {matched}")
    print(f"Unmatched: {unmatched}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
