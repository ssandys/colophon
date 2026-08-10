"""Guards for values duplicated across Python, JavaScript, QML, and JSON.

Every assertion here protects something that fails silently when edited on one
side only: a red glyph beside a "0 problems" tooltip, a settings slider that
writes a key nothing reads, a warm that posts to the wrong endpoint. Add to
this file whenever a new value crosses a language boundary.
"""

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import colophon_collect as collect


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as handle:
        return handle.read()


def load_manifest():
    return json.loads(read("manifest.json"))


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
        for name in ("Panel.qml", "Service.qml"):
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
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
        path = os.path.join(ROOT, "Panel.qml")
        if not os.path.exists(path):
            self.skipTest("Panel.qml not written yet")
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
