import unittest, tempfile
from pathlib import Path
from preferences import Store


class PreferencesTests(unittest.TestCase):
    def test_independent_devices_merge_and_same_field_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "preferences.json")
            self.assertEqual(
                s.update({"base": {"saved": None}, "values": {"saved": [123]}})[1], 200
            )
            self.assertEqual(
                s.update(
                    {
                        "base": {"hiddenProjects": None},
                        "values": {"hiddenProjects": ["near"]},
                    }
                )[1],
                200,
            )
            response, status = s.update(
                {"base": {"saved": None}, "values": {"saved": [456]}}
            )
            self.assertEqual(status, 409)
            self.assertEqual(response["values"]["saved"], [123])
            self.assertEqual(
                Store(s.path).snapshot(), {"saved": [123], "hiddenProjects": ["near"]}
            )

    def test_retry_is_idempotent_and_invalid_values_do_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "preferences.json")
            p = {"base": {"saved": None}, "values": {"saved": [123]}}
            self.assertEqual(s.update(p)[1], 200)
            self.assertEqual(s.update(p)[1], 200)
            for value in {
                "saved": ["bad"],
                "projectGroups": {"near": False},
                "unknown": [],
            }.items():
                with self.assertRaises(ValueError):
                    s.update({"base": {value[0]: None}, "values": dict([value])})
            self.assertEqual(s.snapshot(), {"saved": [123]})


if __name__ == "__main__":
    unittest.main()
