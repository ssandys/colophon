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
# Imported under a distinct name: a test further down in this file already
# binds the bare name `action` to file text (read("scripts",
# "colophon_action.py")), and `action` here would silently shadow that local
# rather than erroring -- see UnitNameTest.
import colophon_action as action_mod


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
        #
        # That claim does not extend to every caller, though: ParamSpecTest
        # below reuses this same method to strip Panel.qml's comments, and
        # Panel.qml is not innocent of the pattern -- its `pathFromUrl` has
        # `if (value.indexOf("file://") === 0)`, whose `//` truncates the rest
        # of that line exactly like a real comment would. Harmless today
        # because nothing load-bearing follows it there, but a future line
        # that combines a `//`-bearing string with a numeric literal would
        # have that literal silently vanish from anything reading this
        # method's output, with no error to say so.
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
    """The bar glyph is defined once, in Model.js, and Panel.qml references it.

    U+EE86 is a Nerd Font codepoint in the Unicode Private Use Area, and PUA
    characters do not survive every editing path. This project shipped a
    Panel.qml whose barIcon was an empty string: it parsed cleanly, registered
    its IPC handler, logged nothing, and rendered an invisible bar widget while
    131 tests passed. Nothing else could have caught it. An escape is greppable,
    diffable, and immune to the whole class of loss -- galley writes its glyph
    the same way for the same reason.

    Two assertions, because there are two ways to break it. The value could be
    wrong: empty, a literal character, or a well-formed but different escape --
    "A" fails the shape check, but a typo like "\\uEE85" satisfies both
    non-empty and shape while rendering a different icon, so only exact equality
    catches it. Or Panel.qml could stop referencing the constant and reintroduce
    a literal of its own, which is how the value came to live in four places
    before this test existed.
    """

    BAR_GLYPH = "\\uEE86"   # U+EE86 nf-fa-stamp; see AGENTS.md trap #14

    def model_js_glyph(self):
        match = re.search(r'var BAR_GLYPH = "([^"]*)"', read("Model.js"))
        self.assertIsNotNone(match, "Model.js defines no BAR_GLYPH")
        return match.group(1)

    def test_the_glyph_is_a_nonempty_escape(self):
        literal = self.model_js_glyph()
        self.assertNotEqual(
            literal, "", "BAR_GLYPH is empty -- the bar renders nothing at all")
        self.assertRegex(
            literal, r"^\\u[0-9a-fA-F]{4}$",
            "write BAR_GLYPH as a \\uXXXX escape, not a literal glyph character")

    def test_the_glyph_is_the_intended_codepoint(self):
        self.assertEqual(
            self.model_js_glyph(), self.BAR_GLYPH,
            "BAR_GLYPH is a well-formed escape but not the stamp glyph -- "
            "did a typo or a copy/paste substitute a different codepoint?")

    def test_panel_references_the_constant_rather_than_a_literal(self):
        line = next((l for l in read("Panel.qml").splitlines()
                     if "barIcon" in l and "property" in l), None)
        self.assertIsNotNone(line, "Panel.qml declares no barIcon")
        self.assertIn(
            "Model.BAR_GLYPH", line,
            "Panel.qml must bind barIcon to Model.BAR_GLYPH; a literal here is "
            "how the codepoint came to be duplicated across four files")
        self.assertNotIn(
            '"', line,
            "Panel.qml's barIcon carries a quoted literal again -- the glyph is "
            "defined once, in Model.js")

    def test_the_constant_is_exported_for_the_js_side(self):
        # QML reads Model.js's top-level vars directly and ignores the export
        # block, so a missing export breaks only node -- but that is where the
        # value assertions above run, and a silently unexported constant would
        # make them assert against nothing.
        self.assertIn("BAR_GLYPH: BAR_GLYPH", read("Model.js"))


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
    def test_the_unit_name_agrees_across_python_and_the_collector(self):
        # Rename it in one place and every action fails with an error that
        # reads like a permissions problem rather than a typo.
        self.assertEqual(collect.UNIT_NAME, "ollama.service")
        action = read("scripts", "colophon_action.py")
        self.assertIn('UNIT_NAME = "ollama.service"', action)

    def test_the_prompt_is_never_suppressed_in_the_action_script(self):
        # The sibling assertion in tests/test_action.py checks the constructed
        # argv; this one checks the file, so a flag added anywhere -- a second
        # call site, a helper, a stray copy from galley -- is caught too.
        # Re-adding it converts every authentication dialog into a silent
        # "Access denied".
        #
        # Comments are stripped first, exactly as ModelJsSyntaxTest.code_only
        # does for Model.js: systemctl_command's own comment names the flag in
        # order to explain why it is absent, and prose *about* a banned
        # construct must not trip the guard. The strip is deliberately naive --
        # it would also cut a "#" inside a string literal, of which this file
        # has none.
        source = re.sub(r"#[^\n]*", "", read("scripts", "colophon_action.py"))
        self.assertNotIn("--no-ask-password", source,
            "the flag must not appear anywhere in the action script -- see "
            "docs/superpowers/specs/2026-08-11-prompted-privilege-design.md")


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


