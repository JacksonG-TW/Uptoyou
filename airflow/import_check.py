"""Build-time check: every `upto` module a DAG runs can be imported where the DAG runs it.

The DAGs run our code two ways, under two interpreters:

- **as a child process**, `[UPTO_PYTHON, "-m", "upto.<module>"]`, under the venv
  (`/opt/upto/venv`). The module name is a string in the DAG file.
- **in Airflow's own process**, `from upto.<module> import ...`, under Airflow's Python with
  `UPTO_SRC` put on `sys.path`.

A module that cannot be imported under the right interpreter fails only when its DAG runs. One
such DAG runs only when a new publication lands, so a classifier that imported the web
framework (absent from the venv) failed every scheduled pass from 2026-08-14 to 2026-10-10.
This script fails the image build instead.

    python import_check.py <dags dir> <src dir> child     # under the venv
    python import_check.py <dags dir> <src dir> inprocess # under Airflow's Python

The module list is read from the DAG files, never written here, so a DAG that starts a new
module is checked without anyone remembering to add it. A name is taken by its shape: a string
that is exactly a dotted `upto.` name (a docstring or a log line never is), or the module of a
`from upto.<module> import`. A name that no longer exists under `<src dir>` is a finding, not a
skip: a renamed module would otherwise drop out of the list and pass. Exit 1 names each module
that would not import, with its error.
"""

import ast
import importlib
import os
import re
import sys

DOTTED = re.compile(r"upto(\.[A-Za-z_]\w*)+")


def is_module(name, src):
    path = os.path.join(src, *name.split("."))
    return os.path.isfile(path + ".py") or os.path.isfile(os.path.join(path, "__init__.py"))


def modules(dags, src, mode):
    found = set()
    for entry in sorted(os.listdir(dags)):
        if not entry.endswith(".py"):
            continue
        with open(os.path.join(dags, entry), encoding="utf-8") as f:
            tree = ast.parse(f.read(), entry)
        for node in ast.walk(tree):
            if mode == "child" and isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = node.value
            elif mode == "inprocess" and isinstance(node, ast.ImportFrom) and node.module:
                name = node.module
                if name == "upto":
                    # `from upto import checks`: the names are the modules.
                    found.update("upto." + a.name for a in node.names if is_module("upto." + a.name, src))
                    continue
            else:
                continue
            if DOTTED.fullmatch(name):
                found.add(name)
    return sorted(found)


def main():
    dags, src, mode = sys.argv[1:4]
    if mode not in ("child", "inprocess"):
        sys.exit("mode is child or inprocess, not " + mode)
    sys.path.insert(0, src)
    names = modules(dags, src, mode)
    if not names:
        sys.exit("import_check: no upto module found in {} ({}): the reading is broken".format(dags, mode))
    broken = []
    for name in names:
        if not is_module(name, src):
            broken.append("{}: not found under {}".format(name, src))
            continue
        try:
            importlib.import_module(name)
        except Exception as error:  # any failure to import is the finding
            broken.append("{}: {}: {}".format(name, type(error).__name__, error))
    print("import_check ({}, {}): {} module(s), {} would not import: {}".format(
        mode, sys.executable, len(names), len(broken), " ".join(names)))
    for line in broken:
        print("  " + line)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
