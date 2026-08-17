"""
Install / load smoke tests (network-free).

Prove the built add-on installs into a real Splunk cleanly: it is enabled, both
modular inputs are registered, their schemes introspect, and nothing in the
add-on failed to import at startup.
"""
from __future__ import annotations

import json

APP = "TA-uk-open-data"
INPUTS = ("carbon_intensity", "nhs_ae")


def test_app_installed_and_enabled(splunk):
    entries = splunk.entries(f"/services/apps/local/{APP}")
    assert entries, f"{APP} is not installed"
    content = entries[0]["content"]
    assert content.get("disabled") in (False, 0, "0"), f"{APP} is disabled: {content.get('disabled')}"


def test_both_modular_inputs_registered(splunk):
    names = {e["name"] for e in splunk.entries("/services/data/modular-inputs")}
    missing = [i for i in INPUTS if i not in names]
    assert not missing, f"modular inputs not registered: {missing} (have: {sorted(names)})"


def test_modinput_schemes_expose_expected_args(splunk):
    # If a script failed to import, Splunk cannot introspect its scheme, so the
    # input-specific argument would be absent. Shape-tolerant: check the JSON.
    expected = {"carbon_intensity": "lookback_days", "nhs_ae": "financial_years"}
    for inp, arg in expected.items():
        data = splunk.get_json(f"/services/data/modular-inputs/{inp}")
        assert arg in json.dumps(data), f"{inp} scheme missing expected arg '{arg}'"


def test_no_startup_import_or_init_errors(splunk):
    # Precise signatures: a failed modular-input init or an import error tied to
    # our scripts. Deliberately does NOT match runtime fetch errors (those are a
    # separate concern covered by the live test).
    spl = (
        'search index=_internal log_level=ERROR '
        '("Unable to initialize modular input \\"carbon_intensity\\"" '
        'OR "Unable to initialize modular input \\"nhs_ae\\"" '
        'OR (("ImportError" OR "ModuleNotFoundError" OR "Traceback") '
        '    AND (carbon_intensity OR nhs_ae OR import_declare_test))) '
        'earliest=-1h'
    )
    hits = splunk.search(spl, earliest="-1h")
    assert not hits, f"startup import/init errors found: {[h.get('_raw', '')[:200] for h in hits[:3]]}"
