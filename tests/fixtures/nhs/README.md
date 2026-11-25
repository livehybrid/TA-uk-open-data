# NHS England snapshot (test fixture)

A copy of the NHS England statistics pages and files the `nhs_ae` and
`nhs_ambulance` inputs read, taken on 25 Nov 2026, laid out by URL path under
`https://www.england.nhs.uk/`. CI serves it from the `mocknhs` container because
www.england.nhs.uk returns an empty response to GitHub-hosted runners.

- `ae-attendances-and-emergency-admissions-2026-27/` and its seven monthly CSVs,
  unchanged.
- `ambulance-quality-indicators/` and the AmbSYS CSV it links to, cut to the
  header and the rows from 2024 onwards to keep the repository small.

Source: NHS England, published under the Open Government Licence v3.0
(https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
