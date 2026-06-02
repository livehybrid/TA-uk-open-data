"""
Path bootstrap for the TA-uk-open-data add-on. Imported at the top of every
script in package/bin/ so the vendored libraries in package/lib/ resolve inside
Splunk's Python runtime.
"""
import os
import re
import sys
from os.path import dirname

ta_name = "TA-uk-open-data"
pattern = re.compile(r"[\\/]etc[\\/]apps[\\/][^\\/]+[\\/]bin[\\/]?$")
new_paths = [p for p in sys.path if not pattern.search(p) or ta_name in p]
new_paths.insert(0, os.path.join(dirname(dirname(__file__)), "lib"))
new_paths.insert(0, os.path.sep.join([os.path.dirname(__file__), ta_name]))
sys.path = new_paths
