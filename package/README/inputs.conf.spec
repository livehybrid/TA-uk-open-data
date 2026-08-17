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
