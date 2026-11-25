# TA-uk-open-data

**UK Open Data — Carbon Intensity & NHS A&E** — a Splunk add-on (built with the
[UCC framework](https://github.com/splunk/addonfactory-ucc-generator)) that
provides four configurable **modular inputs** for open UK datasets. No API key,
no registration, no external dependencies beyond outbound HTTPS.

| Input | Source | Cadence | Writes |
|-------|--------|---------|--------|
| **Carbon Intensity** | `api.carbonintensity.org.uk` | half-hourly | `carbonintensity:national`, `carbonintensity:generation` |
| **Carbon Intensity (regional)** | `api.carbonintensity.org.uk/regional` | half-hourly | `carbonintensity:regional` |
| **NHS A&E (monthly)** | NHS England A&E statistics CSVs | monthly | `nhs:ae:monthly` |
| **NHS Ambulance (monthly)** | NHS England Ambulance Quality Indicators (AmbSYS) CSV | monthly | `nhs:ambulance:monthly` |

All inputs are **idempotent** — they checkpoint what they've already indexed,
so they are safe to run on any interval without creating duplicates.

---

## Compatibility

| Attribute | Value |
|-----------|-------|
| **Add-on version** | 1.0.2 |
| **Tested against** | Splunk Enterprise 10.0 (Python 3.9) and 10.6 (Python 3.13), real Splunk in Docker, on every CI run |
| **Python runtime** | 3.13 on Splunk 10.2 and later, 3.9 on Splunk 10.1 and earlier |
| **Expected compatible** | Splunk Enterprise and Cloud 9.3+ and 10.x |
| **Deployment roles** | Standalone, Distributed, Search Head Clustering |
| **AppInspect** | Passes the `cloud`, `future` and `private_victoria` tag sets |

Splunk 10.2 and later ship Python 3.9 and 3.13 side by side; this add-on sets
`python.required = 3.13`, so it runs on 3.13 there. Splunk 10.1 and earlier
ignore `python.required` and run it on 3.9 (`python.version = python3`), so the
code and vendored libraries stay 3.9-compatible (`requests < 2.33`,
`splunk-sdk < 3`). CI runs the integration tests on Splunk 10.0 (Python 3.9)
and 10.6 (Python 3.13) to hold both.

---

## Installation

1. In Splunk Web: **Apps → Manage Apps → Install app from file** and upload
   `TA-uk-open-data-<version>.tar.gz`.
2. Restart Splunk when prompted (a new modular input requires a restart to register).
3. Open the **UK Open Data — Carbon Intensity & NHS A&E** app from the app menu.

> The destination indexes (`carbonintensity`, `nhsengland`) are **not** created
> by this add-on. Create them first (Settings → Indexes) or point the inputs at
> indexes you already have.

---

## Configuration

### Configuration tab → Logging
| Field | Default | Notes |
|-------|---------|-------|
| Log level | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`. Logs go to `$SPLUNK_HOME/var/log/splunk/ta_uk_open_data_*.log`. |

### Inputs tab → **Carbon Intensity**
| Field | Default | Notes |
|-------|---------|-------|
| Name | — | Unique input name (letters, digits, underscores). |
| Interval (s) | `1800` | Poll interval. 1800 (30 min) matches the API's half-hourly settlement periods. |
| Index | `carbonintensity` | Destination index. |
| Lookback (days) | `2` | Each run fetches the last N days and indexes only periods past the checkpoint. Increase for a larger first-run backfill (max 30). |

On each run it calls `GET /intensity/{from}/{to}` and `GET /generation/{from}/{to}`
and emits one event per half-hourly settlement period:

```json
// carbonintensity:national  (_time = period "from")
{"from":"2026-06-02T13:30Z","to":"2026-06-02T14:00Z","forecast":141,"actual":138,"carbon_index":"moderate"}
// carbonintensity:generation (one event per fuel)
{"from":"2026-06-02T13:30Z","fuel":"wind","perc":17}
```

The checkpoint tracks the latest **settled** period (one with a non-null
`actual`), so the most recent forecast-only periods are re-emitted once until
their actual value settles — then never again.

### Inputs tab → **NHS A&E (monthly)**
| Field | Default | Notes |
|-------|---------|-------|
| Name | — | Unique input name. |
| Interval (s) | `86400` | Check interval. NHS publishes monthly (~6 weeks in arrears), so daily is plenty. |
| Index | `nhsengland` | Destination index. |
| Financial years | `2025-26,2026-27` | Comma-separated NHS financial-year pages to scan for monthly CSVs. Add the next FY when it opens. |

It scans the NHS England *"A&E Attendances and Emergency Admissions"* pages for
each financial year, finds the monthly CSV for any month it hasn't loaded,
downloads and parses it, and emits one event per provider plus the national
`TOTAL` row (`_time` = first of the month):

```json
{"period":"2026-04","org_code":"RJ6","org_name":"CROYDON HEALTH SERVICES NHS TRUST",
 "region":"NHS ENGLAND LONDON","type1_attendances":13405,"type1_over4hrs":3841,
 "type1_within4hr_pct":71.3,"type2_attendances":0,"other_attendances":5222,"total_attendances":18627}
```

`type1_within4hr_pct` is derived: `round(100 · (type1_attendances − type1_over4hrs) / type1_attendances, 1)`.

Each event also carries the rest of the CSV: booked appointments
(`type1_booked_attendances`, `type2_booked_attendances`, `other_booked_attendances`), every
over-4-hour count (`type2_over4hrs`, `other_over4hrs`, `type1_booked_over4hrs`,
`type2_booked_over4hrs`, `other_booked_over4hrs`), the decision-to-admit waits
(`dta_4to12hr_waits`, `dta_12hr_plus_waits`, the "trolley waits") and emergency admissions
(`emergency_admissions_type1`, `emergency_admissions_type2`, `emergency_admissions_other`,
`other_emergency_admissions`). From those it derives the NHS headline figures, which include
booked appointments: `all_attendances`, `all_over4hrs` and
`all_within4hr_pct = round(100 · (all_attendances − all_over4hrs) / all_attendances, 1)`.
`total_attendances` keeps its old meaning (types 1, 2 and other, without booked appointments).

### Inputs tab → **Carbon Intensity (regional)**
| Field | Default | Notes |
|-------|---------|-------|
| Name | — | Unique input name. |
| Interval (s) | `1800` | Poll interval. |
| Index | `carbonintensity` | Destination index. |
| Lookback (days) | `1` | History on the first run, 1-13 (the regional API refuses more than 14 days). |
| Regions | (all) | Comma-separated region ids: 1-14 the DNO regions (1 North Scotland ... 13 London, 14 South East England), 15 England, 16 Scotland, 17 Wales, 18 GB. |

It calls `GET /regional/intensity/{from}/{to}` and emits one event per region per
**finished** half-hour period (the current period waits for the next run, so each is
written once). The regional API publishes a forecast only, no actual:

```json
// carbonintensity:regional  (_time = period "from")
{"from":"2026-11-24T12:00Z","to":"2026-11-24T12:30Z","regionid":13,"shortname":"London",
 "dnoregion":"UKPN London","forecast":211,"carbon_index":"high",
 "gen_gas":44.1,"gen_wind":21.3,"gen_nuclear":8.8,"gen_imports":7.9,"gen_biomass":4.3,"gen_solar":0.6, ...}
```

### Inputs tab → **NHS Ambulance (monthly)**
| Field | Default | Notes |
|-------|---------|-------|
| Name | — | Unique input name. |
| Interval (s) | `86400` | Check interval. NHS publishes monthly. |
| Index | `nhsengland` | Destination index. |
| Since (YYYY-MM) | (all) | Earliest month to load. Empty loads the whole series from August 2017 (about 2,100 events). |

It finds the current AmbSYS CSV on the NHS England *Ambulance Quality Indicators*
page and emits one event per organisation (England, NHS region, ambulance trust)
per month it has not loaded yet (`_time` = first of the month). Times are seconds.
Indicators NHS England leaves blank (`.`) are null.

```json
{"period":"2026-10","region":"Eng","org_code":"Eng","org_name":"England",
 "calls_999":941192,"call_answer_mean_s":8,"call_answer_90th_s":23,"incidents":869421,
 "c1_incidents":85267,"c1_mean_s":479,"c1_90th_s":865,"c2_mean_s":1965,"c2_90th_s":4034,
 "c3_mean_s":7652,"c3_90th_s":18177,"c4_mean_s":9615,"c4_90th_s":24062,
 "hear_and_treat":190993,"see_and_treat":247513,"conveyed_to_ed":391044,"conveyed_not_ed":39871,
 "handover_mean_s":1931,"handover_90th_s":4110,"handovers_over_30min":120111,"handovers_over_60min":36624,
 "indicators":{"A0":...,"A1":941192, ...}}
```

The named fields are the headline indicators (category 1-4 mean and 90th centile
response, 999 call answering, outcomes, hospital handovers). `indicators` holds
every AmbSYS code NHS England published for that row, named as in its
[indicator list](https://www.england.nhs.uk/statistics/statistical-work-areas/ambulance-quality-indicators/).

---

## Verify data is flowing

```spl
| tstats count where index=carbonintensity by sourcetype
search index=carbonintensity sourcetype=carbonintensity:national | head 5
search index=nhsengland sourcetype=nhs:ae:monthly | stats dc(period) as months max(period) as latest
search index=carbonintensity sourcetype=carbonintensity:regional | stats latest(forecast) by shortname
search index=nhsengland sourcetype=nhs:ambulance:monthly org_code=Eng | timechart span=1mon latest(c1_mean_s)
```

Check input health in **Settings → Data inputs → Carbon Intensity / NHS A&E**,
and the add-on logs:

```
index=_internal source=*ta_uk_open_data_carbon_intensity.log*
index=_internal source=*ta_uk_open_data_nhs_ae.log*
```

---

## Building from source

```bash
pip install splunk-add-on-ucc-framework
cd TA-uk-open-data
ucc-gen build --source package --ta-version <version>     # -> output/TA-uk-open-data
ucc-gen package --path output/TA-uk-open-data -o .         # -> TA-uk-open-data-<version>.tar.gz
```

`globalConfig.json` defines the UI/inputs; `package/bin/carbon_intensity.py`,
`carbon_intensity_regional.py`, `nhs_ae.py` and `nhs_ambulance.py` are the modular
input implementations. CI builds, runs
AppInspect, and attaches the package to GitHub Releases (see `.github/workflows`).

---

## Notes & limitations

- **Indexes are not auto-created** — create `carbonintensity` and `nhsengland` first.
- **Single-instance off** — inputs run per-stanza; run on a forwarder, indexer, or standalone.
- Carbon Intensity national data legitimately stores a forecast snapshot and a
  later settled snapshot per period; dashboards should take the latest
  (`| sort -_time | head 1` per period, or `avg(actual)` which ignores nulls).
- NHS data is monthly and ~6 weeks in arrears; the input will pick up each new
  month automatically once NHS England publishes it.
- Both NHS inputs remember months, not files: a month NHS England later revises
  is not loaded again.

## License
Apache-2.0.
