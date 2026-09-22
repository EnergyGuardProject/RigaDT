# Data

This folder holds the datasets used by the EnergyGuard Riga's Buildings Digital Twin. The web client (`app.js`) loads them at runtime.

## Contents

| File | Type | Description |
|------|------|-------------|
| `DT_data.geojson` | GeoJSON | Main building dataset, produced by the `data_preprocessing/` pipeline |
| `ikmnea-gaisa-dati-YYYY.MM-daily.json` | JSON | Daily air quality data, one file per month (rolling 12 months), produced by `data_preprocessing/classify_air_quality.py` |
| `Borders of Riga suburbs.csv` | CSV | Boundaries of Riga's suburbs (static file) |
| `meteo_stations.csv` | CSV | Metadata of Latvia's meteorological stations (static file) |
| `meteo_data_DAUGAVGR.csv` | CSV | Hourly meteorological observations for the Daugavgrīva station |
| `meteo_data_RIGASLU.csv` | CSV | Hourly meteorological observations for the Rīga-Universitāte station |
