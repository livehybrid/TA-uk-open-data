"""
Live end-to-end tests for nhs_ae, carbon_intensity_regional and nhs_ambulance.

Each test creates a real input, lets splunkd run the packaged script against
the public, keyless upstream, and checks what was indexed against what the
upstream publishes. The expectation is built by the test itself: it fetches the
same page or API, parses CSVs with csv.DictReader by exact header name, and
uses a different Carbon Intensity endpoint (per-region) from the collector
(all regions). None of that is the collector's own parsing.

Upstream outages skip rather than fail, as in test_live_carbon_intensity.py:
no events plus the input's own fetch error in splunkd.log means the upstream,
not the add-on, is down.
"""
from __future__ import annotations

import calendar
import csv
import io
import json
import re
import time
import urllib.request

import pytest

UA = {"User-Agent": "Mozilla/5.0 (TA-uk-open-data integration test)"}
INDEX = "main"
APP_NS = "/servicesNS/nobody/TA-uk-open-data/data/inputs"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}

NHS_FY = "2026-27"
NHS_PAGE = ("https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/"
            f"ae-attendances-and-emergency-admissions-{NHS_FY}/")
AMB_PAGE = "https://www.england.nhs.uk/statistics/statistical-work-areas/ambulance-quality-indicators/"
AMB_SINCE = "2025-01"
CI_API = "https://api.carbonintensity.org.uk"


