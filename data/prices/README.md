# Price data

`smard_de_lu_2024_hourly.csv` contains the full UTC-year 2024 historical hourly wholesale electricity price trace for the Germany/Luxembourg bidding zone.

- Source: SMARD, Bundesnetzagentur
- Market data category: `MM-Name.Markt > MM-Name.Großhandelspreise`
- Data id: `4169`
- Region: `DE-LU`
- Endpoint pattern: `https://www.smard.de/app/chart_data/4169/DE-LU/4169_DE-LU_hour_<week_timestamp>.json`
- Unit: EUR/MWh
- Rows: 8784 hourly entries (`2024-01-01T00:00:00Z` through `2024-12-31T23:00:00Z`)

The downloader is in `scripts/download_smard_prices.py`.
