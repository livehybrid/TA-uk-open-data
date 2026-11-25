import import_declare_test  # noqa: F401  (path bootstrap — must be first)

import csv
import io
import json
import os
import re
import sys
from calendar import timegm

from splunklib.modularinput import Argument, Event, EventWriter, Scheme, Script

from run_lock import RunLock

from nhs_ae import _fetch_text

ST = "nhs:ambulance:monthly"
PAGE = "https://www.england.nhs.uk/statistics/statistical-work-areas/ambulance-quality-indicators/"
# The current AmbSYS file is the whole monthly time series since August 2017,
# one row per month per organisation (England, region, ambulance trust).
# "Old-AmbSYS" is the pre-2018 system and is not used.
LINK_RE = re.compile(r'href="([^"]*/AmbSYS-[^"/]*\.csv)"', re.I)

# Indicator codes from NHS England's AmbSYS indicator list. Times are seconds.
HEADLINE = (
    ("A1", "calls_999"),
    ("A3", "call_answer_mean_s"),
    ("A114", "call_answer_90th_s"),
    ("A7", "incidents"),
    ("A8", "c1_incidents"),
    ("A10", "c2_incidents"),
    ("A11", "c3_incidents"),
    ("A12", "c4_incidents"),
    ("A25", "c1_mean_s"),
    ("A26", "c1_90th_s"),
    ("A31", "c2_mean_s"),
    ("A32", "c2_90th_s"),
    ("A34", "c3_mean_s"),
    ("A35", "c3_90th_s"),
    ("A37", "c4_mean_s"),
    ("A38", "c4_90th_s"),
    ("A17", "hear_and_treat"),
    ("A55", "see_and_treat"),
    ("A53", "conveyed_to_ed"),
    ("A54", "conveyed_not_ed"),
    ("A142", "handover_mean_s"),
    ("A143", "handover_90th_s"),
    ("A145", "handovers_over_30min"),
    ("A146", "handovers_over_60min"),
)
PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def _value(text):
    """'479' -> 479, '12.5' -> 12.5, '.' or '' (not supplied) -> None."""
    t = (text or "").strip().replace(",", "")
    if t in ("", ".", "-"):
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return None


def find_csv(html):
    for link in LINK_RE.findall(html):
        if "/Old-AmbSYS" not in link:
            return link
    return None


def parse(raw, skip_periods=(), since=None):
    """Yield (period, event_dict) for every row of an AmbSYS CSV not skipped."""
    reader = csv.DictReader(io.StringIO(raw.lstrip("﻿")))
    for row in reader:
        try:
            period = "%04d-%02d" % (int(row["Year"]), int(row["Month"]))
        except (KeyError, TypeError, ValueError):
            continue
        if period in skip_periods or (since and period < since):
            continue
        body = {"period": period, "region": (row.get("Region") or "").strip(),
                "org_code": (row.get("Org Code") or "").strip(),
                "org_name": (row.get("Org Name") or "").strip()}
        for code, field in HEADLINE:
            body[field] = _value(row.get(code))
        body["indicators"] = {k: _value(v) for k, v in row.items()
                              if k and re.match(r"^A\d+$", k) and _value(v) is not None}
        yield period, body


def month_epoch(period):
    y, m = period.split("-")
    return timegm((int(y), int(m), 1, 0, 0, 0, 0, 0, 0))


class NhsAmbulance(Script):
    def get_scheme(self):
        scheme = Scheme("NHS Ambulance (monthly)")
        scheme.description = ("Index NHS England Ambulance Quality Indicators (AmbSYS): 999 calls, "
                              "category 1-4 response times and handovers, monthly per trust.")
        scheme.use_external_validation = False
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        # Do not declare index/interval here: splunkd supplies them.
        arg = Argument("since")
        arg.data_type = Argument.data_type_string
        arg.description = "Earliest month to load, YYYY-MM. Empty loads the whole series (from 2017-08)."
        arg.required_on_create = False
        scheme.add_argument(arg)
        return scheme

    def _cp_path(self, inputs, name):
        d = inputs.metadata.get("checkpoint_dir", ".")
        return os.path.join(d, "nhs_ambulance_%s.json" % name.replace("://", "_").replace("/", "_"))

    def _load_cp(self, path):
        try:
            with open(path) as f:
                return set(json.load(f).get("loaded", []))
        except Exception:
            return set()

    def _save_cp(self, path, loaded):
        try:
            with open(path, "w") as f:
                json.dump({"loaded": sorted(loaded)}, f)
        except Exception:
            pass

    def stream_events(self, inputs, ew):
        for name, item in inputs.inputs.items():
            lock = RunLock(inputs.metadata.get("checkpoint_dir"), "nhs_ambulance", name)
            if not lock.acquire():
                ew.log(EventWriter.INFO, "nhs_ambulance[%s] another run is still in progress; skipping this one" % name)
                continue
            self._held_locks = getattr(self, "_held_locks", []) + [lock]  # released at process exit
            index = str(item.get("index") or "nhsengland")
            since = str(item.get("since") or "").strip() or None
            if since and not PERIOD_RE.match(since):
                ew.log(EventWriter.ERROR, "nhs_ambulance[%s] since=%r is not YYYY-MM" % (name, since))
                continue
            cp_path = self._cp_path(inputs, name)
            loaded = self._load_cp(cp_path)
            try:
                url = find_csv(_fetch_text(PAGE, 40))
                if not url:
                    ew.log(EventWriter.ERROR, "nhs_ambulance[%s] no AmbSYS CSV link on %s" % (name, PAGE))
                    continue
                raw = _fetch_text(url, 120)
            except Exception as exc:
                ew.log(EventWriter.ERROR, "nhs_ambulance[%s] fetch failed: %s" % (name, exc))
                continue
            new_periods, n = set(), 0
            for period, body in parse(raw, skip_periods=loaded, since=since):
                ev = Event()
                ev.stanza = name
                ev.sourceType = ST
                ev.index = index
                ev.time = "%d" % month_epoch(period)
                ev.data = json.dumps(body)
                ew.write_event(ev)
                if period not in new_periods:
                    # The CSV is in month order: every earlier month is complete.
                    self._save_cp(cp_path, loaded | new_periods)
                    new_periods.add(period)
                n += 1
            loaded |= new_periods
            self._save_cp(cp_path, loaded)
            ew.log(EventWriter.INFO, "nhs_ambulance[%s] total new events=%d, new months=%d, months loaded=%d from %s"
                   % (name, n, len(new_periods), len(loaded), url))


if __name__ == "__main__":
    sys.exit(NhsAmbulance().run(sys.argv))
