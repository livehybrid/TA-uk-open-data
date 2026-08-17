# Integration tests

A real Splunk-in-Docker test layer for TA-uk-open-data. It starts Splunk 10 with
the built add-on mounted, then proves the add-on works against a live instance.

## What it checks

| File | Layer | Network |
| --- | --- | --- |
| `test_install_smoke.py` | App installs + enabled, both modular inputs registered, schemes introspect, no startup import/init errors | none |
| `test_modinput_scheme.py` | Each packaged script runs under Splunk's Python (`--scheme`) — proves vendored libs import in-container | none |
| `test_live_carbon_intensity.py` | Creates a real `carbon_intensity` input, lets splunkd run it against `api.carbonintensity.org.uk`, asserts events are **indexed** with extracted fields | egress |

The live test fails only when *our* pipeline is broken. If the upstream public
API is unreachable from the runner it **skips** (with the reason logged by the
input itself), so a third-party outage never reddens CI falsely.

## Run locally

Requires Docker + `docker compose`, plus `ucc-gen` and `pytest`:

```bash
pip install splunk-add-on-ucc-framework pytest
cd docker
make all        # build -> up (wait for health) -> test -> down
```

Or step by step:

```bash
cd docker
make build      # ucc-gen build -> ../stage/TA-uk-open-data (perms widened for the test container)
make up         # start Splunk, block until the mgmt API is healthy
make test       # pytest ../tests
make logs       # tail splunkd if something fails
make down       # stop + remove
```

## Config (env)

| Var | Default |
| --- | --- |
| `SPLUNK_MGMT_URL` | `https://127.0.0.1:8089` |
| `SPLUNK_USER` | `admin` |
| `SPLUNK_PASSWORD` | `Changeme1!` |
| `SPLUNK_CONTAINER` | `ta_uk_open_data_splunk` |

## CI

Runs as the `integration-test` job in `.github/workflows/splunk-app-ci.yml`
(skipped for Dependabot actors, which have no egress/secrets).