class ParamSpecTest(unittest.TestCase):
    """The two parameters and their bounds live in three files. A one-sided
    edit fails silently: the panel would clamp to one range while the script
    refused another, and the user would see a field that will not commit with
    no error explaining why. See AGENTS.md trap #12.

    Narrowed from four parameters to two in task 6b -- top_p and top_k are
    gone from all three surfaces, and KEYS below shrank to match.
    """

    KEYS = ["num_ctx", "temperature"]

    def test_the_parameter_set_agrees_across_all_three_surfaces(self):
        # Comments stripped first, as ModelJsSyntaxTest.code_only does for its
        # own assertions: these very numbers are discussed in Model.js's
        # comments, and a match found only in prose must not satisfy this.
        model_js = ModelJsSyntaxTest.code_only(read("Model.js"))
        # Order matters in Model.js: PARAM_SPECS drives display order.
        found = re.findall(r'\{\s*key:\s*"([a-z_]+)"', model_js)
        self.assertEqual(found, self.KEYS,
                         "Model.PARAM_SPECS must list exactly these two, in "
                         "this order")
        self.assertEqual(sorted(action_mod.PARAM_BOUNDS), sorted(self.KEYS),
                         "colophon_action.PARAM_BOUNDS must cover the same "
                         "set")

    def test_the_bounds_agree_between_javascript_and_python(self):
        model_js = ModelJsSyntaxTest.code_only(read("Model.js"))
        for key, (low, high, _is_int) in action_mod.PARAM_BOUNDS.items():
            spec = re.search(
                r'key:\s*"' + re.escape(key) + r'",\s*label:[^,]+,\s*'
                r'min:\s*([0-9.]+),\s*max:\s*([0-9.]+)', model_js)
            self.assertIsNotNone(
                spec, "no min/max found for " + key + " in Model.js")
            self.assertEqual(float(spec.group(1)), float(low), key)
            self.assertEqual(float(spec.group(2)), float(high), key)

    def test_panel_qml_hardcodes_no_bound(self):
        # PR #6's equivalent guard omitted Panel.qml, so a hardcoded clamp
        # drifted from Model.js with the whole suite green. ColorPaletteTest
        # reads Panel.qml for exactly this reason.
        #
        # Comments stripped first -- QML uses the same // and /* */ syntax as
        # Model.js, so ModelJsSyntaxTest.code_only works unchanged (with the
        # string-literal caveat noted on that method -- Panel.qml's
        # pathFromUrl has a `//` inside a string that this strip mistakes for
        # a comment marker; harmless here since no bound sits on that line).
        # Without stripping, Panel.qml's own comment sizing the num_ctx text
        # field ("the longest thing any field can hold (\"131072\", 6
        # digits)") would trip this guard on prose, not code.
        #
        # assertNotIn is a substring check, not a word-boundary one: an
        # unrelated future literal that merely CONTAINS "4096" or "131072" as
        # a substring (e.g. a byte size like "40960" or an unrelated
        # "13107200") would fail this test even though it has nothing to do
        # with num_ctx. Left as-is rather than fixed with a regex word
        # boundary: it fails loud and specific enough (the assertion message
        # names the exact key and bound) that a false hit is easy to diagnose
        # and dismiss, which is not true of the silent drift this test exists
        # to catch.
        #
        # Residual gap: after narrowing to two parameters, this only pins
        # num_ctx's 4096 and 131072. temperature's 0 and 2 are excluded below
        # as too ambiguous to assert against QML -- they read as ordinary
        # margins, opacities and Style.space multipliers throughout the file
        # -- so a drift in temperature's bounds specifically would NOT be
        # caught here. test_the_bounds_agree_between_javascript_and_python
        # above is what actually pins temperature's numbers; this test only
        # ever covered num_ctx in practice.
        panel = ModelJsSyntaxTest.code_only(read("Panel.qml"))
        for key, (low, high, _is_int) in action_mod.PARAM_BOUNDS.items():
            for bound in (low, high):
                # 0, 1, and 2 are ordinary QML literals (margins, opacity,
                # Style.space multipliers) that appear throughout Panel.qml
                # for reasons that have nothing to do with these parameters.
                # Asserting on them would be either vacuously true or wrong
                # the moment an unrelated "2" is added nearby, so only
                # num_ctx's bounds are checked here (top_k's 200 was the
                # other one, before task 6b dropped top_k entirely).
                if bound in (0, 0.0, 1, 1.0, 2, 2.0):
                    continue
                self.assertNotIn(
                    str(bound), panel,
                    "Panel.qml must not hardcode " + key + "'s bound "
                    + str(bound) + " -- bind to Model.PARAM_SPECS instead")

    def test_the_collector_surfaces_exactly_these_parameters(self):
        self.assertEqual(sorted(collect.EDITABLE_PARAMS), sorted(self.KEYS),
                         "the collector's filter must match the editable "
                         "set")


