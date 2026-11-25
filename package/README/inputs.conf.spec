[carbon_intensity://<name>]
* Modular input that polls the public api.carbonintensity.org.uk API and emits
*   national carbon-intensity events (carbonintensity:national) and the
*   generation-mix breakdown (carbonintensity:generation).
* interval, index are handled by Splunk natively — do not redeclare them here
*   as that triggers "internal argument" startup errors.

lookback_days = <integer>
* Number of days of history to fetch on each run.
* Default: 2

[nhs_ae://<name>]
* Modular input that indexes NHS England monthly A&E attendances from the
*   published CSVs (england.nhs.uk).
* interval, index are handled by Splunk natively — do not redeclare them here.

financial_years = <string>
* Comma-separated financial-year pages to fetch, e.g. 2025-26,2026-27.
* Default: 2025-26,2026-27

[carbon_intensity_regional://<name>]
* Modular input that polls the public api.carbonintensity.org.uk regional API
*   and emits one carbonintensity:regional event per region per finished
*   half-hour period: forecast intensity, intensity band and generation mix
*   (gen_<fuel> percentages).
* interval, index are handled by Splunk natively — do not redeclare them here.

lookback_days = <integer>
* Days of history to fetch on the first run, 1-13 (the API refuses ranges
*   longer than 14 days). Later runs resume from the checkpoint.
* Default: 1

regions = <string>
* Comma-separated region ids to keep: 1-14 are the DNO regions, 15 England,
*   16 Scotland, 17 Wales, 18 GB. Empty keeps all 18.
* Default: (empty)

[nhs_ambulance://<name>]
* Modular input that indexes the NHS England Ambulance Quality Indicators
*   (AmbSYS) monthly time series: one nhs:ambulance:monthly event per
*   organisation (England, region, ambulance trust) per month.
* interval, index are handled by Splunk natively — do not redeclare them here.

since = <string>
* Earliest month to load, YYYY-MM. Empty loads the whole series (from 2017-08).
* Default: (empty)
