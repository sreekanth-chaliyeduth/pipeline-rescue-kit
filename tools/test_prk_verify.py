#!/usr/bin/env python3
"""Synthetic tests for tools/prk-verify.py. Standard library only."""
import os
import tempfile
import unittest

import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("prk_verify", os.path.join(HERE, "prk-verify.py"))
prk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prk)


def write(root, module, class_name, cases):
    path = os.path.join(root, module, "target", "surefire-reports")
    os.makedirs(path, exist_ok=True)
    body = []
    for name, status in cases.items():
        if status == "PASS":
            body.append('<testcase classname="%s" name="%s"/>' % (class_name, name))
        elif status == "FAIL":
            body.append('<testcase classname="%s" name="%s"><failure/></testcase>' % (class_name, name))
        elif status == "ERROR":
            body.append('<testcase classname="%s" name="%s"><error/></testcase>' % (class_name, name))
        else:
            body.append('<testcase classname="%s" name="%s"><skipped/></testcase>' % (class_name, name))
    xml = ('<?xml version="1.0"?><testsuite name="%s" tests="%d">%s</testsuite>'
           % (class_name, len(cases), "".join(body)))
    with open(os.path.join(path, "TEST-%s.xml" % class_name), "w", encoding="utf-8") as fh:
        fh.write(xml)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "base")
        self.cand = os.path.join(self.tmp.name, "cand")

    def tearDown(self):
        self.tmp.cleanup()

    def result(self):
        return prk.compare(prk.load(self.base), prk.load(self.cand))

    def test_exact_parity_passes(self):
        write(self.base, "m", "T", {"a": "PASS", "b": "FAIL"})
        write(self.cand, "m", "T", {"a": "PASS", "b": "FAIL"})
        self.assertEqual(self.result()["verdict"], "PASS")

    def test_previously_passing_now_fails(self):
        write(self.base, "m", "T", {"a": "PASS"})
        write(self.cand, "m", "T", {"a": "FAIL"})
        self.assertEqual(self.result()["verdict"], "FAIL")

    def test_missing_previously_failing_test_fails(self):
        write(self.base, "m", "T", {"a": "PASS", "b": "FAIL"})
        write(self.cand, "m", "T", {"a": "PASS"})
        self.assertEqual(self.result()["verdict"], "FAIL")

    def test_new_failing_test_fails(self):
        write(self.base, "m", "T", {"a": "PASS"})
        write(self.cand, "m", "T", {"a": "PASS", "new": "ERROR"})
        self.assertEqual(self.result()["verdict"], "FAIL")

    def test_new_passing_test_is_addition(self):
        write(self.base, "m", "T", {"a": "PASS"})
        write(self.cand, "m", "T", {"a": "PASS", "new": "PASS"})
        result = self.result()
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["additions"]), 1)

    def test_previously_failing_now_passes_is_improvement(self):
        write(self.base, "m", "T", {"a": "FAIL"})
        write(self.cand, "m", "T", {"a": "PASS"})
        result = self.result()
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["improvements"]), 1)

    def test_skipped_transition_is_reported_not_improvement(self):
        write(self.base, "m", "T", {"a": "SKIPPED"})
        write(self.cand, "m", "T", {"a": "PASS"})
        result = self.result()
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["improvements"]), 0)
        self.assertEqual(len(result["transitions"]), 1)

    def test_duplicate_identity_is_invalid(self):
        write(self.base, "m", "T", {"a": "PASS"})
        write(self.cand, "m", "T", {"a": "PASS"})
        path = os.path.join(self.cand, "m", "target", "surefire-reports")
        with open(os.path.join(path, "TEST-extra.xml"), "w", encoding="utf-8") as fh:
            fh.write('<testsuite name="T"><testcase classname="T" name="a"/></testsuite>')
        self.assertEqual(prk.main([self.base, self.cand]), 2)

    def test_malformed_xml_is_invalid(self):
        write(self.base, "m", "T", {"a": "PASS"})
        path = os.path.join(self.cand, "m", "target", "surefire-reports")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "TEST-bad.xml"), "w", encoding="utf-8") as fh:
            fh.write("<testsuite>")
        self.assertEqual(prk.main([self.base, self.cand]), 2)

    def test_empty_tree_is_invalid(self):
        os.makedirs(self.base, exist_ok=True)
        os.makedirs(self.cand, exist_ok=True)
        self.assertEqual(prk.main([self.base, self.cand]), 2)

    def test_previously_failing_test_skipped_fails(self):
        write(self.base, "m", "T", {"a": "FAIL"})
        write(self.cand, "m", "T", {"a": "SKIPPED"})
        self.assertEqual(self.result()["verdict"], "FAIL")

    def test_missing_test_name_is_invalid(self):
        write(self.base, "m", "T", {"a": "PASS"})
        path = os.path.join(self.cand, "m", "target", "surefire-reports")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "TEST-noname.xml"), "w", encoding="utf-8") as fh:
            fh.write('<testsuite name="T"><testcase classname="T"/></testsuite>')
        self.assertEqual(prk.main([self.base, self.cand]), 2)

    def test_unreadable_xml_is_invalid(self):
        write(self.base, "m", "T", {"a": "PASS"})
        write(self.cand, "m", "T", {"a": "PASS"})
        path = os.path.join(self.cand, "m", "target", "surefire-reports", "TEST-T.xml")
        os.chmod(path, 0)
        try:
            self.assertEqual(prk.main([self.base, self.cand]), 2)
        finally:
            os.chmod(path, 0o644)


if __name__ == "__main__":
    unittest.main()
