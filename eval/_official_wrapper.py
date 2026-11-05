"""Run BIRD's vendored evaluation_ex.py / evaluation_f1.py against our database.

Runs under .venv-official (psycopg2, func_timeout, pymysql). Prints a JSON
list of per-question scores, in question order, to stdout.
Usage: python _official_wrapper.py <ex|f1> <vendored_dir> <dsn> <script args...>
"""
import contextlib
import io
import json
import multiprocessing as mp
import runpy
import sys

metric, vendored, dsn, *script_args = sys.argv[1:]
sys.path.insert(0, vendored)
mp.set_start_method("fork")  # children must inherit the patched connection

import evaluation_utils  # noqa: E402
import psycopg2  # noqa: E402

evaluation_utils.connect_postgresql = lambda: psycopg2.connect(dsn)

script = {"ex": "evaluation_ex.py", "f1": "evaluation_f1.py"}[metric]
sys.argv = [script, *script_args]
with contextlib.redirect_stdout(io.StringIO()) as log:
    globs = runpy.run_path(f"{vendored}/{script}", run_name="__main__")
sys.stderr.write(log.getvalue())
results = sorted(globs["exec_result"], key=lambda r: r["sql_idx"])
print(json.dumps([r["res"] for r in results]))
