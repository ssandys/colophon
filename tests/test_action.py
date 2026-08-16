import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import call
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import colophon_action as action

SCRIPT = os.path.join(ROOT, "scripts", "colophon_action.py")


def run(args):
    return subprocess.run(["python3", SCRIPT] + args,
                          capture_output=True, text=True, timeout=20)


class PlanTest(unittest.TestCase):
    def test_lifecycle_verbs_are_one_systemctl_call(self):
        for verb in ("start", "stop", "restart"):
            with self.subTest(verb=verb):
                self.assertEqual(
                    action.plan(verb, "", "generate", 5,
                                "http://127.0.0.1:11434", False),
                    ["/usr/bin/systemctl " + verb + " ollama.service"])

    def test_boot_verbs_are_one_systemctl_call(self):
        # enable/disable go through manage-unit-files rather than manage-units,
        # but the constructed command is the same shape: one systemctl call,
        # no flag. They never touch run state, so plan() must not add a start
        # step the way `warm` does on a stopped server.
        for verb in ("enable", "disable"):
            with self.subTest(verb=verb):
                self.assertEqual(
                    action.plan(verb, "", "generate", 5,
                                "http://127.0.0.1:11434", False),
                    ["/usr/bin/systemctl " + verb + " ollama.service"])

    def test_the_prompt_is_never_suppressed(self):
        # --no-ask-password sets allow_interactive_authorization=false on the
        # D-Bus call, which turns Omarchy's authentication dialog into a bare
        # "Access denied". Re-adding it does not fail loudly -- every action
        # silently becomes permission denied, with no error anywhere. The flag
        # looks defensive, and galley is one copy-paste away, so this asserts
        # its absence rather than trusting nobody re-adds it.
        #
        # This iterates SYSTEMCTL_VERBS, not LIFECYCLE_VERBS, deliberately: the
        # guard's contract is every verb that shells out to systemctl. A new
        # verb category added to its own tuple would otherwise ship unguarded
        # while this test kept passing.
        self.assertEqual(action.SYSTEMCTL_VERBS,
                         action.LIFECYCLE_VERBS + action.BOOT_VERBS,
                         "SYSTEMCTL_VERBS must cover every systemctl verb")
        for verb in action.SYSTEMCTL_VERBS:
            with self.subTest(verb=verb):
                self.assertNotIn(
                    "--no-ask-password", action.systemctl_command(verb),
                    "the prompt must not be suppressed -- see "
                    "docs/superpowers/specs/2026-08-11-prompted-privilege-design.md")

    def test_warm_on_a_stopped_server_starts_waits_then_posts(self):
        steps = action.plan("warm", "llama3.2:3b", "generate", 5,
                            "http://127.0.0.1:11434", False)
        self.assertEqual(len(steps), 3)
        self.assertIn("start ollama.service", steps[0])
        self.assertIn("/api/version", steps[1])
        self.assertIn("POST http://127.0.0.1:11434/api/generate", steps[2])
        self.assertIn('"keep_alive": "5m"', steps[2])

    def test_warm_on_a_running_server_only_posts(self):
        steps = action.plan("warm", "llama3.2:3b", "generate", 5,
                            "http://127.0.0.1:11434", True)
        self.assertEqual(len(steps), 1)
        self.assertIn("POST", steps[0])

    def test_warm_honours_the_keep_alive_minutes(self):
        steps = action.plan("warm", "llama3.2:3b", "generate", 30,
                            "http://127.0.0.1:11434", True)
        self.assertIn('"keep_alive": "30m"', steps[0])

    def test_warm_carries_the_context_window(self):
        steps = action.plan("warm", "llama3.2:3b", "generate", 5,
                            "http://127.0.0.1:11434", True, 8192)
        self.assertIn('"num_ctx": 8192', steps[0])

    def test_warm_without_a_context_size_sends_no_options(self):
        steps = action.plan("warm", "llama3.2:3b", "generate", 5,
                            "http://127.0.0.1:11434", True)
        self.assertNotIn("options", steps[0])

    def test_an_embedding_warm_carries_the_context_window(self):
        steps = action.plan("warm", "nomic-embed-text:latest", "embed", 5,
                            "http://127.0.0.1:11434", True, 16384)
        self.assertIn("/api/embed", steps[0])
        self.assertIn('"num_ctx": 16384', steps[0])

    def test_unload_posts_keep_alive_zero_and_never_starts_anything(self):
        steps = action.plan("unload", "llama3.2:3b", "generate", 5,
                            "http://127.0.0.1:11434", False)
        self.assertEqual(len(steps), 1)
        self.assertIn('"keep_alive": 0', steps[0])
        self.assertNotIn("systemctl", steps[0])

    def test_an_embedding_model_targets_the_embed_endpoint(self):
        # nomic-embed-text is installed on the target machine, so this is a
        # live case. /api/generate would error on it.
        steps = action.plan("warm", "nomic-embed-text:latest", "embed", 5,
                            "http://127.0.0.1:11434", True)
        self.assertIn("/api/embed", steps[0])
        self.assertNotIn("/api/generate", steps[0])
        self.assertIn('"input": ""', steps[0])

    def test_unload_of_an_embedding_model_also_targets_embed(self):
        steps = action.plan("unload", "nomic-embed-text:latest", "embed", 5,
                            "http://127.0.0.1:11434", True)
        self.assertIn("/api/embed", steps[0])
        self.assertIn('"keep_alive": 0', steps[0])

    def test_a_custom_api_base_is_honoured(self):
        steps = action.plan("unload", "x:1", "generate", 5,
                            "http://10.0.0.9:1234/", True)
        self.assertIn("http://10.0.0.9:1234/api/generate", steps[0])

    def test_apply_context_lists_then_recreates_every_model(self):
        # Two I/O-free lines: discover the installed set, then re-stamp every
        # one with the default num_ctx. apply-context never starts the service,
        # so plan() must not add a systemctl start the way `warm` does.
        steps = action.plan("apply-context", "", "generate", 5,
                            "http://127.0.0.1:11434", False, 24000)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0], "GET http://127.0.0.1:11434/api/tags")
        self.assertIn("num_ctx 24000", steps[1])
        self.assertNotIn("systemctl", "\n".join(steps))