def _fetch(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def _create(splunk, kind, name, **params):
    data = {"name": name, "index": INDEX, "interval": "60", **params}
    st, body = splunk.request("POST", f"{APP_NS}/{kind}", data=data)
    assert st in (200, 201, 409), f"create {kind}/{name} -> {st}: {body[:300]}"
    splunk.request("POST", f"{APP_NS}/{kind}/{name}/enable")


def _delete(splunk, kind, name):
    splunk.request("DELETE", f"{APP_NS}/{kind}/{name}")


def _logged(splunk, kind, name):
    """The input's own EventWriter.log lines (splunkd.log, via ExecProcessor)."""
    rows = splunk.search(f'search index=_internal source=*splunkd.log* "{kind}://{name}" | table _raw',
                         earliest="-30m", count=500)
    return [r.get("_raw", "") for r in rows if f"{kind}[{kind}://{name}]" in r.get("_raw", "")]


def _wait(splunk, spl, done, timeout=300, earliest="-15y", latest="+1d"):
    deadline = time.time() + timeout
    rows = []
    while time.time() < deadline:
        rows = splunk.search(spl, earliest=earliest, latest=latest, count=10000)
        if done(rows):
            return rows
        time.sleep(10)
    return rows


def _skip_if_upstream_down(splunk, kind, name):
    errors = [e for e in _logged(splunk, kind, name) if "failed" in e]
    if errors:
        pytest.skip(f"{kind} ran but the upstream was unreachable: {errors[0][:200]}")


def _runs(splunk, kind, name, needle):
    return [e for e in _logged(splunk, kind, name) if needle in e]


# ---------------------------------------------------------------- NHS A&E

def _nhs_expected():
    """{period: {org_code: DictReader row}} for every monthly CSV on the FY page."""
    html = _fetch(NHS_PAGE, 60)
    out = {}
    for link in dict.fromkeys(re.findall(r'href="([^"]+\.csv)"', html, re.I)):
        rows = list(csv.DictReader(io.StringIO(_fetch(link))))
        data = [r for r in rows if (r.get("Org Code") or "").strip()]
        if not data:
            continue
        m = re.search(r"([A-Za-z]+)-(\d{4})$", data[0]["Period"].strip())
        period = "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])
        out[period] = {r["Org Code"].strip(): r for r in data}
    return out


@pytest.fixture(scope="module")
def nhs(splunk):
    _create(splunk, "nhs_ae", "ci_nhs", financial_years=NHS_FY)
    yield _nhs_expected()
    _delete(splunk, "nhs_ae", "ci_nhs")


NHS_SPL = f'search index={INDEX} source="nhs_ae://ci_nhs" sourcetype="nhs:ae:monthly"'


def _nhs_counts(splunk, expected):
    want = sum(len(v) for v in expected.values())
    rows = _wait(splunk, NHS_SPL + " | spath | stats count dc(org_code) as orgs by period",
                 lambda rs: sum(int(r["count"]) for r in rs) >= want)
    return {r["period"]: (int(r["count"]), int(r["orgs"])) for r in rows}


def test_nhs_ae_ingests_every_month_on_the_page(splunk, nhs):
    assert nhs, "the test found no monthly CSVs on the NHS page"
    got = _nhs_counts(splunk, nhs)
    if not got:
        _skip_if_upstream_down(splunk, "nhs_ae", "ci_nhs")
    want = {p: (len(rows), len(rows)) for p, rows in nhs.items()}
    assert got == want, f"(rows, distinct orgs) by period: got {got}, want {want}"


NHS_FIELDS = {
    "type1_attendances": "A&E attendances Type 1",
    "type2_attendances": "A&E attendances Type 2",
    "other_attendances": "A&E attendances Other A&E Department",
    "type1_booked_attendances": "A&E attendances Booked Appointments Type 1",
    "type2_booked_attendances": "A&E attendances Booked Appointments Type 2",
    "other_booked_attendances": "A&E attendances Booked Appointments Other Department",
    "type1_over4hrs": "Attendances over 4hrs Type 1",
    "type2_over4hrs": "Attendances over 4hrs Type 2",
    "other_over4hrs": "Attendances over 4hrs Other Department",
    "type1_booked_over4hrs": "Attendances over 4hrs Booked Appointments Type 1",
    "type2_booked_over4hrs": "Attendances over 4hrs Booked Appointments Type 2",
    "other_booked_over4hrs": "Attendances over 4hrs Booked Appointments Other Department",
    "dta_4to12hr_waits": "Patients who have waited 4-12 hs from DTA to admission",
    "dta_12hr_plus_waits": "Patients who have waited 12+ hrs from DTA to admission",
    "emergency_admissions_type1": "Emergency admissions via A&E - Type 1",
    "emergency_admissions_type2": "Emergency admissions via A&E - Type 2",
    "emergency_admissions_other": "Emergency admissions via A&E - Other A&E department",
    "other_emergency_admissions": "Other emergency admissions",
}


def test_nhs_ae_total_rows_match_the_csv(splunk, nhs):
    _nhs_counts(splunk, nhs)
    rows = splunk.search(NHS_SPL + ' org_code=TOTAL | table _raw _time', earliest="-15y", latest="+1d", count=100)
    if not rows:
        _skip_if_upstream_down(splunk, "nhs_ae", "ci_nhs")
    events = {json.loads(r["_raw"])["period"]: (json.loads(r["_raw"]), int(float(r["_time"]))) for r in rows}
    assert set(events) == set(nhs), f"TOTAL rows for {sorted(events)}, CSVs for {sorted(nhs)}"
    for period, (ev, ts) in events.items():
        src = nhs[period]["TOTAL"]
        want = {f: int(src[h]) for f, h in NHS_FIELDS.items()}
        got = {f: ev.get(f) for f in NHS_FIELDS}
        assert got == want, f"{period}: TOTAL row differs from the CSV: " + str(
            {f: (got[f], want[f]) for f in want if got[f] != want[f]})
        all_att = sum(want[f] for f in ("type1_attendances", "type2_attendances", "other_attendances",
                                        "type1_booked_attendances", "type2_booked_attendances",
                                        "other_booked_attendances"))
        all_over = sum(want[f] for f in NHS_FIELDS if f.endswith("over4hrs"))
        assert ev["all_attendances"] == all_att and ev["all_over4hrs"] == all_over, ev
        assert abs(ev["all_within4hr_pct"] - 100.0 * (all_att - all_over) / all_att) <= 0.05, ev
        assert time.strftime("%Y-%m", time.gmtime(ts)) == period and ts % 86400 == 0, (period, ts)


def test_nhs_ae_second_run_adds_nothing(splunk, nhs):
    _nhs_counts(splunk, nhs)
    deadline = time.time() + 180
    while time.time() < deadline and not _runs(splunk, "nhs_ae", "ci_nhs", "total new events=0"):
        time.sleep(10)
    assert _runs(splunk, "nhs_ae", "ci_nhs", "total new events=0"), "no second nhs_ae run seen"
    got = _nhs_counts(splunk, nhs)
    want = {p: (len(rows), len(rows)) for p, rows in nhs.items()}
    assert got == want, f"after a second run: got {got}, want {want}"


# ------------------------------------------------------ Carbon (regional)

REG_SPL = 'search index={} source="carbon_intensity_regional://{}" sourcetype="carbonintensity:regional"'


@pytest.fixture(scope="module")
def regional(splunk):
    _create(splunk, "carbon_intensity_regional", "ci_regional", lookback_days="1")
    _create(splunk, "carbon_intensity_regional", "ci_regional_two", lookback_days="1", regions="13, 18")
    yield
    _delete(splunk, "carbon_intensity_regional", "ci_regional")
    _delete(splunk, "carbon_intensity_regional", "ci_regional_two")


def _ci_epoch(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%MZ"))


def _regional_counts(splunk, name, min_periods=40):
    spl = REG_SPL.format(INDEX, name) + " | spath output=pfrom path=from | spath regionid | stats count by pfrom regionid"
    rows = _wait(splunk, spl, lambda rs: len({r["pfrom"] for r in rs}) >= min_periods, earliest="-3d")
    return {(r["pfrom"], int(r["regionid"])): int(r["count"]) for r in rows}


def test_regional_every_region_every_finished_period_once(splunk, regional):
    counts = _regional_counts(splunk, "ci_regional")
    if not counts:
        _skip_if_upstream_down(splunk, "carbon_intensity_regional", "ci_regional")
    periods = sorted({f for f, _ in counts}, key=_ci_epoch)
    assert len(periods) >= 40, f"only {len(periods)} periods"
    starts = [_ci_epoch(p) for p in periods]
    assert all(b - a == 1800 for a, b in zip(starts, starts[1:])), "gap in the half-hour periods"
    assert starts[-1] + 1800 <= time.time(), f"an unfinished period was written: {periods[-1]}"
    by_period = {p: sorted(r for f, r in counts if f == p) for p in periods}
    bad = {p: r for p, r in by_period.items() if r != list(range(1, 19))}
    assert not bad, f"periods without exactly regions 1-18: {dict(list(bad.items())[:3])}"
    dups = {k: v for k, v in counts.items() if v != 1}
    assert not dups, f"duplicated (period, region): {dict(list(dups.items())[:5])}"


def test_regional_matches_the_per_region_endpoint(splunk, regional):
    _regional_counts(splunk, "ci_regional")
    rows = splunk.search(REG_SPL.format(INDEX, "ci_regional") + " regionid=13 | table _raw",
                         earliest="-3d", count=200)
    if not rows:
        _skip_if_upstream_down(splunk, "carbon_intensity_regional", "ci_regional")
    events = {json.loads(r["_raw"])["from"]: json.loads(r["_raw"]) for r in rows}
    # Periods two to four hours old: settled, and inside what was collected.
    now = int(time.time()) // 1800 * 1800
    frm = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now - 4 * 3600))
    to = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now - 2 * 3600))
    ref = json.loads(_fetch(f"{CI_API}/regional/intensity/{frm}/{to}/regionid/13", 30))["data"]
    checked = 0
    for period in ref["data"]:
        ev = events.get(period["from"])
        if ev is None:
            continue
        mix = {"gen_" + m["fuel"]: m["perc"] for m in period["generationmix"]}
        assert ev["shortname"] == ref["shortname"] == "London", ev
        assert ev["forecast"] == period["intensity"]["forecast"], (period["from"], ev, period["intensity"])
        assert ev["carbon_index"] == period["intensity"]["index"], (period["from"], ev)
        assert {k: ev.get(k) for k in mix} == mix, (period["from"], ev, mix)
        checked += 1
    assert checked >= 3, f"only {checked} periods overlapped the reference window {frm}..{to}"


