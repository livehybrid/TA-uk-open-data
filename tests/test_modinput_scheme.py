"""
Modular-input scheme execution smoke (network-free).

Runs each packaged input script under Splunk's own Python via `--scheme`. This
proves the vendored libraries (import_declare_test path bootstrap, requests,
splunklib) all import inside the container and the scripts emit a valid scheme
XML, independent of splunkd having scheduled them.
"""
from __future__ import annotations

import re
from xml.sax.saxutils import escape

import pytest

from conftest import docker_exec

APP = "TA-uk-open-data"
SCRIPTS = {
    "carbon_intensity.py": "Carbon Intensity",
    "nhs_ae.py": "NHS A&E (monthly)",
}


@pytest.mark.parametrize("script,title", SCRIPTS.items())
def test_script_emits_scheme(splunk, script, title):
    rc, out, err = docker_exec(
        "/opt/splunk/bin/splunk",
        "cmd",
        "python",
        f"/opt/splunk/etc/apps/{APP}/bin/{script}",
        "--scheme",
    )
    assert rc == 0, f"{script} --scheme exited {rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
    assert "<scheme>" in out, f"{script} did not emit a scheme:\n{out}\n{err}"
    # The scheme is XML, so a title containing & (e.g. "NHS A&E") is emitted as
    # "NHS A&amp;E". Compare against the XML-escaped form, not the raw string.
    assert escape(title) in out, f"{script} scheme missing title '{title}':\n{out}"
    # index/interval/host/source/sourcetype/disabled are supplied by Splunk
    # natively. Declaring any as a scheme argument makes splunkd reject the whole
    # kind at startup ("Endpoint argument '<x>' is an internal argument") so the
    # input never registers. Catch it here in <1s instead of via a much later
    # ModularInputs init failure.
    declared = set(re.findall(r'<arg name="([^"]+)"', out))
    reserved = {"index", "interval", "host", "source", "sourcetype", "disabled", "name"}
    clash = sorted(declared & reserved)
    assert not clash, (
        f"{script} scheme declares reserved arg(s) {clash}; Splunk supplies these "
        f"natively so splunkd will refuse to register the input"
    )
