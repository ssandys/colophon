# tests/test_dev.py
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEV = os.path.join(ROOT, "bin", "dev")


def run(args, env=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(["bash", DEV] + args, capture_output=True,
                          timeout=30, env=merged, cwd=ROOT)


def lines(proc):
    """Non-blank stdout lines. In a dry run these are the commands, in order."""
    return [line for line in proc.stdout.decode().splitlines() if line.strip()]


class DispatchTest(unittest.TestCase):
    def test_unknown_verb_exits_2(self):
        proc = run(["obliterate"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown verb", proc.stderr.decode())

    def test_no_verb_exits_2(self):
        proc = run([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage", proc.stderr.decode().lower())


class DeployTest(unittest.TestCase):
    def test_dry_run_emits_rsync_and_sed(self):
        out = "\n".join(lines(run(["deploy", "--dry-run"])))
        self.assertIn("rsync", out)
        self.assertIn("sed", out)

    def test_deploy_never_touches_the_running_shell(self):
        # deploy is what bin/dev-watch calls on every save. If it could restart
        # or enable anything, the edit loop would flicker the whole bar on each
        # keystroke-to-disk. Checked on the leading token: $DEST legitimately
        # contains "omarchy" in its path.
        for line in lines(run(["deploy", "--dry-run"])):
            first = line.split()[0]
            self.assertNotIn(first, ("omarchy", "omarchy-shell"),
                             f"deploy emitted a shell command: {line}")

    def test_dry_run_deploys_nothing(self):
        proc = run(["deploy", "--dry-run"])
        self.assertEqual(proc.returncode, 0)
        # mkdir routes through run() like everything else, so a dry run cannot
        # create the destination as a side effect.
        self.assertTrue(any("mkdir" in line for line in lines(proc)))


class RealDeployTest(unittest.TestCase):
    """Executes deploy() for real into a scratch HOME.

    Every other test here inspects --dry-run's printed strings, which means
    deploy() and verify() are never actually run. That left the rewrite itself
    untested: narrowing the sed target back to a named file, or dropping
    --delete from the rsync, both kept the suite green. $DEST derives from
    $HOME alone, so an overridden HOME makes a real deploy fully hermetic.

    verify() is NOT covered here, and cannot be by any assertion on deployed
    output: its grep uses the same quote anchors as the sed it is checking,
    so there is no input on which the sed misses and verify catches it.
    Replacing verify()'s body with `return 0` still leaves correctly-rewritten
    output behind whenever the sed itself is correct, so no assertion on that
    output can tell verify() is gone. It is a redundant belt-and-braces check,
    not a tested one.

    The literals are read from this repo's own manifest.json, the same way
    PortabilityTest does, so this test ports unchanged.
    """

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.published_id = manifest["id"]
        self.published_name = manifest["name"]
        self.dev_id = f"{self.published_id}-dev"
        self.home = tempfile.mkdtemp(prefix="dev-test-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.dest = os.path.join(
            self.home, ".config", "omarchy", "plugins", self.dev_id)

    def deploy_into(self, home):
        return subprocess.run(["bash", DEV, "deploy"], capture_output=True,
                              timeout=60, cwd=ROOT, env={**os.environ, "HOME": home})

    def deployed_manifest(self):
        with open(os.path.join(self.dest, "manifest.json")) as handle:
            return json.load(handle)

    def deployed_qml_files(self):
        return [name for name in os.listdir(self.dest) if name.endswith(".qml")]

    def test_deploy_exits_zero(self):
        proc = self.deploy_into(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

    def test_deployed_manifest_carries_the_dev_identity(self):
        self.deploy_into(self.home)
        manifest = self.deployed_manifest()
        self.assertEqual(manifest["id"], self.dev_id)
        self.assertTrue(manifest["name"].endswith("(dev)"), manifest["name"])

    def test_every_deployed_qml_file_is_rewritten(self):
        self.deploy_into(self.home)
        qml_files = self.deployed_qml_files()
        self.assertTrue(qml_files, "deploy produced no *.qml files to check")
        published_id_quoted = f'"{self.published_id}"'
        published_name_quoted = f'{self.published_name}"'
        for name in qml_files:
            with open(os.path.join(self.dest, name)) as handle:
                text = handle.read()
            self.assertNotIn(
                published_id_quoted, text,
                f"{name} still claims the published id {published_id_quoted!r}")
            self.assertNotIn(
                published_name_quoted, text,
                f"{name} still carries the published name "
                f"{published_name_quoted!r}")

    def test_rewrite_reaches_every_top_level_qml_file_not_just_one(self):
        # Regression guard for the exact defect the old bin/install had and
        # this branch replaces: a rewrite scoped to a named file (there,
        # Panel.qml) silently misses a second top-level QML file introduced
        # later -- colophon's real Service.qml bug, described in the design
        # spec. Galley itself currently has only one top-level *.qml file, so
        # this can't be exercised against this repo's own tree: a mutation
        # that hardcodes the sed target back to "$DEST/Panel.qml" produces
        # byte-identical output to the glob today, and would slip past a test
        # that only looks at this repo's actual files. Reproduced instead in
        # a scratch mirror of the source tree carrying a second *.qml file.
        mirror = tempfile.mkdtemp(prefix="dev-test-mirror-")
        self.addCleanup(shutil.rmtree, mirror, ignore_errors=True)
        os.makedirs(os.path.join(mirror, "bin"))
        shutil.copy(DEV, os.path.join(mirror, "bin", "dev"))
        shutil.copy(os.path.join(ROOT, "manifest.json"), mirror)
        # The real Panel.qml, copied verbatim, alongside a synthetic second
        # QML file below: a mutation that hardcodes the sed target back to
        # "$DEST/Panel.qml" then succeeds on Panel.qml and silently skips the
        # second file, instead of crashing on a missing named file -- which is
        # what a mirror carrying only the synthetic file would produce, for
        # the wrong reason (sed: can't read .../Panel.qml: No such file or
        # directory), never exercising the actual defect this test exists for.
        shutil.copy(os.path.join(ROOT, "Panel.qml"), mirror)
        with open(os.path.join(mirror, "Extra.qml"), "w") as handle:
            handle.write(
                'Item {\n'
                f'  property string moduleName: "{self.published_id}"\n'
                f'  property string label: "  {self.published_name}"\n'
                '}\n')

        proc = subprocess.run(
            ["bash", os.path.join(mirror, "bin", "dev"), "deploy"],
            capture_output=True, timeout=60, cwd=mirror,
            env={**os.environ, "HOME": self.home})
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

        with open(os.path.join(self.dest, "Extra.qml")) as handle:
            text = handle.read()
        self.assertNotIn(f'"{self.published_id}"', text,
                         "a second top-level *.qml file still carries the "
                         "published id -- the rewrite is not reaching every "
                         "*.qml file")
        self.assertNotIn(f'{self.published_name}"', text,
                         "a second top-level *.qml file still carries the "
                         "published name -- the rewrite is not reaching "
                         "every *.qml file")

    def test_second_deploy_into_the_same_home_stays_idempotent(self):
        # `up` runs deploy repeatedly (rescan and enable are themselves
        # idempotent), so a second deploy over the first's output must not
        # compound the rewrite into -dev-dev or "(dev) (dev)".
        self.deploy_into(self.home)
        proc = self.deploy_into(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())

        manifest = self.deployed_manifest()
        self.assertEqual(manifest["id"], self.dev_id)
        self.assertNotIn("-dev-dev", manifest["id"])
        self.assertNotIn("(dev) (dev)", manifest["name"])

        for name in self.deployed_qml_files():
            with open(os.path.join(self.dest, name)) as handle:
                text = handle.read()
            self.assertNotIn("-dev-dev", text)
            self.assertNotIn("(dev) (dev)", text)

    def test_second_deploy_removes_a_stray_file_left_in_dest(self):
        # `up` relies on rsync --delete to stay idempotent over a stale
        # $DEST (see bin/dev's own comment in down()), but nothing above
        # actually deploys twice with $DEST perturbed in between, so dropping
        # --delete from the rsync leaves this whole suite green. Plant a
        # stray file inside the deployed directory after the first deploy and
        # confirm the second one removes it.
        self.deploy_into(self.home)
        stray = os.path.join(self.dest, "stray-leftover.txt")
        with open(stray, "w") as handle:
            handle.write("leftover\n")

        proc = self.deploy_into(self.home)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertFalse(
            os.path.exists(stray),
            "a stray file in $DEST survived a second deploy -- rsync "
            "--delete is missing or not being applied, so `up` is not "
            "idempotent over a stale $DEST")


class UpTest(unittest.TestCase):
    def setUp(self):
        self.out = lines(run(["up", "--dry-run"]))

    def index_of(self, needle):
        for i, line in enumerate(self.out):
            if needle in line:
                return i
        self.fail(f"`up --dry-run` never emitted {needle!r}; got {self.out}")

    def test_rescans_before_enabling(self):
        # `omarchy plugin enable` exits 1 on an id the registry has never seen,
        # which is every first deploy of a fresh clone. The official install
        # sequence rescans first; bin/install skipped it and only worked on a
        # machine where the dev id already existed.
        self.assertLess(self.index_of("rescanPlugins"),
                        self.index_of("plugin enable"))

    def test_deploys_before_rescanning(self):
        self.assertLess(self.index_of("rsync"), self.index_of("rescanPlugins"))

    def test_restarts_the_shell_last(self):
        self.assertEqual(self.index_of("restart shell"), len(self.out) - 1)

    def test_passes_no_placement_to_enable(self):
        # manifest.json's barWidget.defaultSection already declares placement.
        # `up` runs repeatedly, so stamping one here would overwrite a position
        # the user has since moved by hand.
        enable = self.out[self.index_of("plugin enable")]
        self.assertRegex(enable, r"^omarchy plugin enable \S+$")


class UpWaitsForRegistrationTest(unittest.TestCase):
    """Drives `up` for real against a scratch $HOME with a PATH-shimmed
    registry, proving it polls the registry after the rescan instead of
    racing straight into `enable`.

    This is the bug live verification caught on a genuinely cold start:
    `rescanPlugins` is asynchronous -- the IPC call returns before the shell
    finishes re-walking the plugin directories in the background -- so
    `enable` right after it lost the race on a first-ever deploy. No
    --dry-run test could see this, since --dry-run only inspects printed
    strings and skips the wait entirely; RealDeployTest never touches the
    registry at all.

    DEV_STATE_FIXTURE can't drive this: it returns one fixed answer for the
    whole run, and this needs the answer to change mid-run. So instead of
    the fixture, this shims `omarchy` and `omarchy-shell` on PATH -- both
    binaries, since `up` calls both -- with scripts that report the dev id
    absent for their first few `plugin list --json` calls and present after,
    using a counter file to persist state across the separate invocations
    `up` makes. HOME is pinned to a scratch directory, exactly as in
    RealDeployTest, so `deploy` (which `up` runs first) is fully hermetic;
    the shim on top of that means `up` itself never reaches the real
    registry or the real desktop shell.
    """

    OMARCHY_STUB = '''#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  "plugin list")
    count=0
    [[ -f "%(counter)s" ]] && count="$(cat "%(counter)s")"
    count=$((count + 1))
    echo "$count" > "%(counter)s"
    if (( count <= %(flip_after)d )); then
      echo '[]'
    else
      echo '[{"id":"%(dev_id)s","enabled":false}]'
    fi
    ;;
  "plugin enable")
    exit 0
    ;;
  "restart shell")
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
'''

    OMARCHY_SHELL_STUB = "#!/usr/bin/env bash\nexit 0\n"

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.dev_id = f"{manifest['id']}-dev"
        self.home = tempfile.mkdtemp(prefix="dev-test-up-home-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.stub_dir = tempfile.mkdtemp(prefix="dev-test-up-stub-")
        self.addCleanup(shutil.rmtree, self.stub_dir, ignore_errors=True)
        self.counter = os.path.join(self.stub_dir, "calls")

        shell_stub = os.path.join(self.stub_dir, "omarchy-shell")
        with open(shell_stub, "w") as handle:
            handle.write(self.OMARCHY_SHELL_STUB)
        os.chmod(shell_stub, 0o755)

    def write_omarchy_stub(self, flip_after):
        """flip_after: how many `plugin list` calls report the id absent
        before it starts reporting present. A huge value never flips, for
        the timeout test."""
        stub = os.path.join(self.stub_dir, "omarchy")
        with open(stub, "w") as handle:
            handle.write(self.OMARCHY_STUB % {
                "counter": self.counter,
                "flip_after": flip_after,
                "dev_id": self.dev_id,
            })
        os.chmod(stub, 0o755)

    def call_count(self):
        if not os.path.exists(self.counter):
            return 0
        with open(self.counter) as handle:
            return int(handle.read().strip())

    def run_up(self, env_extra=None):
        merged = dict(os.environ)
        merged["HOME"] = self.home
        merged["PATH"] = self.stub_dir + os.pathsep + merged["PATH"]
        if env_extra:
            merged.update(env_extra)

        # Confirm the shim, not the real system, is what `up` will reach.
        # A failure here means this test itself would touch the live
        # omarchy desktop -- the one thing this suite must never do.
        which = subprocess.run(
            ["bash", "-c", "command -v omarchy && command -v omarchy-shell"],
            capture_output=True, env=merged)
        self.assertEqual(which.returncode, 0, which.stderr.decode())
        resolved = which.stdout.decode().splitlines()
        self.assertEqual(len(resolved), 2, resolved)
        for path in resolved:
            self.assertTrue(
                path.startswith(self.stub_dir),
                f"real omarchy binary reachable on PATH: {path}")

        return subprocess.run(["bash", DEV, "up"], capture_output=True,
                              timeout=30, cwd=ROOT, env=merged)

    def test_up_waits_for_the_registry_then_succeeds(self):
        self.write_omarchy_stub(flip_after=3)
        proc = self.run_up()
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertGreater(
            self.call_count(), 1,
            "the registry was queried only once -- up raced straight into "
            "enable instead of polling for the rescan to land")

    def test_up_times_out_with_a_clear_message_instead_of_hanging(self):
        # Reports absent forever. Without the fix this would hang until
        # `enable` fails on its own; with the fix, and DEV_WAIT_TIMEOUT
        # overridden, it fails fast with a message naming the id rather than
        # actually waiting out the real 10-second default.
        self.write_omarchy_stub(flip_after=999999)
        proc = self.run_up(env_extra={"DEV_WAIT_TIMEOUT": "1"})
        self.assertNotEqual(proc.returncode, 0)
        err = proc.stderr.decode()
        self.assertIn(self.dev_id, err)
        self.assertIn("regist", err.lower())
        self.assertGreater(self.call_count(), 1)


class DownTest(unittest.TestCase):
    def out(self, state):
        return lines(run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": state}))

    def test_absent_is_a_noop_and_does_not_restart(self):
        # `omarchy plugin disable` exits 1 on an unregistered id, which under
        # `set -e` would abort before the restart with an omarchy error rather
        # than a useful one.
        proc = run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": "absent"})
        self.assertEqual(proc.returncode, 0)
        joined = "\n".join(lines(proc))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("not registered", joined)

    def test_already_disabled_is_a_noop_and_does_not_restart(self):
        # A shell restart flickers the whole bar and closes open panels, which
        # is too rude for a no-op.
        joined = "\n".join(self.out("disabled"))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)
        self.assertIn("already disabled", joined)

    def test_enabled_disables_then_restarts(self):
        out = self.out("enabled")
        self.assertTrue(any("plugin disable" in line for line in out), out)
        self.assertTrue(any("restart shell" in line for line in out), out)
        disable_at = next(i for i, l in enumerate(out) if "plugin disable" in l)
        restart_at = next(i for i, l in enumerate(out) if "restart shell" in l)
        self.assertLess(disable_at, restart_at)

    def test_down_does_not_remove_the_deployed_directory(self):
        # Retaining $DEST preserves the dev copy's shell.json settings, and
        # rsync --delete already makes `up` idempotent over a stale directory.
        joined = "\n".join(self.out("enabled"))
        self.assertNotIn("rm ", joined)

    def test_unrecognised_state_does_not_act_and_exits_nonzero(self):
        # The case in down() must not default to "act": a typo, an
        # unexpected-case fixture, or a future fourth state falling through
        # the absent/disabled guard must not disable the plugin and restart
        # the shell for a state this script does not understand.
        proc = run(["down", "--dry-run"], env={"DEV_STATE_FIXTURE": "typo"})
        self.assertNotEqual(proc.returncode, 0)
        joined = "\n".join(lines(proc))
        self.assertNotIn("restart", joined)
        self.assertNotIn("plugin disable", joined)


class PluginStateQueryTest(unittest.TestCase):
    """Drives a registry-query failure with an `omarchy` stub on PATH.

    DEV_STATE_FIXTURE bypasses the query entirely, so it can't exercise this
    path. Putting a failing `omarchy` first on PATH does.
    """

    def setUp(self):
        self.stub_dir = tempfile.mkdtemp(prefix="dev-test-path-stub-")
        self.addCleanup(shutil.rmtree, self.stub_dir, ignore_errors=True)
        stub = os.path.join(self.stub_dir, "omarchy")
        with open(stub, "w") as handle:
            handle.write("#!/usr/bin/env bash\nexit 1\n")
        os.chmod(stub, 0o755)

    def run_with_broken_omarchy(self, args):
        merged = dict(os.environ)
        merged["PATH"] = self.stub_dir + os.pathsep + merged["PATH"]
        return subprocess.run(["bash", DEV] + args, capture_output=True,
                              timeout=30, env=merged, cwd=ROOT)

    def test_down_fails_loudly_rather_than_reporting_absent(self):
        # Without the fix, `set -e` does not abort inside the command
        # substitution that assigns $json, so a failing `omarchy` leaves it
        # empty, `jq -e` reads that as "not present", and `down` would print
        # "is not registered; nothing to take down" and exit 0 -- the user
        # believes the dev copy is torn down while it is still enabled.
        proc = self.run_with_broken_omarchy(["down", "--dry-run"])
        self.assertNotEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertNotIn("not registered", out)
        self.assertNotIn("plugin disable", out)
        self.assertNotIn("restart", out)

    def test_status_fails_loudly_rather_than_reporting_absent(self):
        proc = self.run_with_broken_omarchy(["status"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("absent", proc.stdout.decode())


class StatusTest(unittest.TestCase):
    def registry_line(self, state):
        proc = run(["status"], env={"DEV_STATE_FIXTURE": state})
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout.decode()
        self.assertIn("-dev", out)
        self.assertIn("deployed:", out)
        return next(line for line in out.splitlines()
                    if line.startswith("registry:"))

    def test_reports_the_registry_state_the_fixture_says(self):
        # Asserting only that "enabled" appears when the fixture says
        # "enabled" would pass even if the fixture were ignored entirely, on
        # any machine where the dev plugin genuinely is enabled. Checking
        # both directions forces the fixture to actually be read.
        self.assertIn("enabled", self.registry_line("enabled"))
        absent_line = self.registry_line("absent")
        self.assertIn("absent", absent_line)
        self.assertNotIn("enabled", absent_line)


class PortabilityTest(unittest.TestCase):
    """The dev scripts must be byte-identical across plugin repos.

    Everything plugin-specific is derived at runtime from manifest.json, so a
    port is a copy with no edits. This asserts the invariant that makes that
    true: no script mentions this plugin's id, display name, or short name.

    The literals are read from manifest.json rather than hardcoded, so this
    test itself ports unchanged -- which is the whole point.

    Necessarily textual, unlike the behavioural tests above: absence of a
    literal is a textual property. Scoped to exactly that and nothing else.
    """

    SCRIPTS = ("bin/dev", "bin/dev-watch", "bin/test")

    def setUp(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        plugin_id = manifest["id"]
        self.literals = {
            "manifest id": plugin_id,
            "display name": manifest["name"],
            "short name": plugin_id.split(".")[-1],
        }

    # bin/dev's header points at the design spec's fixed home, "ssandys/galley"
    # (the spec's own "Canonical location" note: other repos reference it
    # rather than holding a copy). That pointer is identical on every port,
    # including this one, so it costs the byte-identical invariant nothing --
    # it only happens to collide with the check below, because galley is both
    # the current repo and the spec's permanent host, and "galley" is this
    # repo's own short name. Stripped by exact match, not by a general
    # "galley" filter, so a real leak of the short name anywhere else in the
    # file still fails loudly.
    SPEC_HOME_REFERENCE = "ssandys/galley"

    def test_scripts_carry_no_plugin_specific_literal(self):
        for relative in self.SCRIPTS:
            path = os.path.join(ROOT, relative)
            with open(path) as handle:
                source = handle.read()
            source = source.replace(self.SPEC_HOME_REFERENCE, "")
            for label, literal in self.literals.items():
                self.assertNotIn(
                    literal, source,
                    f"{relative} hardcodes the {label} '{literal}'. Derive it "
                    f"from manifest.json instead, so this script stays "
                    f"byte-identical across plugins and ports by copying.")

    def test_every_dev_script_is_covered(self):
        # A guard listing files by name is only as good as the list. If a new
        # bin/ script appears, it must be added above or explicitly excused.
        present = {
            os.path.join("bin", name)
            for name in os.listdir(os.path.join(ROOT, "bin"))
        }
        self.assertEqual(present, set(self.SCRIPTS),
                         "bin/ contents changed; update SCRIPTS or excuse the "
                         "new file explicitly")


if __name__ == "__main__":
    unittest.main()
