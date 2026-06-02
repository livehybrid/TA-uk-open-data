# UK Open Data — Carbon Intensity & NHS A&E — Splunkbase listing copy

> Source of truth for the Splunkbase listing fields. Keep in sync with each release.
> Compatibility: Splunk Enterprise 9.0+ or Splunk Cloud (modular-input add-on, built with the UCC framework).

## Short Description (max 380 chars)

Two modular inputs for open UK datasets, with a configuration UI. Ingests UK Carbon Intensity (api.carbonintensity.org.uk — half-hourly national intensity + generation mix) and NHS England monthly A&E attendance statistics. No API key. Idempotent, checkpoint-based, safe to run on any interval.

## Summary (max 3000 chars)

**UK Open Data** is a UCC-framework add-on that brings two well-known open UK datasets into Splunk with no API key and no external dependencies beyond outbound HTTPS.

**Carbon Intensity** — polls the National Grid ESO Carbon Intensity API (`api.carbonintensity.org.uk`) and indexes, per half-hourly settlement period, the national forecast/actual gCO₂/kWh and intensity band (`carbonintensity:national`) plus the generation mix by fuel type (`carbonintensity:generation`). Ideal for carbon-aware scheduling, ESG dashboards and "greenest time to run" decisions.

**NHS A&E (monthly)** — scans the NHS England "A&E Attendances and Emergency Admissions" pages, downloads each monthly CSV you haven't already loaded, and indexes one event per provider plus a national TOTAL row (`nhs:ae:monthly`) — type 1/2/other attendances, 4-hour performance and over-4hr counts. Great for healthcare performance and public-sector analytics.

Both inputs are **idempotent**: they checkpoint what they've already indexed, so they're safe to run on any interval without creating duplicates. Carbon re-emits only un-settled recent periods until their actual value lands; NHS only loads months it hasn't seen.

Built with the Splunk UCC framework — full configuration UI, per-input index/interval settings, and standard logging.

## Details

Configure inputs under the add-on's UI (or **Settings → Data inputs**).

**Carbon Intensity input** — `interval` (default 1800s / 30 min), `index` (default `carbonintensity`), `lookback_days` (default 2; increase for a larger first-run backfill, max 30). Writes sourcetypes `carbonintensity:national` and `carbonintensity:generation`.

Example event (national):
```json
{"from":"2026-06-02T13:30Z","to":"2026-06-02T14:00Z","forecast":141,"actual":138,"carbon_index":"moderate"}
```

**NHS A&E input** — `interval` (default 86400s / daily; NHS publishes monthly), `index` (default `nhsengland`), `financial_years` (comma-separated, e.g. `2025-26,2026-27`). Writes sourcetype `nhs:ae:monthly`; `type1_within4hr_pct` is derived as `100·(type1_attendances − type1_over4hrs)/type1_attendances`.

Verify:
```spl
| tstats count where index=carbonintensity by sourcetype
search index=nhsengland sourcetype=nhs:ae:monthly | stats dc(period) max(period)
```

## Installation

1. Create the destination indexes first (Settings → Indexes): e.g. `carbonintensity`, `nhsengland`. **The add-on does not create indexes.**
2. Install the add-on (Apps → Install app from file, or Splunkbase).
3. **Restart Splunk** — a new modular input requires a restart to register.
4. Open the add-on, add a **Carbon Intensity** and/or **NHS A&E** input, set the index and interval, and save.

Run on a standalone instance, heavy forwarder, or indexer (single-instance mode is off; one stanza per input).

## Troubleshooting

- **No data after enabling:** confirm Splunk was restarted after install, the input is enabled, and the destination index exists. Check the logs:
  `index=_internal source=*ta_uk_open_data_carbon_intensity.log*` / `*ta_uk_open_data_nhs_ae.log*`.
- **Outbound HTTPS blocked:** the inputs need egress to `api.carbonintensity.org.uk` and `www.england.nhs.uk`; allow these through any proxy/firewall.
- **NHS month missing:** NHS A&E publishes ~6 weeks in arrears; add the relevant year to `financial_years`. Already-loaded months are skipped via checkpoint.
- **Carbon "actual" is null on recent rows:** expected — the latest half-hour is forecast-only and re-emitted with its actual once the period settles.
- **Duplicate events after manual back-fill:** the input checkpoints by period; avoid mixing it with separate one-off loads into the same index/period.
