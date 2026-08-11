"""Guards for values duplicated across Python, JavaScript, QML, and JSON.

Every assertion here protects something that fails silently when edited on one
side only: a red glyph beside a "0 problems" tooltip, a settings slider that
writes a key nothing reads, a warm that posts to the wrong endpoint. Add to
this file whenever a new value crosses a language boundary.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import colophon_collect as collect


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as handle:
        return handle.read()


def load_manifest():
    return json.loads(read("manifest.json"))


def panel_is_wired():
    """True once Panel.qml has been wired to Service.qml.

    File existence is the WRONG arming condition for a Panel.qml guard:
    Panel.qml exists from the walking-skeleton task onward, so keying on it
    makes the kind guard fail against a skeleton that legitimately has no
    actions yet, AND makes the palette guard pass vacuously against a skeleton
    that has no colors yet. Instantiating Service is the unambiguous marker
    that the real panel has landed.
    """
    if not os.path.exists(os.path.join(ROOT, "Panel.qml")):
        return False
    return re.search(r"^\s*Service\s*\{", read("Panel.qml"), re.M) is not None


class StatusSetTest(unittest.TestCase):
    def test_javascript_statuses_match_python(self):
        # Model.js maps every status to a glyph, a color, and a label. A status
        # Python can emit but Model.js does not know renders as a bare string
        # with a fallback color -- wrong, and invisible in review.
        source = read("Model.js")
        match = re.search(r"var STATUSES = \[(.*?)\]", source, re.S)
        self.assertIsNotNone(match, "STATUSES not found in Model.js")
        js_statuses = set(re.findall(r'"([a-z]+)"', match.group(1)))
        self.assertEqual(js_statuses, set(collect.STATUSES))


class ModelJsSyntaxTest(unittest.TestCase):
    """Model.js must stay inside the ES5 subset both engines accept.

    Nothing else in the suite can catch a violation. `node --test` accepts
    arrow functions, let/const, and template literals without complaint, and
    qmllint cannot resolve Model.js at all. So a banned construct fails only
    in the live shell, at runtime, which is the most expensive place to find
    it -- and the failure mode is a silently dead widget, not an error.
    """

    BANNED = [
        (r"=>", "arrow function"),
        (r"\blet\s", "let"),
        (r"\bconst\s", "const"),
        (r"\.\.\.", "spread"),
        (r"`", "template literal"),
        (r"Object\.assign", "Object.assign"),
        (r"\.includes\(", ".includes("),
        (r"\.endsWith\(", ".endsWith("),
    ]

    @staticmethod
    def code_only(source):
        # Strip comments so prose *about* a banned construct does not trip the
        # guard. Deliberately naive: it would also strip a `//` inside a string
        # literal, which Model.js has none of. If one is ever added, this needs
        # a real tokenizer rather than a looser regex.
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        return re.sub(r"//[^\n]*", "", source)

    def test_model_js_uses_no_banned_syntax(self):
        source = self.code_only(read("Model.js"))
        for pattern, label in self.BANNED:
            with self.subTest(construct=label):
                found = re.search(pattern, source)
                self.assertIsNone(
                    found,
                    "Model.js uses " + label + " -- QML's engine rejects it, "
                    "and neither node nor qmllint will tell you")

    def test_top_level_declarations_are_var_or_function(self):
        # Anything else at top level is the other half of the same rule.
        source = self.code_only(read("Model.js"))
        for line in source.splitlines():
            if not line or line[0].isspace():
                continue
            stripped = line.strip()
            if stripped in ("}", "{") or stripped.startswith("}"):
                continue
            with self.subTest(line=stripped[:60]):
                self.assertTrue(
                    stripped.startswith("var ")
                    or stripped.startswith("function ")
                    or stripped.startswith("if (typeof module"),
                    "unexpected top-level construct: " + stripped[:60])


class BarGlyphTest(unittest.TestCase):
    """The bar glyph must be a non-empty \\uXXXX escape, never a literal glyph.

    U+F2DB is a Nerd Font codepoint in the Unicode Private Use Area, and PUA
    characters do not survive every editing path. This project shipped a
    Panel.qml whose barIcon was an empty string: it parsed cleanly, registered
    its IPC handler, logged nothing, and rendered an invisible bar widget while
    131 tests passed. Nothing else could have caught it. An escape is greppable,
    diffable, and immune to the whole class of loss -- galley writes its glyph
    the same way for the same reason.
    """

    def test_bar_icon_is_a_nonempty_escape(self):
        match = re.search(r'property string barIcon:\s*"([^"]*)"', read("Panel.qml"))
        self.assertIsNotNone(match, "Panel.qml declares no barIcon")
        literal = match.group(1)
        self.assertNotEqual(
            literal, "", "barIcon is empty -- the bar renders nothing at all")
        self.assertRegex(
            literal, r"^\\u[0-9a-fA-F]{4}$",
            "write barIcon as a \\uXXXX escape, not a literal glyph character")


class ColorPaletteTest(unittest.TestCase):
    def hex_literals(self, text):
        return set(match.lower()
                   for match in re.findall(r"#[0-9a-fA-F]{6}", text))

    def model_colors(self):
        source = read("Model.js")
        return self.hex_literals(
            "\n".join(re.findall(r"var COLOR_[A-Z]+ = \"(#[0-9a-fA-F]{6})\"",
                                 source)))

    def test_model_declares_the_galley_palette(self):
        # Colophon reuses galley's palette verbatim so the two plugins do not
        # disagree about what amber means.
        self.assertEqual(self.model_colors(),
                         {"#22c55e", "#eab308", "#ef4444", "#3b82f6"})

    def test_qml_hex_literals_come_from_the_model_palette(self):
        # Panel.qml inlines hex because bar chrome cannot import Model.js in a
        # binding cheaply; this keeps the two from drifting apart.
        if not panel_is_wired():
            self.skipTest("Panel.qml is still the skeleton -- guard would "
                          "pass vacuously against a file with no colors")
        for name in ("Panel.qml", "Service.qml"):
            if not os.path.exists(os.path.join(ROOT, name)):
                self.skipTest(name + " not written yet")
            extra = self.hex_literals(read(name)) - self.model_colors()
            self.assertEqual(extra, set(),
                             name + " uses colors absent from Model.js")


class SettingsDefaultTest(unittest.TestCase):
    def test_service_fallbacks_match_the_manifest_defaults(self):
        # Service.qml calls setting("key", fallback). A fallback that disagrees
        # with the manifest default means the widget behaves one way on a fresh
        # install and another way once the user opens the settings panel.
        path = os.path.join(ROOT, "Service.qml")
        if not os.path.exists(path):
            self.skipTest("Service.qml not written yet")
        source = read("Service.qml")
        defaults = load_manifest()["barWidget"]["defaults"]
        found = dict(re.findall(r'setting\("([A-Za-z]+)",\s*([^)]+)\)', source))
        for key, expected in defaults.items():
            with self.subTest(key=key):
                self.assertIn(key, found,
                              key + " has a manifest default but Service.qml "
                                    "never reads it")
                literal = found[key].strip().rstrip(")").strip()
                if isinstance(expected, bool):
                    self.assertEqual(literal, "true" if expected else "false")
                elif isinstance(expected, int):
                    self.assertEqual(literal, str(expected))
                else:
                    self.assertEqual(literal.strip('"'), expected)


class KindRoutingTest(unittest.TestCase):
    def test_the_embedding_family_list_exists_only_in_python(self):
        # The generate-vs-embed decision is derived once, in the collector, and
        # passed through as --kind. A second copy in JS or QML would be a
        # silent divergence the moment a family is added.
        self.assertTrue(collect.EMBED_FAMILIES)
        for name in ("Model.js", "Panel.qml", "Service.qml"):
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            source = read(name)
            for family in collect.EMBED_FAMILIES:
                self.assertNotIn('"' + family + '"', source,
                                 name + " re-derives the model kind")

    def test_the_panel_passes_kind_through(self):
        if not panel_is_wired():
            self.skipTest("Panel.qml is still the skeleton -- it has no "
                          "actions to pass a kind to yet")
        self.assertIn("kind", read("Panel.qml"),
                      "Panel.qml must pass a model's kind to runAction")


class UnitNameTest(unittest.TestCase):
    def test_the_unit_name_agrees_across_python_and_the_polkit_rule(self):
        # The grant names the unit; the scripts name the unit. Rename one and
        # every action starts failing with a permission error that looks like a
        # missing rule rather than a typo.
        self.assertEqual(collect.UNIT_NAME, "ollama.service")
        rule = read("polkit", "49-colophon-ollama.rules")
        self.assertIn('"ollama.service"', rule)
        action = read("scripts", "colophon_action.py")
        self.assertIn('UNIT_NAME = "ollama.service"', action)

    def test_systemctl_is_always_non_interactive(self):
        action = read("scripts", "colophon_action.py")
        self.assertIn("--no-ask-password", action)


class ShowPropertyTest(unittest.TestCase):
    def test_every_requested_property_is_read_somewhere(self):
        # A property added to the systemctl call but never read is dead weight;
        # one read but never requested is silently always empty.
        source = read("scripts", "colophon_collect.py")
        for prop in collect.SHOW_PROPERTIES:
            with self.subTest(prop=prop):
                uses = len(re.findall(r'"' + prop + r'"', source))
                self.assertGreaterEqual(
                    uses, 2, prop + " is requested but never read")


def node_binary():
    return shutil.which("node")


def empty_snapshot_key_shape():
    """The key set of Model.js's EMPTY_SNAPSHOT, at the top level and at each
    of its three nested object levels (unit/api/summary; loaded/installed
    are arrays with no shape of their own to dump).

    Shelled out to node rather than parsed with a regex: EMPTY_SNAPSHOT is a
    nested JS object literal, and getting that right by hand-rolled pattern
    matching is exactly the kind of thing that would itself be subtly wrong.
    node is already a project dependency (tests/model.test.js runs under
    node --test), so requiring Model.js for real and dumping Object.keys is
    both simpler and more trustworthy than parsing its source as text.
    """
    script = (
        "var Model = require(" + json.dumps(os.path.join(ROOT, "Model.js")) + ");"
        "var s = Model.EMPTY_SNAPSHOT;"
        "process.stdout.write(JSON.stringify({"
        "top: Object.keys(s).sort(),"
        "unit: Object.keys(s.unit).sort(),"
        "api: Object.keys(s.api).sort(),"
        "summary: Object.keys(s.summary).sort()"
        "}));"
    )
    result = subprocess.run([node_binary(), "-e", script],
                            capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise AssertionError("node -e failed: " + result.stderr)
    return json.loads(result.stdout)


class SnapshotSchemaTest(unittest.TestCase):
    """Nothing previously bridged the collector's JSON to Model.js.

    The snapshot schema exists three times: emitted by collect(), mirrored by
    hand in Model.js's EMPTY_SNAPSHOT, and hand-duplicated again in
    tests/model.test.js's RUNNING literal. Renaming sizeBytes to bytes in the
    collector would leave every one of those 132 tests green while the panel
    quietly rendered the wrong thing everywhere that key is read -- exactly
    the class of silent cross-boundary failure this file exists to prevent,
    and, until now, the one boundary it did not actually guard.

    Driven entirely from tests/fixtures via collect.FixtureSource, so it
    needs no live service.
    """

    def setUp(self):
        if not node_binary():
            self.skipTest("node not found on PATH")
        self.shape = empty_snapshot_key_shape()

    def snapshot_for(self, state):
        source = collect.FixtureSource(os.path.join(FIXTURES, state),
                                       "http://127.0.0.1:11434")
        return collect.collect(source, now_sec=5000.0, uptime_sec=1000.0)

    def test_top_level_and_nested_objects_match_empty_snapshot(self):
        for state in ("running", "stopped", "foreign"):
            with self.subTest(state=state):
                snapshot = self.snapshot_for(state)
                self.assertEqual(sorted(snapshot.keys()), self.shape["top"])
                self.assertEqual(sorted(snapshot["unit"].keys()),
                                 self.shape["unit"])
                self.assertEqual(sorted(snapshot["api"].keys()),
                                 self.shape["api"])
                self.assertEqual(sorted(snapshot["summary"].keys()),
                                 self.shape["summary"])

    def test_a_loaded_row_carries_every_key_panel_qml_reads_off_it(self):
        # `running` is the only fixture state that populates `loaded` -- a
        # row object has to exist somewhere before its keys can be checked.
        snapshot = self.snapshot_for("running")
        loaded = snapshot["loaded"]
        self.assertTrue(loaded, "the running fixture must populate loaded")
        row_keys = set(loaded[0].keys())

        panel = read("Panel.qml")
        # Scoped to the LOADED section only: Panel.qml reuses `modelData` as
        # the Repeater loop variable for BOTH the loaded and installed
        # lists, and the two row shapes are genuinely different (a loaded
        # row has no `family`; an installed row has no `expiresAt`).
        # Slicing on the file's own section comments keeps the two separate.
        loaded_text = panel[panel.index("── Loaded models ──"):
                            panel.index("── Installed models ──")]
        referenced = set(re.findall(r"modelData\.([A-Za-z]+)", loaded_text))
        self.assertTrue(referenced, "no modelData.* reads found in the "
                                    "loaded section -- did the markers move?")
        missing = referenced - row_keys
        self.assertEqual(missing, set(),
                         "Panel.qml reads a key off a loaded-model row that "
                         "the collector does not emit: " + str(missing))

    def test_an_installed_row_carries_every_key_panel_qml_reads_off_it(self):
        snapshot = self.snapshot_for("stopped")
        installed = snapshot["installed"]
        self.assertTrue(installed, "the shared models fixture must be "
                                   "non-empty")
        row_keys = set(installed[0].keys())

        panel = read("Panel.qml")
        installed_text = panel[panel.index("── Installed models ──"):]
        referenced = set(re.findall(r"modelData\.([A-Za-z]+)", installed_text))
        self.assertTrue(referenced, "no modelData.* reads found in the "
                                    "installed section -- did the markers "
                                    "move?")
        missing = referenced - row_keys
        self.assertEqual(missing, set(),
                         "Panel.qml reads a key off an installed-model row "
                         "that the collector does not emit: " + str(missing))