class ParamWriteGuardTest(unittest.TestCase):
    """Three invariants that decide whether `apply` writes what the user asked
    for, and which NO runtime test in this repository can reach: two live in
    Service.qml and one in a QML focus transition. All three were shipped
    broken and caught by review, so they are pinned at the source level -- the
    same idiom BarGlyphTest and ColorPaletteTest already use for QML facts.

    Comments are stripped first, so a guard cannot be satisfied by prose that
    merely describes the invariant.
    """

    @staticmethod
    def strip_comments(source):
        return re.sub(r"//[^\n]*", "", source)

    def qml_function(self, source, name):
        """The body of a top-level `function <name>(` in a QML file.

        Sliced to the next two-space `function ` declaration rather than by
        brace matching: every function in Service.qml sits at one indent level
        inside the root object, so the next sibling declaration is an
        unambiguous terminator and needs no brace counter.
        """
        start = source.index("function " + name + "(")
        rest = source[start + 1:]
        end = rest.find("\n  function ")
        return rest if end < 0 else rest[:end]

    def test_the_dirty_loops_are_kind_filtered_and_need_a_staged_edit(self):
        if not panel_is_wired():
            self.skipTest("Panel.qml is not wired to Service.qml yet")
        source = self.strip_comments(read("Service.qml"))
        for name in ("paramDirty", "commitParams"):
            body = self.qml_function(source, name)
            self.assertIn(
                "Model.paramSpecsFor(entry.kind)", body,
                name + " must walk the specs the panel actually renders. "
                "Iterating every spec let an embedding model that declares an "
                "out-of-range temperature light apply with no visible field, "
                "and write a temperature onto a model that hides it.")
            self.assertNotIn(
                "PARAM_SPECS", body,
                name + " must not iterate the unfiltered spec list.")
            self.assertIn(
                "hasParamEdit", body,
                name + " must require a staged edit. Deciding dirtiness by "
                "comparing the parsed field text against the raw declared "
                "value goes dirty with nothing typed whenever a declared "
                "value does not survive its own round trip -- the field "
                "renders it rounded and clamped, and both transforms are "
                "lossy.")

    def test_a_destroyed_parameter_field_releases_the_focus_count(self):
        if not panel_is_wired():
            self.skipTest("Panel.qml is not wired to Service.qml yet")
        source = self.strip_comments(read("Panel.qml"))
        self.assertRegex(
            source,
            r"Component\.onDestruction:\s*if\s*\(activeFocus\)\s*"
            r"root\.paramFieldsFocused\s*=",
            "A parameter field must give its focus count back when it is "
            "DESTROYED, not only when it is hidden or blurred. The installed "
            "Repeater rebuilds every delegate whenever the snapshot's content "
            "differs, and a successful apply is exactly what makes it differ. "
            "Without this the counter strands above zero with nothing "
            "focused, and PanelKeyCatcher swallows r and esc for the rest of "
            "the panel session -- the bug PR #6 shipped.")


class TextFormatGuardTest(unittest.TestCase):
    """Every `Text` in Panel.qml must declare `textFormat: Text.PlainText`.

    The default is `Text.AutoText`, which sniffs the string and renders
    HTML-shaped content as rich text inside the shared shell process, where an
    `<img src="http://...">` becomes a resource Qt tries to fetch. Three sinks
    carry strings this plugin does not author -- model names off the manifest
    tree and from an API whose base URL is a user-editable setting, and the
    stderr of both scripts.

    Reported against commit 92161f0 by the marketplace security review
    (HANCORE-linux/omarchy-plugin-marketplace#3413), which counted 0 of 24
    declaring a format. Measured with a headless qml6 probe, 3/3 runs: the same
    hostile string laid out at 95.8px under the default and 382.3px as
    PlainText -- the default swallowed the tag rather than showing it.

    Asserted for ALL of them rather than the three known sinks, so a Text added
    later cannot reintroduce the question.
    """

    def test_every_text_item_declares_plain_text(self):
        if not panel_is_wired():
            self.skipTest("Panel.qml is not wired to Service.qml yet")
        source = read("Panel.qml")
        lines = source.split("\n")
        opens = [i for i, line in enumerate(lines)
                 if re.match(r"^\s*Text \{$", line)]
        self.assertGreater(len(opens), 0, "found no Text items to check")

        missing = []
        for index in opens:
            # The declaration is the line straight after the brace. Deliberately
            # positional rather than a search of the whole block: it keeps the
            # guard from being satisfied by a nested item's declaration, and it
            # keeps every Text looking the same to a reader.
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if following.strip() != "textFormat: Text.PlainText":
                missing.append(index + 1)

        self.assertEqual(
            missing, [],
            "Panel.qml lines %s open a Text without `textFormat: "
            "Text.PlainText` on the next line. The default AutoText renders "
            "HTML-shaped content as rich text in the shared shell process."
            % missing)


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
