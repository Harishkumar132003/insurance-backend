#!/usr/bin/env python3
"""Zero-dependency test runner.

    venv/bin/python app/services/hybrid/tests/run_tests.py

The repo has no pytest and no test convention, and adding one would mean touching
`requirements.txt`. These tests are written in plain assert/class style, so they run
under pytest unchanged if it ever lands — this runner just makes them work today.
"""
import importlib
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)).rsplit("/app/", 1)[0])

MODULES = ["test_compare", "test_diagnostics", "test_fanout", "test_identifiers"]


def run() -> int:
    passed = failed = 0
    failures: list[tuple[str, str]] = []

    for mod_name in MODULES:
        try:
            mod = importlib.import_module(f"app.services.hybrid.tests.{mod_name}")
        except Exception:
            failures.append((mod_name, traceback.format_exc()))
            failed += 1
            continue

        for cls_name in sorted(vars(mod)):
            cls = getattr(mod, cls_name)
            if not (isinstance(cls, type) and cls_name.startswith("Test")):
                continue
            for meth_name in sorted(vars(cls)):
                if not meth_name.startswith("test_"):
                    continue
                label = f"{mod_name}.{cls_name}.{meth_name}"
                try:
                    getattr(cls(), meth_name)()
                    passed += 1
                    print(f"  ok    {label}")
                except Exception:
                    failed += 1
                    failures.append((label, traceback.format_exc()))
                    print(f"  FAIL  {label}")

    for label, tb in failures:
        print(f"\n{'=' * 70}\n{label}\n{'-' * 70}\n{tb}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
