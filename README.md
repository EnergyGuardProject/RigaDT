# RigaDT data preprocessing pipeline

## Folder structure

```
script_pipeline/
├── run_pipeline.py                         ← orchestrator
├── 01_xml_to_csv/
│   └── batch_xml2csv.py
├── 02_build_dataset/
│   ├── build_residential_dataset.py
│   └── material_classifier.py
├── 03_merge_and_dedup/
│   ├── combine_residential_groups.py
│   ├── deduplicate_geojson.py
│   └── heating_data_fallback.py
├── 04_enrich_heat/
│   └── enrich_heat_timeseries.py
├── 05_enrich_energy/
│   └── enrich_energy_class.py
├── output/                                 ← pipeline-generated files
└── utils/
    ├── download_rea_all_features.py        ← one-time REA data download
    ├── filter_only_with_heat_series.py     ← optional post-pipeline filter
    ├── enrich_heat_consumption.py          ← legacy API-based enrichment (reference only)
    └── debug/
        ├── analyze_duplicates.py
        ├── check_data_match.py
        ├── debug_extraction.py
        ├── evaluate_output.py
        └── inspect_geojson.py
```

## Steps

### 1 — XML → CSV (`01_xml_to_csv/batch_xml2csv.py`)
- Does: parse State Land textual XML exports into a normalized CSV of building attributes.
- Keeps: rows with a cadastral identifier (`Kadastra Nr.` / `CODE`), building type, address fields, and basic attributes used later (area, floors, year).
- Source: State Land - Textual Data — https://data.gov.lv/dati/dataset/b28f0eed-73b0-4e44-94e7-b04b11bf0b69/resource/bf88b763-98b8-445d-a51f-b76f45c362c5/download/0001000_kk_shp.zip (or local folder `0001000_kk_shp`)

### 2 — Geometry merge & classification (`02_build_dataset/build_residential_dataset.py`)
- Does: read per-group geometry (shapefiles / GeoJSON), join with textual CSV by cadastre ID, run material/classification rules.
- Keeps: features that match the textual CSV and that are residential (filter by `OBJECTCODE` / building type), and whose `CODE` is present in the historical allowlist.
- Source: State Land - Geometry Data — https://data.gov.lv/dati/dataset/be841486-4af9-4d38-aa14-6502a2ddb517/resource/9fe29b57-07cd-4458-b22c-b0b9f2bc8915/download/building.zip (or local `0001000_kk_shp/ExportCadGroup_*`)

### 3 — Concatenate groups (`03_merge_and_dedup/combine_residential_groups.py`)
- Does: combine per-group GeoJSONs into a single file for downstream processing.
- Keeps: all merged residential features produced in step 2 (no further filtering).
- Output: `merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson`

### 3b — Deduplicate (`03_merge_and_dedup/deduplicate_geojson.py`)
- Does: collapse features that share the same cadastral `CODE` with keep-first strategy.
- Keeps: one canonical feature per `CODE`.
- Output: `output/ALL_RESIDENTIAL_BUILDINGS_WITH_BUILDING_FIELDS_DEDUP.geojson`

### 3c — Fill missing building attributes (`03_merge_and_dedup/heating_data_fallback.py`)
- Does: use `Heating_2017-2024.csv` fallback to populate missing `building_data` fields (e.g., heated area, heating system) when available.
- Keeps: all features; updates properties where heating CSV provides data.
- Source (local): `Heating_2017-2024.csv`

### 4 — Heat consumption enrichment (`04_enrich_heat/enrich_heat_timeseries.py`)
- Does: resolve heat timeseries for each deduplicated `CODE` from REA JSON export (primary) or local cache (fallback). No API queries are made during the pipeline.
- Resolution order: (1) REA JSON export (5531 records), (2) local cache, (3) None.
- Keeps: all features; those without heat data remain with `heat_consumption_timeseries = None`.
- Local inputs: `output/all_buildings_with_building_fields.json` and `output/rea_all_features.json`

### 5 — Energy-class enrichment (`05_enrich_energy/enrich_energy_class.py`)
- Does: download public energy CSV/ZIP, match by building identifier, and attach energy performance fields.
- Keeps: only features that have both `energy_class` and `reference_area_m2` (others are dropped from the final output).
- Example sources:
  - Building energy certificates SCCB: https://data.gov.lv/dati/dataset/075498f5-0136-47d7-af86-0066acb0264c/resource/212c0946-a06e-4c2c-8112-833b2969b44b/download/eku-energosertifikati-21.10.2025.csv
  - Energy efficiency indicators (package query): https://data.gov.lv/api/action/package_search?q=rigas-daudzdzivoklu-maju-apkures-energoefektivitates-raditaji

## Final outputs

| File | Description |
|------|-------------|
| `output/all_buildings_with_building_fields.json` | Merged base (pre-heat) |
| `output/all_buildings_with_building_fields_heat.json` | Heat-enriched (post-step 4) |
| `output/historical_residential_buildings_full_pipeline_heat_energy.json` | Final heat + energy output (post-step 5) |

## Run

