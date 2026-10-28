import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from analyze_team_graph import analyze_graph


def coupling(a, b, strength):
    return {"a": a, "b": b, "strength": strength, "kind": "shared-file", "evidence": f"{a}/{b}"}


class AnalyzeGraphTests(unittest.TestCase):
    def test_two_strong_pairs_form_proper_subclusters(self):
        result = analyze_graph({
            "tasks": [{"id": task} for task in "abcd"],
            "couplings": [coupling("a", "b", 4), coupling("b", "c", 2), coupling("c", "d", 4)],
        })
        self.assertEqual(result["clusters"], [{
            "id": "C01", "tasks": list("abcd"), "subclusters": [
                {"id": "C01.S01", "tasks": ["a", "b"]},
                {"id": "C01.S02", "tasks": ["c", "d"]},
            ],
        }])
        self.assertEqual(result["task_to_leaf"], {"a": "C01.S01", "b": "C01.S01", "c": "C01.S02", "d": "C01.S02"})

    def test_weak_dependency_preserved_across_root_groups(self):
        result = analyze_graph({
            "tasks": [{"id": "a"}, {"id": "b"}, {"id": "c", "depends_on": ["b"]}, {"id": "d"}],
            "couplings": [coupling("a", "b", 4), coupling("c", "d", 4)],
        })
        self.assertEqual([c["tasks"] for c in result["clusters"]], [["a", "b"], ["c", "d"]])
        self.assertEqual(result["dependency_edges"], [{"from": "b", "to": "c"}])
        edge = next(edge for edge in result["affinity_edges"] if (edge["a"], edge["b"]) == ("b", "c"))
        self.assertEqual(edge, {"a": "b", "b": "c", "weight": 1, "kinds": ["dependency"], "evidence": ["predecessor output"]})

    def test_isolated_dense_and_singleton_only_splits_have_no_nesting(self):
        for edges in ([], [coupling("a", "b", 4), coupling("b", "c", 4)],
                      [coupling("a", "b", 2), coupling("b", "c", 2)]):
            with self.subTest(edges=edges):
                result = analyze_graph({"tasks": [{"id": task} for task in "abc"], "couplings": edges})
                self.assertTrue(all(not cluster["subclusters"] for cluster in result["clusters"]))
                self.assertEqual(set(result["task_to_leaf"]), set("abc"))

    def test_duplicate_pairs_use_max_and_preserve_evidence(self):
        result = analyze_graph({
            "tasks": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}],
            "couplings": [coupling("b", "a", 4), {"a": "a", "b": "b", "strength": 2, "kind": "interface", "evidence": "API"}],
        })
        self.assertEqual(result["affinity_edges"], [{
            "a": "a", "b": "b", "weight": 4, "kinds": ["dependency", "interface", "shared-file"],
            "evidence": ["API", "b/a", "predecessor output"],
        }])

    def test_thresholds_are_inclusive_and_mixed_children_are_retained(self):
        result = analyze_graph({
            "tasks": [{"id": task} for task in "abc"],
            "couplings": [coupling("a", "b", 6), coupling("b", "c", 5)],
        }, cluster_threshold=5, subcluster_threshold=6)
        self.assertEqual(result["thresholds"], {"cluster": 5, "subcluster": 6})
        self.assertEqual(result["clusters"][0]["subclusters"], [
            {"id": "C01.S01", "tasks": ["a", "b"]},
            {"id": "C01.S02", "tasks": ["c"]},
        ])

    def test_order_invariant_and_every_task_has_exactly_one_leaf(self):
        data = {"tasks": [{"id": "z", "depends_on": ["b", "a"]}, {"id": "b"}, {"id": "a"}],
                "couplings": [coupling("z", "b", 4), coupling("a", "b", 2)]}
        result = analyze_graph(data)
        reordered = {"tasks": list(reversed(data["tasks"])), "couplings": list(reversed(data["couplings"]))}
        reordered["tasks"][-1] = {"id": "z", "depends_on": ["a", "b"]}
        self.assertEqual(result, analyze_graph(reordered))
        leaves = [leaf for root in result["clusters"] for leaf in (root["subclusters"] or [root])]
        tasks = [task for leaf in leaves for task in leaf["tasks"]]
        self.assertEqual(sorted(tasks), ["a", "b", "z"])
        for leaf in leaves:
            for task in leaf["tasks"]:
                self.assertEqual(result["task_to_leaf"][task], leaf["id"])

    def test_invalid_schema_and_graphs(self):
        invalid = [None, [], {}, {"tasks": []}, {"tasks": {}}, {"tasks": [None]},
                   {"tasks": [{"id": " "}]}, {"tasks": [{"id": 1}]},
                   {"tasks": [{"id": "a"}, {"id": "a"}]},
                   {"tasks": [{"id": "a", "depends_on": "b"}]},
                   {"tasks": [{"id": "a", "depends_on": ["missing"]}]},
                   {"tasks": [{"id": "a", "depends_on": ["a"]}]},
                   {"tasks": [{"id": "a"}, {"id": "b", "depends_on": ["a", "a"]}]},
                   {"tasks": [{"id": "a", "depends_on": [3]}]},
                   {"tasks": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]},
                   {"tasks": [{"id": "a"}], "couplings": {}},
                   {"tasks": [{"id": "a"}], "couplings": [None]}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, r".+"):
                analyze_graph(data)

    def test_invalid_couplings(self):
        base = coupling("a", "b", 2)
        changes = [{"a": "missing"}, {"b": "a"}, {"a": []}, {"strength": True}, {"strength": "2"},
                   {"strength": 0}, {"strength": -1}, {"strength": float("nan")},
                   {"strength": float("inf")}, {"kind": " "}, {"kind": 1}, {"evidence": ""}, {"evidence": []}]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, r"couplings\[0\]"):
                analyze_graph({"tasks": [{"id": "a"}, {"id": "b"}], "couplings": [dict(base, **change)]})
        for key in base:
            bad = dict(base)
            del bad[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                analyze_graph({"tasks": [{"id": "a"}, {"id": "b"}], "couplings": [bad]})

    def test_invalid_thresholds(self):
        for cluster, sub in [(0, 3), (-1, 3), (2, 2), (3, 2), (True, 3), (2, False),
                             (float("nan"), 3), (2, float("inf")), ("2", 3)]:
            with self.subTest(cluster=cluster, sub=sub), self.assertRaisesRegex(ValueError, "threshold"):
                analyze_graph({"tasks": [{"id": "a"}]}, cluster, sub)

    def test_cli_success_and_errors(self):
        script = Path(__file__).with_name("analyze_team_graph.py")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "tasks.json"
            source.write_text(json.dumps({"tasks": [{"id": "a"}]}))
            result = subprocess.run([sys.executable, str(script), str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["task_to_leaf"], {"a": "C01"})
            for args in (["--cluster-threshold", "nan"], ["--subcluster-threshold", "1"]):
                failed = subprocess.run([sys.executable, str(script), str(source), *args], capture_output=True, text=True)
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(failed.stdout, "")
                self.assertIn("threshold", failed.stderr)
            source.write_text("{")
            failed = subprocess.run([sys.executable, str(script), str(source)], capture_output=True, text=True)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(failed.stdout, "")
            self.assertIn("error", failed.stderr.lower())
            missing = subprocess.run([sys.executable, str(script), str(source.with_name("missing.json"))],
                                     capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(missing.stdout, "")
            self.assertIn("missing.json", missing.stderr)


if __name__ == "__main__":
    unittest.main()
