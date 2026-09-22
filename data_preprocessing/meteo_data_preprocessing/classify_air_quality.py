"""
Air Quality Level Classifier

Reads a pollutant dataset in the ikmnea-gaisa-dati-YYYY.MM.json format
(a list of monitoring stations, each with a "noverojumi" list of pollutant
series, each with a "merijumi" list of {"datums", "vertiba"} measurements)
and adds an air quality level to every measurement, based on the fixed
1-hour average thresholds below. Works on any file in this format,
regardless of which month/date it covers.  
Data source: https://data.gov.lv/dati/dataset/ikmenesa-gaisa-kvalitate - Air quality data per month 

Level          PM2.5    PM10     NO2      SO2      O3
Good           0-5      0-15     0-10     0-20     0-60
Fair           6-15     16-45    11-25    21-40    61-100
Moderate       16-50    46-120   26-60    41-125   101-120
Poor           51-90    121-195  61-100   126-190  121-160
Very Poor      91-140   196-270  101-150  191-275  161-180
Extremely Poor >140     >270     >150     >275     >180


Source: https://gmsd.riga.lv/main.php?i_lang=2

Also builds a daily-average dataset from the classified data: one row per
station per day, with each pollutant's daily average and level, plus the
day's overall level (the worst of its pollutant levels) and a
main_pollutant column naming the pollutant that set that worst level.

Usage:
    python classify_air_quality.py <path/to/ikmnea-gaisa-dati-YYYY.MM.json>

Writes <input-name>-levels.json and <input-name>-daily.json in the same
folder as the input file.
"""

import json
import sys
from pathlib import Path

# Each pollutant maps to a list of (upper_bound, level_name) tuples,
# checked in order. The last entry (None) catches everything above
# the previous upper bound ("Extremely Poor").
THRESHOLDS = {
    "PM2.5": [
        (5,   "Good"),
        (15,  "Fair"),
        (50,  "Moderate"),
        (90,  "Poor"),
        (140, "Very Poor"),
        (None, "Extremely Poor"),
    ],
    "PM10": [
        (15,  "Good"),
        (45,  "Fair"),
        (120, "Moderate"),
        (195, "Poor"),
        (270, "Very Poor"),
        (None, "Extremely Poor"),
    ],
    "NO2": [
        (10,  "Good"),
        (25,  "Fair"),
        (60,  "Moderate"),
        (100, "Poor"),
        (150, "Very Poor"),
        (None, "Extremely Poor"),
    ],
    "SO2": [
        (20,  "Good"),
        (40,  "Fair"),
        (125, "Moderate"),
        (190, "Poor"),
        (275, "Very Poor"),
        (None, "Extremely Poor"),
    ],
    "O3": [
        (60,  "Good"),
        (100, "Fair"),
        (120, "Moderate"),
        (160, "Poor"),
        (180, "Very Poor"),
        (None, "Extremely Poor"),
    ],
}

# Maps the "kods" values found in the dataset to the pollutant keys
# used by THRESHOLDS. Series for pollutants with no listed thresholds
# (CO, BEN, heavy metals, etc.) are dropped from the output entirely.
KODS_TO_POLLUTANT = {
    "PM2.5_60min": "PM2.5",
    "PM10_60min": "PM10",
    "NO2": "NO2",
    "SO2": "SO2",
    "O3": "O3",
}

# Fixed pollutant column order used in the daily-average output, and the
# tie-break order when several pollutants share the day's worst level.
POLLUTANT_ORDER = ["PM2.5", "PM10", "NO2", "SO2", "O3"]

# All pollutants share the same ordered level names; take them from PM2.5.
LEVEL_ORDER = [level for _, level in THRESHOLDS["PM2.5"]]


def classify(pollutant, value):
    for upper_bound, level in THRESHOLDS[pollutant]:
        if upper_bound is None or value <= upper_bound:
            return level
    return None


def classify_dataset(data):
    for station in data:
        kept_series = []
        for series in station.get("noverojumi", []):
            pollutant = KODS_TO_POLLUTANT.get(series.get("kods"))
            if pollutant is None:
                continue
            for measurement in series.get("merijumi", []):
                measurement["limenis"] = classify(pollutant, measurement["vertiba"])
            kept_series.append(series)
        station["noverojumi"] = kept_series
    return data


def daily_dataset(data):
    """Mirror the source file's per-station shape (name, geom, one entry
    per pollutant with its unit), but with one row per day per pollutant
    holding the daily average and level, plus the day's overall (worst)
    level and its main_pollutant.
    """
    stations = []
    for station in data:
        values_by_date = {}
        unit_by_pollutant = {}
        for series in station.get("noverojumi", []):
            pollutant = KODS_TO_POLLUTANT.get(series.get("kods"))
            if pollutant is None:
                continue
            unit_by_pollutant[pollutant] = series.get("mervieniba")
            for measurement in series.get("merijumi", []):
                date = measurement["datums"].split(" ")[0]
                values_by_date.setdefault(date, {}).setdefault(pollutant, []).append(
                    measurement["vertiba"]
                )

        days = []
        for date in sorted(values_by_date):
            pollutants_for_date = values_by_date[date]
            day = {"date": date}
            day_levels = {}

            for pollutant in POLLUTANT_ORDER:
                values = pollutants_for_date.get(pollutant)
                if values:
                    average = sum(values) / len(values)
                    level = classify(pollutant, average)
                    day[pollutant] = {
                        "avg": round(average, 2),
                        "unit": unit_by_pollutant.get(pollutant),
                        "level": level,
                    }
                    day_levels[pollutant] = level
                else:
                    day[pollutant] = None

            if day_levels:
                main_pollutant = max(
                    day_levels, key=lambda p: LEVEL_ORDER.index(day_levels[p])
                )
                day["daily_level"] = day_levels[main_pollutant]
                day["main_pollutant"] = main_pollutant
            else:
                day["daily_level"] = None
                day["main_pollutant"] = None

            days.append(day)

        stations.append(
            {
                "station": station.get("nosaukums"),
                "geom": station.get("geom"),
                "days": days,
            }
        )

    return stations


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python classify_air_quality.py <input.json>")

    input_path = Path(sys.argv[1])
    with input_path.open(encoding="utf-8") as f:
        data = json.load(f)

    classify_dataset(data)

    output_path = input_path.with_name(f"{input_path.stem}-levels{input_path.suffix}")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote {output_path}")

    daily_records = daily_dataset(data)
    daily_path = input_path.with_name(f"{input_path.stem}-daily{input_path.suffix}")
    with daily_path.open("w", encoding="utf-8") as f:
        json.dump(daily_records, f, ensure_ascii=False, indent=2)
    print(f"Wrote {daily_path}")


if __name__ == "__main__":
    main()
