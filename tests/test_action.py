import json
import os
import subprocess
import sys
import unittest

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

    def test_the_prompt_is_never_suppressed(self):
        # --no-ask-password sets allow_interactive_authorization=false on the
        # D-Bus call, which turns Omarchy's authentication dialog into a bare
        # "Access denied". Re-adding it does not fail loudly -- every action
        # silently becomes permission denied, with no error anywhere. The flag
        # looks defensive, and galley is one copy-paste away, so this asserts
        # its absence rather than trusting nobody re-adds it.
        for verb in ("start", "stop", "restart"):
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

    def test_dry_run_never_touches_the_service(self):
        before = subprocess.run(
            ["systemctl", "is-active", "ollama.service"],
            capture_output=True, text=True).stdout.strip()
        for args in (["start"], ["stop"], ["restart"],
                     ["warm", "llama3.2:3b"], ["unload", "llama3.2:3b"]):
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

    def test_endpoint_routing(self):
        self.assertEqual(action.endpoint_for("embed"), "/api/embed")
        self.assertEqual(action.endpoint_for("generate"), "/api/generate")
