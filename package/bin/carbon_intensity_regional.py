import import_declare_test  # noqa: F401  (path bootstrap — must be first)

import json
import os
import sys
import time

from splunklib.modularinput import Argument, Event, EventWriter, Scheme, Script

from carbon_intensity import API, _epoch, _get, _iso

ST_REGIONAL = "carbonintensity:regional"
# The regional endpoint refuses a range longer than 14 days.
MAX_LOOKBACK_DAYS = 13
ALL_REGIONS = tuple(range(1, 19))


def parse_regions(value):
    """'1, 13,18' -> (1, 13, 18). Empty or 'all' -> every region (1-18)."""
    text = str(value or "").strip().lower()
    if text in ("", "all"):
        return ALL_REGIONS
    ids = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)
        if n not in ALL_REGIONS:
            raise ValueError("region id %d is not 1-18" % n)
        if n not in ids:
            ids.append(n)
    return tuple(ids) or ALL_REGIONS


def region_events(payload, checkpoint, now, regions):
    """Yield (from_epoch, event_dict) for each wanted region in each finished period.

    Only periods that have ended are emitted, so each is written once: the
    current half hour is left for the next run.
    """
    wanted = set(regions)
    for period in payload.get("data") or []:
        fe = _epoch(period["from"])
        te = _epoch(period["to"])
        if fe <= checkpoint or te > now:
            continue
        for region in period.get("regions") or []:
            if region.get("regionid") not in wanted:
                continue
            intensity = region.get("intensity") or {}
            body = {
                "from": period["from"], "to": period["to"],
                "regionid": region.get("regionid"), "shortname": region.get("shortname"),
                "dnoregion": region.get("dnoregion"),
                "forecast": intensity.get("forecast"), "carbon_index": intensity.get("index"),
            }
            for mix in region.get("generationmix") or []:
                if mix.get("fuel"):
                    body["gen_" + str(mix["fuel"])] = mix.get("perc")
            yield fe, body


class CarbonIntensityRegional(Script):
    def get_scheme(self):
        scheme = Scheme("Carbon Intensity (regional)")
        scheme.description = ("Index regional carbon intensity and generation mix for the 14 GB "
                              "DNO regions, England, Scotland, Wales and GB from api.carbonintensity.org.uk.")
        scheme.use_external_validation = False
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False
        # Do not declare index/interval here: splunkd supplies them and rejects
        # the kind if they are redeclared (see carbon_intensity.py).
        for name, desc in (
            ("lookback_days", "Days of history to fetch on the first run (1-13)."),
            ("regions", "Comma-separated region ids (1-18); empty for all."),
        ):
            arg = Argument(name)
            arg.data_type = Argument.data_type_string
            arg.description = desc
            arg.required_on_create = False
            scheme.add_argument(arg)
        return scheme

    def _checkpoint_path(self, inputs, name):
        d = inputs.metadata.get("checkpoint_dir", ".")
        safe = name.replace("://", "_").replace("/", "_")
        return os.path.join(d, "carbon_regional_%s.json" % safe)

    def _load_cp(self, path):
        try:
            with open(path) as f:
                return int(json.load(f).get("last_from", 0))
        except Exception:
            return 0

    def _save_cp(self, path, last_from):
        try:
            with open(path, "w") as f:
                json.dump({"last_from": last_from}, f)
        except Exception:
            pass

    def stream_events(self, inputs, ew):
        for name, item in inputs.inputs.items():
            index = str(item.get("index") or "carbonintensity")
            try:
                lookback = max(1, min(MAX_LOOKBACK_DAYS, int(float(item.get("lookback_days") or 1))))
                regions = parse_regions(item.get("regions"))
            except (TypeError, ValueError) as exc:
                ew.log(EventWriter.ERROR, "carbon_intensity_regional[%s] bad setting: %s" % (name, exc))
                continue

            cp_path = self._checkpoint_path(inputs, name)
            checkpoint = self._load_cp(cp_path)
            now = int(time.time())
            # The API returns the period that contains `from`, so asking from
            # the checkpoint itself is safe: that period is skipped below.
            start = max(checkpoint, now - lookback * 86400)
            frm, to = _iso(start), _iso(now)
            emitted, newest = 0, checkpoint
            try:
                payload = _get("%s/regional/intensity/%s/%s" % (API, frm, to))
                for fe, body in region_events(payload, checkpoint, now, regions):
                    ev = Event()
                    ev.stanza = name
                    ev.sourceType = ST_REGIONAL
                    ev.index = index
                    ev.time = "%d" % fe
                    ev.data = json.dumps(body)
                    ew.write_event(ev)
                    emitted += 1
                    newest = max(newest, fe)
            except Exception as exc:
                ew.log(EventWriter.ERROR, "carbon_intensity_regional[%s] fetch/index failed: %s" % (name, exc))
                continue
            if newest > checkpoint:
                self._save_cp(cp_path, newest)
            ew.log(EventWriter.INFO, "carbon_intensity_regional[%s] emitted %d events (index=%s, window %s..%s)"
                   % (name, emitted, index, frm, to))


if __name__ == "__main__":
    sys.exit(CarbonIntensityRegional().run(sys.argv))
