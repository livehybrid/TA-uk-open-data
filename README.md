# TA-uk-open-data

**UK Open Data — Carbon Intensity & NHS A&E** — a Splunk add-on (built with the
[UCC framework](https://github.com/splunk/addonfactory-ucc-generator)) that
provides two configurable **modular inputs** for open UK datasets. No API key,
no registration, no external dependencies beyond outbound HTTPS.

| Input | Source | Cadence | Writes |
|-------|--------|---------|--------|
| **Carbon Intensity** | `api.carbonintensity.org.uk` | half-hourly | `carbonintensity:national`, `carbonintensity:generation` |
| **NHS A&E (monthly)** | NHS England A&E statistics CSVs | monthly | `nhs:ae:monthly` |

Both inputs are **idempotent** — they checkpoint what they've already indexed,
so they are safe to run on any interval without creating duplicates.

---

## Compatibility

| Attribute | Value |
|-----------|-------|
| **Add-on version** | 1.0.2 |
| **Tested against** | Splunk Enterprise 10.0, Python 3.9 (real Splunk in Docker, on every CI run) |
| **Python runtime** | 3.9, Splunk's long-term-support runtime |
| **Expected compatible** | Splunk Enterprise and Cloud 9.3+ and 10.x (any release on the Python 3.9 runtime) |
| **Deployment roles** | Standalone, Distributed, Search Head Clustering |
| **AppInspect** | Passes the `cloud`, `future` and `private_victoria` tag sets |

Splunk 9.3 through 10.1 default to Python 3.9, and 3.9 stays the LTS runtime on
10.2 and later, so an add-on that is clean on 3.9 runs unchanged across that
whole range. This add-on is validated on 3.9 and pins its vendored libraries to
versions that stay 3.9-clean. It is not yet validated on the opt-in Python 3.13
runtime introduced in Splunk 10.2.

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

---

## Verify data is flowing

```spl
| tstats count where index=carbonintensity by sourcetype
search index=carbonintensity sourcetype=carbonintensity:national | head 5
search index=nhsengland sourcetype=nhs:ae:monthly | stats dc(period) as months max(period) as latest
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

`globalConfig.json` defines the UI/inputs; `package/bin/carbon_intensity.py` and
`package/bin/nhs_ae.py` are the modular input implementations. CI builds, runs
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

## License
Apache-2.0.
