# EnergyGuard Riga's Buildings Digital Twin

Riga's Buildings Digital Twin combines multiple data sources into a geospatially enriched visualization of the city's residential building stock, presented through an interactive map interface. Each building is enriched with EPC information, structural and audit data, and continuously updated heating consumption records. City-level historical and real-time meteorological data add further context, since weather is closely tied to energy efficiency.

Users can explore, filter and analyze building performance within the urban context. Beyond visual exploration, export options and API access to the underlying datasets let solution providers integrate building data into their applications, analytics pipelines and decision support tools, supporting AI experimentation and validation in the building sector.


---

## Repository structure

```
Riga-Digital-Twin-/
├── index.html              # Code implementation of the digital twin:
├── app.js                  #   page layout, application logic (data loading,
├── styles.css              #   rendering, filters, popups, charts) and styles
├── data/                   # Datasets used by the digital twin
├── data_preprocessing/     # Preprocessing of the data used
└── riga_data_lake_api/     # API connecting the data to the EnergyGuard data lake
```