class TimeoutConstantsTest(unittest.TestCase):
    def test_the_load_post_timeout_is_not_the_api_wait_deadline(self):
        # A prompt-less /api/generate only returns once the model is fully
        # resident in memory -- done_reason "load" is the completion signal,
        # not an early ack -- so a large model loading from a cold page
        # cache routinely exceeds a 20s deadline while still succeeding.
        # Sharing one constant between "wait for the port to bind" (fast)
        # and "wait for the load POST to finish" (can be slow) is exactly
        # the bug this pins against a regression.
        self.assertGreater(action.LOAD_POST_TIMEOUT_SEC,
                           action.API_WAIT_DEADLINE_SEC)
        self.assertGreaterEqual(action.LOAD_POST_TIMEOUT_SEC, 120)

    def test_the_systemctl_timeout_gives_a_human_time_to_authenticate(self):
        # This call now blocks on Omarchy's authentication dialog, not just
        # systemd -- a human has to notice the prompt and walk back to a
        # fingerprint sensor. 30s was fine when the call was non-interactive;
        # it is not enough now. Lowering this back toward 30 kills the
        # subprocess mid-authentication and reports a timeout for an action
        # the user was in the middle of approving, not a real failure.
        self.assertGreaterEqual(
            action.SYSTEMCTL_TIMEOUT_SEC, 120,
            "SYSTEMCTL_TIMEOUT_SEC must budget for a human walking to a "
            "fingerprint sensor -- dropping it back toward the old 30s "
            "non-interactive value kills the action mid-authentication and "
            "reports a timeout for something the user was about to approve")


