"""
Live end-to-end test for the carbon_intensity modular input.

This is the real integration proof: it creates an actual input in the running
Splunk, lets splunkd schedule and run the packaged script against the public
api.carbonintensity.org.uk API, and asserts that real events are indexed with
the expected extracted fields.

Honest failure semantics:
  * events indexed with fields        -> PASS  (the whole pipeline works)
  * no events, but splunkd logged the input's own upstream fetch error
                                       -> SKIP  (external API unreachable, not us)
  * no events and no error logged      -> FAIL  (the input never ran / is broken)
"""
from __future__ import annotations

import time

import pytest

STANZA = "ci_probe"
INDEX = "main"
NATIONAL_ST = "carbonintensity:national"
GENERATION_ST = "carbonintensity:generation"

# Namespaces to try, in order. `search` is writable by the container's splunk
# user without touching the bind-mounted app dir; the app namespace is a fallback.
CREATE_PATHS = (
    "/servicesNS/nobody/search/data/inputs/carbon_intensity",
    "/servicesNS/nobody/TA-uk-open-data/data/inputs/carbon_intensity",
)

POLL_SECONDS = 240
POLL_INTERVAL = 10


@pytest.fixture(scope="module")
def carbon_input(splunk):
    """Create a short-interval carbon_intensity input; remove it on teardown."""
    used_path = None
    # NB: this modular-input create handler rejects a "disabled" arg on POST
    # ("Argument \"disabled\" is not supported by this handler"). We enable the
    # stanza explicitly below rather than passing disabled=0 here.
    for path in CREATE_PATHS:
        status, body = splunk.request(
            "POST",
            path,
            data={
                "name": STANZA,
                "index": INDEX,
                "interval": "60",
                "lookback_days": "2",
            },
        )
        if status in (200, 201) or (status == 409):  # created, or already exists
            used_path = path
            break
    assert used_path, f"could not create carbon_intensity input (last {status}: {body[:400]})"
    # Ensure it is enabled even if it pre-existed (409).
    splunk.request("POST", f"{used_path}/{STANZA}/enable")

    yield used_path

    splunk.request("DELETE", f"{used_path}/{STANZA}", params={"output_mode": "json"})


def _upstream_error_logged(splunk):
    spl = (
        'search index=_internal source=*splunkd.log* '
        '"carbon_intensity" ("fetch/index failed" OR "ConnectionError" '
        'OR "Max retries" OR "Timeout" OR "Temporary failure in name resolution") '
        'earliest=-15m'
    )
    return bool(splunk.search(spl, earliest="-15m"))


def test_carbon_intensity_events_indexed(splunk, carbon_input):
    deadline = time.time() + POLL_SECONDS
    results = []
    while time.time() < deadline:
        # `| spath` parses each event's JSON `_raw` directly, so field assertions
        # are independent of whether search-time auto-kv (props KV_MODE=json) is
        # in scope for this oneshot context. This is how a dashboard panel reads
        # the payload too, so it tests the real contract deterministically.
        results = splunk.search(
            f'search index={INDEX} sourcetype={NATIONAL_ST} | head 5 | spath',
            earliest="-7d",
        )
        if results:
            break
        time.sleep(POLL_INTERVAL)

    if not results:
        if _upstream_error_logged(splunk):
            pytest.skip("carbon_intensity input ran but the upstream API was unreachable from the runner")
        pytest.fail(
            f"no {NATIONAL_ST} events indexed within {POLL_SECONDS}s and no upstream "
            "error logged — the modular input did not run"
        )

    # Prove Splunk extracted the JSON payload the script emits.
    row = results[0]
    assert any(k in row for k in ("carbon_index", "forecast", "actual")), (
        f"indexed event missing expected carbon-intensity fields: {sorted(row)}"
    )


def test_generation_mix_events_indexed(splunk, carbon_input):
    # The same run also emits the generation-mix sourcetype. Give it a moment;
    # if national landed, generation is written in the same pass.
    deadline = time.time() + 120
    results = []
    while time.time() < deadline:
        results = splunk.search(
            f'search index={INDEX} sourcetype={GENERATION_ST} | head 5 | spath',
            earliest="-7d",
        )
        if results:
            break
        time.sleep(POLL_INTERVAL)

    if not results:
        if _upstream_error_logged(splunk):
            pytest.skip("upstream API unreachable from the runner")
        pytest.fail(f"no {GENERATION_ST} events indexed within 120s")

    assert any(k in results[0] for k in ("fuel", "perc")), (
        f"generation event missing fuel/perc: {sorted(results[0])}"
    )
