# Optional endpoint overrides for TA-uk-open-data. Not on the Configuration
# page. Absent or empty means the real public sites.

[nhs]
base_url = <string>
* Replaces https://www.england.nhs.uk in every URL the nhs_ae and
*   nhs_ambulance inputs fetch (the statistics pages and the CSV links on
*   them), e.g. a mirror or an outbound proxy that serves the same paths.
* Must be an http(s) URL. Read on every run.
* Default: (empty, the real site)