def test_regional_regions_filter(splunk, regional):
    counts = _regional_counts(splunk, "ci_regional_two")
    if not counts:
        _skip_if_upstream_down(splunk, "carbon_intensity_regional", "ci_regional_two")
    assert {r for _, r in counts} == {13, 18}, sorted({r for _, r in counts})


def test_regional_later_runs_add_nothing_twice(splunk, regional):
    _regional_counts(splunk, "ci_regional")
    deadline = time.time() + 180
    while time.time() < deadline and len(_runs(splunk, "carbon_intensity_regional", "ci_regional", "emitted")) < 3:
        time.sleep(10)
    runs = _runs(splunk, "carbon_intensity_regional", "ci_regional", "emitted")
    assert len(runs) >= 3, f"saw {len(runs)} runs"
    counts = _regional_counts(splunk, "ci_regional")
    dups = {k: v for k, v in counts.items() if v != 1}
    assert not dups, f"after {len(runs)} runs, duplicated: {dict(list(dups.items())[:5])}"


# ---------------------------------------------------------- NHS ambulance

AMB_FIELDS = {"A1": "calls_999", "A3": "call_answer_mean_s", "A8": "c1_incidents",
              "A25": "c1_mean_s", "A26": "c1_90th_s", "A31": "c2_mean_s", "A32": "c2_90th_s",
              "A34": "c3_mean_s", "A35": "c3_90th_s", "A37": "c4_mean_s", "A38": "c4_90th_s",
              "A142": "handover_mean_s", "A146": "handovers_over_60min"}