```powershell
python .\script_pipeline\run_pipeline.py
```

## Datasets

| Name | Source |
|------|--------|
| State Land - Textual Data | https://data.gov.lv/dati/dataset/b28f0eed-73b0-4e44-94e7-b04b11bf0b69/resource/bf88b763-98b8-445d-a51f-b76f45c362c5/download/0001000_kk_shp.zip |
| State Land - Geometry Data | https://data.gov.lv/dati/dataset/be841486-4af9-4d38-aa14-6502a2ddb517/resource/9fe29b57-07cd-4458-b22c-b0b9f2bc8915/download/building.zip |
| Heating time series (local) | `Heating_2017-2024.csv` |
| Historical cadastre allowlist (local) | `script_pipeline/historical_cadastre_lookup.csv` |
| Building energy certificates | https://data.gov.lv/dati/dataset/075498f5-0136-47d7-af86-0066acb0264c/resource/212c0946-a06e-4c2c-8112-833b2969b44b/download/eku-energosertifikati-21.10.2025.csv |
| Energy efficiency indicators | https://data.gov.lv/api/action/package_search?q=rigas-daudzdzivoklu-maju-apkures-energoefektivitates-raditaji |
| 3D LOD2 | https://data.gov.lv/api/action/package_search?q=rigas-apkaimju-lod2-modeli |
| Riga neighborhoods | https://data.gov.lv/api/action/package_search?q=rigas_apkaimes |

## Precise rules & defaults

**Residential classification** (step 2):
- Text stems searched (case-insensitive) in `BuildingBasicData.BuildingUseKind.BuildingUseKindName` and `BuildingTypeData.BuildingKind.BuildingKindName`: `māja`, `dzīvojam`, `dzīvokļ`.
- Building-kind ID prefixes accepted as residential: `1110`, `112`, `113`.

**Historical allowlist** (step 2):
- File: `script_pipeline/historical_cadastre_lookup.csv`.
- Accepted header names: `Kadastra Nr.`, `Kadastra Nr`, `KadastraNr`, `CODE` (or first column).
- Cadastre values are normalized (digits only, padded to 14 characters) before comparison.

**Deduplication** (step 3b):
- Strategy: keep-first per `CODE`.

**Energy-class enrichment** (step 5):
- Default URL: `https://data.gov.lv/dati/dataset/df5908be-3995-4a34-99a7-34e8d454b71b/resource/12b3dd61-42d3-4d28-9862-44e4481939bf/download/majas_energoefektivitates_raditaji.zip`
- Cadastre column candidates: `Objektu_identificejosie_kadastra_apzimejumi`, `cadastrena`.
- Energy-class column candidates: `Ekas_energoefektivitates_klase`, `enef_klase`.
- Reference-area column candidates: `References_platiba_m2`, `lietd_plat`.
- Final quality rule: features missing either `energy_class` or `reference_area_m2` are dropped.

## Field reference (by step)

**Step 1 — fields produced (CSV columns):**
- `BuildingBasicData.BuildingGroundFloors`
- `BuildingBasicData.BuildingUndergroundFloors`
- `BuildingBasicData.BuildingPregCount`
- `BuildingBasicData.BuildingArea`
- `BuildingBasicData.BuildingUseKind.BuildingUseKindName`
- `BuildingTypeData.BuildingKind.BuildingKindId`
- `BuildingTypeData.BuildingKind.BuildingKindName`
- `BuildingOrPremiseGroupExplicationData.TotalArea`
- `BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientArea`
- `BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientAreaDetails.FlatTotalAreaDetails.FlatArea`

**Step 2 — fields added to GeoJSON features:**
- Retained geometry fields: `CODE`, `OBJECTCODE`, `PARCELCODE`, `AREA_SCALE`, `GROUP_CODE`
- `building_data` (array of raw flattened CSV dicts)
- `building_count`, `building_use`, `building_material`, `building_area`
- `building_kind_id`, `building_kind`
- `is_residential`, `residential_match_keyword`, `residential_match_field`
- `building_use_native`, `building_kind_native`, `building_kind_id_native`
- `heavy_light` (light / heavy / mixed)

**Step 3c — fields filled/updated:**
- `source_csv_file`, `building_data_source` (set to `heating_fallback`)
- `manufacture_year`
- Values inside `building_data` entries (area, floor count, etc.)

**Step 4 — fields added:**
- `heat_consumption_timeseries` (per-year/per-month consumption keyed by `CODE`, or `None`)

**Step 5 — fields added:**
- `energy_perf_class`, `energy_class`, `reference_area_m2`
- `manufacture_year` (may overwrite step 3c value)
- `heating_indicator`
- Provenance fields (source CSV name/URL)

## Notes

- Heat enrichment is deterministic and offline: no live API queries during the pipeline. To refresh the REA source data, run `utils/download_rea_all_features.py`.
- To get a trimmed output containing only buildings with heat data, run `utils/filter_only_with_heat_series.py` on the final output.
- `utils/enrich_heat_consumption.py` is the legacy API-based enricher (queries live GeoRiga API per building). Kept for reference; not used by the pipeline.
