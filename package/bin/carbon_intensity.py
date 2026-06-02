import import_declare_test  # noqa: F401  (path bootstrap — must be first)

import json
import os
import sys
import time
from calendar import timegm

import requests
from splunklib.modularinput import Argument, Event, EventWriter, Scheme, Script

API = "https://api.carbonintensity.org.uk"
ST_NATIONAL = "carbonintensity:national"
ST_GENERATION = "carbonintensity:generation"


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(epoch))


def _epoch(iso):
    # "2026-05-09T17:30Z"
    return timegm(time.strptime(iso.replace("Z", "GMT"), "%Y-%m-%dT%H:%M%Z"))


def _get(url):
    r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json()


class CarbonIntensity(Script):
    def get_scheme(self):
        scheme = Scheme("Carbon Intensity")
        scheme.description = "Index UK carbon intensity (national + generation mix) from api.carbonintensity.org.uk."
        scheme.use_external_validation = False
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        for name, desc in (
            ("index", "Destination index."),
            ("lookback_days", "Days of history to fetch each run."),
        ):
            arg = Argument(name)
            arg.data_type = Argument.data_type_string
            arg.description = desc
            arg.required_on_create = False
            scheme.add_argument(arg)
        return arg and scheme

    def _checkpoint_path(self, inputs, name):
        d = inputs.metadata.get("checkpoint_dir", ".")
        safe = name.replace("://", "_").replace("/", "_")
        return os.path.join(d, "carbon_%s.json" % safe)

    def _load_cp(self, path):
        try:
            with open(path) as f:
                return json.load(f).get("last_actual_from", 0)
        except Exception:
            return 0

    def _save_cp(self, path, last_actual_from):
        try:
            with open(path, "w") as f:
                json.dump({"last_actual_from": last_actual_from}, f)
        except Exception:
            pass

    def stream_events(self, inputs, ew):
        for name, item in inputs.inputs.items():
            try:
                index = str(item.get("index") or "carbonintensity")
                lookback = max(1, min(30, int(float(item.get("lookback_days") or 2))))
            except (TypeError, ValueError):
                index, lookback = "carbonintensity", 2

            cp_path = self._checkpoint_path(inputs, name)
            checkpoint = self._load_cp(cp_path)
            now = int(time.time())
            start = max(checkpoint, now - lookback * 86400)
            frm, to = _iso(start), _iso(now)

            emitted = 0
            new_last_actual = checkpoint
            try:
                ni = _get("%s/intensity/%s/%s" % (API, frm, to))
                for d in ni.get("data", []):
                    fe = _epoch(d["from"])
                    if fe <= checkpoint:
                        continue
                    it = d.get("intensity", {}) or {}
                    ev = Event()
                    ev.stanza = name
                    ev.sourceType = ST_NATIONAL
                    ev.index = index
                    ev.time = "%d" % fe
                    ev.data = json.dumps({"from": d["from"], "to": d.get("to"),
                                          "forecast": it.get("forecast"), "actual": it.get("actual"),
                                          "carbon_index": it.get("index")})
                    ew.write_event(ev)
                    emitted += 1
                    if it.get("actual") is not None and fe > new_last_actual:
                        new_last_actual = fe

                ge = _get("%s/generation/%s/%s" % (API, frm, to))
                for d in ge.get("data", []):
                    fe = _epoch(d["from"])
                    if fe <= checkpoint:
                        continue
                    for g in (d.get("generationmix") or []):
                        ev = Event()
                        ev.stanza = name
                        ev.sourceType = ST_GENERATION
                        ev.index = index
                        ev.time = "%d" % fe
                        ev.data = json.dumps({"from": d["from"], "fuel": g.get("fuel"), "perc": g.get("perc")})
                        ew.write_event(ev)
                        emitted += 1
            except Exception as exc:
                ew.log(EventWriter.ERROR, "carbon_intensity[%s] fetch/index failed: %s" % (name, exc))
                continue

            if new_last_actual > checkpoint:
                self._save_cp(cp_path, new_last_actual)
            ew.log(EventWriter.INFO, "carbon_intensity[%s] emitted %d events (index=%s, window %s..%s)" % (name, emitted, index, frm, to))


if __name__ == "__main__":
    sys.exit(CarbonIntensity().run(sys.argv))
