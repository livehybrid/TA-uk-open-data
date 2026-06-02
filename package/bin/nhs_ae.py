import import_declare_test  # noqa: F401  (path bootstrap — must be first)

import csv
import io
import json
import os
import re
import sys
import time
from calendar import timegm

import requests
from splunklib.modularinput import Argument, Event, EventWriter, Scheme, Script

ST = "nhs:ae:monthly"
BASE = "https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/ae-attendances-and-emergency-admissions-%s/"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
UA = {"User-Agent": "Mozilla/5.0 (TA-uk-open-data NHS A&E modular input)"}


def _num(v):
    try:
        return int(re.sub(r"[^0-9-]", "", str(v)) or 0)
    except ValueError:
        return 0


def _period_from_url(url):
    m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)[-_ ]*(\d{4})", url, re.I)
    if not m:
        return None
    return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])


def _month_epoch(period):  # "2026-04" -> epoch of 2026-04-01
    y, mo = period.split("-")
    return timegm(time.strptime("%s-%s-01" % (y, mo), "%Y-%m-%d"))


class NhsAE(Script):
    def get_scheme(self):
        scheme = Scheme("NHS A&E (monthly)")
        scheme.description = "Index NHS England monthly A&E attendances from the published CSVs."
        scheme.use_external_validation = False
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        for name, desc in (("index", "Destination index."), ("financial_years", "Comma-separated FY pages, e.g. 2025-26,2026-27.")):
            arg = Argument(name)
            arg.data_type = Argument.data_type_string
            arg.description = desc
            arg.required_on_create = False
            scheme.add_argument(arg)
        return scheme

    def _cp_path(self, inputs, name):
        d = inputs.metadata.get("checkpoint_dir", ".")
        return os.path.join(d, "nhs_%s.json" % name.replace("://", "_").replace("/", "_"))

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

    def _csv_links(self, fy):
        try:
            html = requests.get(BASE % fy, headers=UA, timeout=40).text
        except Exception:
            return []
        return list(dict.fromkeys(re.findall(r'href="([^"]+\.csv)"', html, re.I)))

    def _emit_csv(self, url, index, ew, name):
        raw = requests.get(url, headers=UA, timeout=60).text
        rows = list(csv.reader(io.StringIO(raw)))
        if len(rows) < 2:
            return 0, None
        hdr = [h.strip().lower() for h in rows[0]]

        def col(*subs):
            for i, h in enumerate(hdr):
                if all(s in h for s in subs):
                    return i
            return -1
        c_org = col("org", "code")
        c_parent = col("parent")
        c_name = col("org", "name")
        c_t1 = col("attendances", "type 1") if col("attendances", "type 1") >= 0 else col("a&e attendances type 1")
        c_t2 = col("a&e attendances type 2")
        c_other = col("a&e attendances other")
        c_t1o = col("over 4hrs type 1") if col("over 4hrs type 1") >= 0 else col("attendances over 4hrs type 1")
        period = None
        n = 0
        for r in rows[1:]:
            if len(r) <= max(c_org, c_t1o) or not r[c_org].strip() or r[c_org].strip().lower() == "org code":
                continue
            if period is None:
                period = _period_from_url(url) or self._period_from_cell(r[0])
            is_total = r[c_org].strip().upper() == "TOTAL"
            t1, t2, oth, t1o = _num(r[c_t1]), _num(r[c_t2]), _num(r[c_other]), _num(r[c_t1o])
            ev = Event()
            ev.stanza = name
            ev.sourceType = ST
            ev.index = index
            ev.time = "%d" % _month_epoch(period)
            ev.data = json.dumps({
                "period": period, "org_code": r[c_org].strip(),
                "org_name": r[c_name].strip() if c_name >= 0 else "",
                "region": "TOTAL" if is_total else (r[c_parent].strip() if c_parent >= 0 else ""),
                "type1_attendances": t1, "type1_over4hrs": t1o,
                "type1_within4hr_pct": (round(1000 * (t1 - t1o) / t1) / 10) if t1 > 0 else None,
                "type2_attendances": t2, "other_attendances": oth, "total_attendances": t1 + t2 + oth})
            ew.write_event(ev)
            n += 1
        return n, period

    @staticmethod
    def _period_from_cell(cell):
        m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)[-_ ]*(\d{4})", cell, re.I)
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()]) if m else None

    def stream_events(self, inputs, ew):
        for name, item in inputs.inputs.items():
            index = str(item.get("index") or "nhsengland")
            fys = [s.strip() for s in str(item.get("financial_years") or "2025-26,2026-27").split(",") if s.strip()]
            cp_path = self._cp_path(inputs, name)
            loaded = self._load_cp(cp_path)
            total = 0
            for fy in fys:
                for url in self._csv_links(fy):
                    period = _period_from_url(url)
                    if period and period in loaded:
                        continue
                    try:
                        n, period = self._emit_csv(url, index, ew, name)
                        if period:
                            loaded.add(period)
                            total += n
                            ew.log(EventWriter.INFO, "nhs_ae[%s] loaded %s (%d rows) from %s" % (name, period, n, url))
                    except Exception as exc:
                        ew.log(EventWriter.ERROR, "nhs_ae[%s] failed %s: %s" % (name, url, exc))
            self._save_cp(cp_path, loaded)
            ew.log(EventWriter.INFO, "nhs_ae[%s] total new events=%d, months loaded=%d" % (name, total, len(loaded)))


if __name__ == "__main__":
    sys.exit(NhsAE().run(sys.argv))