class DryRunTest(unittest.TestCase):
    def test_start_prints_the_command_and_exits_zero(self):
        result = run(["start", "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "/usr/bin/systemctl start ollama.service")

    def test_dry_run_prints_the_maximal_warm_plan(self):
        # A dry run performs no I/O, so it cannot know whether the server is
        # up; it prints the full plan, which is what a reviewer needs to see.
        result = run(["warm", "llama3.2:3b", "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 3)

    def test_dry_run_prints_the_context_window(self):
        result = run(["warm", "llama3.2:3b", "--context-size", "16384",
                      "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"num_ctx": 16384', result.stdout)

    def test_apply_context_dry_run_prints_the_sweep(self):
        result = run(["apply-context", "24000", "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("/api/tags", lines[0])
        self.assertIn("num_ctx 24000", lines[1])

    def test_dry_run_never_touches_the_service(self):
        before = subprocess.run(
            ["systemctl", "is-active", "ollama.service"],
            capture_output=True, text=True).stdout.strip()
        for args in (["start"], ["stop"], ["restart"],
                     ["warm", "llama3.2:3b"], ["unload", "llama3.2:3b"],
                     ["apply-context", "24000"]):
            run(args + ["--dry-run"])
        after = subprocess.run(
            ["systemctl", "is-active", "ollama.service"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(before, after)


class ArgumentTest(unittest.TestCase):
    def test_an_unknown_verb_exits_two(self):
        result = run(["frobnicate", "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown verb", result.stderr)

    def test_no_verb_exits_two(self):
        result = run([])
        self.assertEqual(result.returncode, 2)

    def test_an_unknown_flag_exits_two(self):
        result = run(["start", "--wat"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)

    def test_an_unknown_kind_exits_two(self):
        result = run(["warm", "x:1", "--kind", "banana", "--dry-run"])
        self.assertEqual(result.returncode, 2)

    def test_a_non_integer_keep_alive_exits_two(self):
        result = run(["warm", "x:1", "--keep-alive", "soon", "--dry-run"])
        self.assertEqual(result.returncode, 2)

    def test_warm_without_a_model_exits_three(self):
        result = run(["warm", "--dry-run"])
        self.assertEqual(result.returncode, 3)
        self.assertIn("needs a model", result.stderr)

    def test_a_shell_metacharacter_in_a_model_name_is_refused(self):
        # There is no shell in the execution path, so this is belt and braces
        # -- but a name that cannot be a model name is a bug somewhere
        # upstream, and failing loudly beats posting it.
        for bad in ["a;rm -rf /", "a b", "a$(id)", "a|b", "../../etc/passwd\n"]:
            with self.subTest(model=bad):
                result = run(["warm", bad, "--dry-run"])
                self.assertEqual(result.returncode, 3)

    def test_a_realistic_model_name_is_accepted(self):
        for good in ["llama3.2:3b", "nomic-embed-text:latest",
                     "hf.co/someone/model:Q4_K_M", "qwen2.5:7b"]:
            with self.subTest(model=good):
                result = run(["unload", good, "--dry-run"])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_keep_alive_zero_is_rejected(self):
        # "0m" means unload-immediately to Ollama -- the opposite of warm.
        result = run(["warm", "x:1", "--keep-alive", "0", "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 1 and 120", result.stderr)

    def test_a_negative_keep_alive_is_rejected(self):
        result = run(["warm", "x:1", "--keep-alive", "-5", "--dry-run"])
        self.assertEqual(result.returncode, 2)

    def test_an_out_of_range_keep_alive_is_rejected(self):
        result = run(["warm", "x:1", "--keep-alive", "121", "--dry-run"])
        self.assertEqual(result.returncode, 2)

    def test_a_non_integer_context_size_is_rejected(self):
        result = run(["warm", "x:1", "--context-size", "wide", "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--context-size must be an integer", result.stderr)

    def test_an_out_of_range_context_size_is_rejected(self):
        for bad in ("0", "2048", "131073", "99999999", "-8192"):
            with self.subTest(context=bad):
                result = run(["warm", "x:1", "--context-size", bad,
                              "--dry-run"])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("between", result.stderr)

    def test_the_context_size_boundaries_are_accepted(self):
        for value in ("4096", "131072"):
            with self.subTest(context=value):
                result = run(["warm", "x:1", "--context-size", value,
                              "--dry-run"])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_typed_in_range_context_size_is_accepted(self):
        # The panel's editable number field can send any whole value in range,
        # not just a power of two; 18000 is a size a user can actually type.
        result = run(["warm", "x:1", "--context-size", "18000", "--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"num_ctx": 18000', result.stdout)

    def test_the_range_boundaries_are_accepted(self):
        for value in ("1", "120"):
            with self.subTest(value=value):
                result = run(["warm", "x:1", "--keep-alive", value, "--dry-run"])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_malformed_api_base_is_rejected(self):
        # Otherwise this fails api_reachable() like an ordinary refusal and
        # warm starts the LOCAL unit because of a typo in an unrelated flag.
        for bad in ["bogus", "127.0.0.1:11434", "ftp://x/y", ""]:
            with self.subTest(api_base=bad):
                result = run(["warm", "x:1", "--api-base", bad, "--dry-run"])
                self.assertEqual(result.returncode, 2)
                self.assertIn("http://", result.stderr)

    def test_a_well_formed_api_base_is_accepted(self):
        for good in ["http://127.0.0.1:11434", "https://10.0.0.9:1234/"]:
            with self.subTest(api_base=good):
                result = run(["warm", "x:1", "--api-base", good, "--dry-run"])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_apply_context_without_a_size_exits_two(self):
        result = run(["apply-context", "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("needs a context size", result.stderr)

    def test_apply_context_refuses_a_duplicate_size_source(self):
        # The size is positional so Service.qml can freeze the committed value;
        # a --context-size alongside it is ambiguous and must be refused rather
        # than silently preferred.
        result = run(["apply-context", "24000", "--context-size", "8192",
                      "--dry-run"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("not --context-size", result.stderr)

    def test_apply_context_out_of_range_exits_two(self):
        for bad in ("0", "2048", "131073", "24000.5", "twenty-four"):
            with self.subTest(size=bad):
                result = run(["apply-context", bad, "--dry-run"])
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_apply_context_in_range_is_accepted(self):
        for value in ("4096", "18000", "24000", "131072"):
            with self.subTest(size=value):
                result = run(["apply-context", value, "--dry-run"])
                self.assertEqual(result.returncode, 0, result.stderr)


class PostJsonTest(unittest.TestCase):
    def test_a_truncated_error_body_does_not_raise(self):
        # A server that closes mid error-body raises http.client.IncompleteRead
        # from error.read() itself, which is NOT an OSError. Uncaught, it lets
        # a raw traceback escape instead of the clean exit-1 the rest of the
        # error path gives -- the same gap that was fixed in api_get/api_reachable.
        import http.server
        import threading

        class TruncatingError(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b'{"error":"trunc')
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass  # keep test output pristine

        server = http.server.HTTPServer(("127.0.0.1", 0), TruncatingError)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = ("http://127.0.0.1:" + str(server.server_address[1])
                   + "/api/generate")
            # post_json writes its diagnostic straight to stderr (that is its
            # contract when run via the CLI, where the caller captures it);
            # swallow it here so calling it in-process keeps -v output clean.
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                code = action.post_json(
                    url, {"model": "x:1", "keep_alive": "5m"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(code, 1)


class BodyTest(unittest.TestCase):
    def test_generate_bodies_carry_no_input_field(self):
        body = action.load_body("x:1", "generate", "5m")
        self.assertEqual(body, {"model": "x:1", "keep_alive": "5m"})

    def test_embed_bodies_carry_an_empty_input(self):
        body = action.load_body("x:1", "embed", 0)
        self.assertEqual(body,
                         {"model": "x:1", "keep_alive": 0, "input": ""})

    def test_a_context_size_becomes_num_ctx(self):
        body = action.load_body("x:1", "generate", "5m", 8192)
        self.assertEqual(
            body,
            {"model": "x:1", "keep_alive": "5m",
             "options": {"num_ctx": 8192}})

    def test_embed_bodies_carry_both_input_and_context(self):
        body = action.load_body("x:1", "embed", "5m", 16384)
        self.assertEqual(
            body,
            {"model": "x:1", "keep_alive": "5m", "input": "",
             "options": {"num_ctx": 16384}})

    def test_zero_context_is_treated_as_absent(self):
        # Service.qml only passes --context-size on warm, but a falsy value
        # must never sneak an options block into the body.
        body = action.load_body("x:1", "generate", "5m", 0)
        self.assertEqual(body, {"model": "x:1", "keep_alive": "5m"})

    def test_endpoint_routing(self):
        self.assertEqual(action.endpoint_for("embed"), "/api/embed")
        self.assertEqual(action.endpoint_for("generate"), "/api/generate")


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class InstalledModelsTest(unittest.TestCase):
    def test_returns_every_model_name_from_tags(self):
        payload = json.dumps({"models": [
            {"name": "qwen3.6:27b"}, {"name": "nomic-embed-text:latest"},
            {"digest": "sha256:…"}]}).encode()
        with patch("urllib.request.urlopen",
                   return_value=FakeResponse(payload)) as opened:
            names = action.installed_models("http://127.0.0.1:11434")
        self.assertEqual(names, ["qwen3.6:27b", "nomic-embed-text:latest"])
        opened.assert_called_once()
        self.assertIn("/api/tags", opened.call_args.args[0])

    def test_a_refused_server_returns_none(self):
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            with contextlib.redirect_stderr(io.StringIO()):
                names = action.installed_models("http://127.0.0.1:11434")
        self.assertIsNone(names)

    def test_a_truncated_body_returns_none(self):
        # A server dying mid-body raises http.client.IncompleteRead, which is
        # none of URLError/OSError/ValueError -- trap #25, closed everywhere.
        import http.client
        with patch("urllib.request.urlopen",
                   side_effect=http.client.IncompleteRead(b"")):
            with contextlib.redirect_stderr(io.StringIO()):
                names = action.installed_models("http://127.0.0.1:11434")
        self.assertIsNone(names)

    def test_a_malformed_response_returns_none(self):
        with patch("urllib.request.urlopen",
                   return_value=FakeResponse(b"not json")):
            with contextlib.redirect_stderr(io.StringIO()):
                names = action.installed_models("http://127.0.0.1:11434")
        self.assertIsNone(names)


class CreateWithContextTest(unittest.TestCase):
    def test_runs_ollama_create_with_a_self_referencing_modelfile(self):
        completed = subprocess.CompletedProcess(
            ["ollama"], 0, stdout="", stderr="")
        with patch("subprocess.run", return_value=completed) as ran:
            code = action.create_with_context("qwen3.5:9b", 24000)
        self.assertEqual(code, 0)
        command = ran.call_args.args[0]
        self.assertEqual(command[:4], ["ollama", "create", "qwen3.5:9b", "-f"])
        modelfile = command[4]
        self.assertIn("/tmp/colophon-", modelfile)
        self.assertTrue(modelfile.endswith(".Modelfile"))
        self.assertFalse(os.path.exists(modelfile),
                         "the temp Modelfile must be removed")

    def test_a_failed_create_is_reported(self):
        completed = subprocess.CompletedProcess(
            ["ollama"], 1, stdout="", stderr="boom")
        with patch("subprocess.run", return_value=completed) as ran:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = action.create_with_context("qwen3.5:9b", 24000)
        self.assertEqual(code, 1)
        self.assertIn("failed", err.getvalue())
        self.assertFalse(os.path.exists(ran.call_args.args[0][4]))


class ApplyDefaultContextTest(unittest.TestCase):
    def test_applies_to_every_installed_model(self):
        with patch("colophon_action.installed_models",
                   return_value=["a:1", "b:2"]) as models:
            with patch("colophon_action.create_with_context",
                       return_value=0) as create:
                code = action.apply_default_context(
                    "http://127.0.0.1:11434", 24000)
        self.assertEqual(code, 0)
        models.assert_called_once()
        self.assertEqual(create.call_args_list,
                         [call("a:1", 24000), call("b:2", 24000)])

    def test_a_failed_create_stops_the_sweep(self):
        with patch("colophon_action.installed_models",
                   return_value=["a:1", "b:2"]):
            with patch("colophon_action.create_with_context",
                       side_effect=[0, 1]) as create:
                code = action.apply_default_context(
                    "http://127.0.0.1:11434", 8192)
        self.assertEqual(code, 1)
        self.assertEqual(create.call_count, 2)

    def test_an_unreachable_server_exits_one_without_starting(self):
        with patch("colophon_action.installed_models",
                   return_value=None) as models:
            code = action.apply_default_context(
                "http://127.0.0.1:11434", 8192)
        self.assertEqual(code, 1)
        models.assert_called_once()

    def test_a_suspicious_model_name_is_skipped(self):
        with patch("colophon_action.installed_models",
                   return_value=["good:1", "evil;rm -rf /", "ok:2"]):
            with patch("colophon_action.create_with_context",
                       return_value=0) as create:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = action.apply_default_context(
                        "http://127.0.0.1:11434", 8192)
        self.assertEqual(code, 0)
        names = [c.args[0] for c in create.call_args_list]
        self.assertEqual(names, ["good:1", "ok:2"])