AMB_SPL = f'search index={INDEX} source="nhs_ambulance://ci_amb" sourcetype="nhs:ambulance:monthly"'


@pytest.fixture(scope="module")
def amb(splunk):
    _create(splunk, "nhs_ambulance", "ci_amb", since=AMB_SINCE)
    html = _fetch(AMB_PAGE, 60)
    link = next(u for u in re.findall(r'href="([^"]+\.csv)"', html) if "AmbSYS" in u and "Old-" not in u)
    rows = {}
    for r in csv.DictReader(io.StringIO(_fetch(link))):
        period = "%s-%02d" % (r["Year"], int(r["Month"]))
        if period >= AMB_SINCE:
            rows[(period, r["Org Code"])] = r
    yield rows
    _delete(splunk, "nhs_ambulance", "ci_amb")


def _amb_counts(splunk, want):
    rows = _wait(splunk, AMB_SPL + " | spath | stats count by period org_code",
                 lambda rs: sum(int(r["count"]) for r in rs) >= want)
    return {(r["period"], r["org_code"]): int(r["count"]) for r in rows}


def test_ambulance_every_org_every_month_once(splunk, amb):
    counts = _amb_counts(splunk, len(amb))
    if not counts:
        _skip_if_upstream_down(splunk, "nhs_ambulance", "ci_amb")
    assert set(counts) == set(amb), (
        f"missing {sorted(set(amb) - set(counts))[:5]}, extra {sorted(set(counts) - set(amb))[:5]}")
    assert set(counts.values()) == {1}, {k: v for k, v in counts.items() if v != 1}


def test_ambulance_fields_match_the_csv(splunk, amb):
    _amb_counts(splunk, len(amb))
    rows = splunk.search(AMB_SPL + " org_code=Eng | table _raw _time", earliest="-15y", count=200)
    if not rows:
        _skip_if_upstream_down(splunk, "nhs_ambulance", "ci_amb")
    assert len(rows) == len({p for p, o in amb if o == "Eng"}), len(rows)
    for r in rows:
        ev = json.loads(r["_raw"])
        src = amb[(ev["period"], "Eng")]
        want = {f: (None if src[c].strip() == "." else int(src[c])) for c, f in AMB_FIELDS.items()}
        got = {f: ev.get(f) for f in AMB_FIELDS.values()}
        assert got == want, (ev["period"], {f: (got[f], want[f]) for f in want if got[f] != want[f]})
        assert ev["org_name"] == "England"
        assert time.strftime("%Y-%m", time.gmtime(int(float(r["_time"])))) == ev["period"]


def test_ambulance_since_is_honoured_and_second_run_adds_nothing(splunk, amb):
    _amb_counts(splunk, len(amb))
    deadline = time.time() + 180
    while time.time() < deadline and not _runs(splunk, "nhs_ambulance", "ci_amb", "total new events=0"):
        time.sleep(10)
    assert _runs(splunk, "nhs_ambulance", "ci_amb", "total new events=0"), "no second nhs_ambulance run seen"
    counts = _amb_counts(splunk, len(amb))
    assert min(p for p, _ in counts) >= AMB_SINCE, min(counts)
    assert set(counts) == set(amb) and set(counts.values()) == {1}, "changed after the second run"
