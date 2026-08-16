import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_manifest():
    with open(os.path.join(ROOT, "manifest.json")) as handle:
        return json.load(handle)


class ManifestTest(unittest.TestCase):
    def test_identity(self):
        manifest = load_manifest()
        self.assertEqual(manifest["id"], "ssandys.colophon")
        self.assertEqual(manifest["kinds"], ["bar-widget"])

    def test_entry_point_exists(self):
        manifest = load_manifest()
        target = manifest["entryPoints"]["barWidget"]
        self.assertTrue(os.path.exists(os.path.join(ROOT, target)))

    def test_defaults_and_schema_agree(self):
        # These two blocks are hand-duplicated in the manifest format. A key in
        # one and not the other, or a default that disagrees, ships a widget
        # whose settings panel writes a value the code never reads.
        widget = load_manifest()["barWidget"]
        defaults = widget["defaults"]
        schema = {}
        for entry in widget["schema"]:
            schema[entry["key"]] = entry
        self.assertEqual(sorted(defaults.keys()), sorted(schema.keys()))
        for key, value in defaults.items():
            self.assertEqual(value, schema[key]["defaultValue"], key)

    def test_every_default_key_is_expected(self):
        expected = [
            "apiBase",
            "contextSize",
            "keepAliveMinutes",
            "notifyServiceDied",
            "pollIntervalIdleSec",
            "pollIntervalOpenSec",
            "pollIntervalRunningSec",
            "showInstalledModels",
        ]
        widget = load_manifest()["barWidget"]
        self.assertEqual(sorted(widget["defaults"].keys()), expected)
