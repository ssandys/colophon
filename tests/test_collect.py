import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

import colophon_collect as collect


def fixture_text(state, name):
    with open(os.path.join(FIXTURES, state, name)) as handle:
        return handle.read()


class ParseShowTest(unittest.TestCase):
    def test_splits_on_the_first_equals_only(self):
        text = "ActiveState=active\nEnvironment=HOME=/var/lib/ollama\n"
        parsed = collect.parse_show(text)
        self.assertEqual(parsed["ActiveState"], "active")
        self.assertEqual(parsed["Environment"], "HOME=/var/lib/ollama")

    def test_ignores_blank_and_malformed_lines(self):
        parsed = collect.parse_show("\nActiveState=active\ngarbage\n\n")
        self.assertEqual(parsed, {"ActiveState": "active"})

    def test_reads_the_real_stopped_fixture(self):
        parsed = collect.parse_show(fixture_text("stopped", "systemctl.txt"))
        self.assertEqual(parsed["ActiveState"], "inactive")
        self.assertEqual(parsed["LoadState"], "loaded")


class ModelsRootTest(unittest.TestCase):
    def test_reads_ollama_models_from_the_unit_environment(self):
        show = {"Environment": '"HOME=/var/lib/ollama" "OLLAMA_MODELS=/srv/models"'}
        self.assertEqual(collect.models_root(show), "/srv/models")

    def test_handles_unquoted_environment(self):
        show = {"Environment": "HOME=/x OLLAMA_MODELS=/srv/models"}
        self.assertEqual(collect.models_root(show), "/srv/models")

    def test_falls_back_when_unset(self):
        self.assertEqual(collect.models_root({}), "/var/lib/ollama")

    def test_falls_back_on_unbalanced_quotes(self):
        # shlex raises on this; the fallback must not crash the poll.
        show = {"Environment": 'OLLAMA_MODELS="/srv/models'}
        self.assertEqual(collect.models_root(show), "/var/lib/ollama")


class MemoryBytesTest(unittest.TestCase):
    def test_reads_a_real_value(self):
        self.assertEqual(collect.memory_bytes({"MemoryCurrent": "687194767"}),
                         687194767)

    def test_uint64_max_means_unknown(self):
        # systemd's "no value" sentinel. Rendering it would print 18 exabytes.
        self.assertIsNone(
            collect.memory_bytes({"MemoryCurrent": "18446744073709551615"}))

    def test_not_set_means_unknown(self):
        self.assertIsNone(collect.memory_bytes({"MemoryCurrent": "[not set]"}))

    def test_absent_means_unknown(self):
        self.assertIsNone(collect.memory_bytes({}))


class StartedAtTest(unittest.TestCase):
    def test_computes_an_epoch_from_the_monotonic_stamp(self):
        # Started 600s after boot; the box has been up 1000s; now is 5000.
        show = {"ExecMainStartTimestampMonotonic": "600000000"}
        self.assertEqual(collect.started_at(show, 1000.0, 5000.0), 4600)

    def test_zero_means_never_started(self):
        self.assertIsNone(
            collect.started_at({"ExecMainStartTimestampMonotonic": "0"},
                               1000.0, 5000.0))

    def test_absent_means_never_started(self):
        self.assertIsNone(collect.started_at({}, 1000.0, 5000.0))

    def test_a_stamp_from_the_future_is_rejected(self):
        show = {"ExecMainStartTimestampMonotonic": "2000000000"}
        self.assertIsNone(collect.started_at(show, 1000.0, 5000.0))


class ProcessorTest(unittest.TestCase):
    def test_all_in_vram_is_gpu(self):
        self.assertEqual(collect.processor(1000, 1000), ("gpu", 100))

    def test_none_in_vram_is_cpu(self):
        self.assertEqual(collect.processor(1000, 0), ("cpu", 0))

    def test_partial_is_a_split_with_a_percentage(self):
        self.assertEqual(collect.processor(1000, 620), ("split", 62))

    def test_vram_above_size_clamps_to_gpu(self):
        self.assertEqual(collect.processor(1000, 1200), ("gpu", 100))

    def test_zero_size_is_cpu(self):
        self.assertEqual(collect.processor(0, 0), ("cpu", 0))


class ParseRfc3339Test(unittest.TestCase):
    def test_parses_an_offset_timestamp(self):
        self.assertEqual(
            collect.parse_rfc3339("2026-08-10T12:00:00-05:00"), 1786381200)

    def test_truncates_nine_digit_fractions(self):
        # Ollama emits nanosecond precision; fromisoformat accepts at most
        # microseconds, so an untruncated value raises instead of parsing.
        value = collect.parse_rfc3339("2026-08-10T12:00:00.123456789-05:00")
        self.assertEqual(value, 1786381200)

    def test_accepts_a_zulu_suffix(self):
        self.assertEqual(
            collect.parse_rfc3339("2026-08-10T17:00:00Z"), 1786381200)

    def test_the_zero_year_sentinel_is_none(self):
        # Ollama uses 0001-01-01 for "no expiry"; it is not a real time.
        self.assertIsNone(collect.parse_rfc3339("0001-01-01T00:00:00Z"))

    def test_garbage_is_none(self):
        self.assertIsNone(collect.parse_rfc3339("not a timestamp"))
        self.assertIsNone(collect.parse_rfc3339(""))
        self.assertIsNone(collect.parse_rfc3339(None))


class ModelKindTest(unittest.TestCase):
    def test_nomic_bert_is_an_embedding_model(self):
        # Verified on the target machine: nomic-embed-text reports
        # model_family "nomic-bert". Embedding models take /api/embed, so this
        # lookup is what keeps `warm` from posting to the wrong endpoint.
        self.assertEqual(collect.model_kind("nomic-bert"), "embed")

    def test_bert_and_xlm_roberta_are_embedding_models(self):
        self.assertEqual(collect.model_kind("bert"), "embed")
        self.assertEqual(collect.model_kind("xlm-roberta"), "embed")

    def test_a_chat_family_is_generate(self):
        self.assertEqual(collect.model_kind("llama"), "generate")
        self.assertEqual(collect.model_kind("qwen3"), "generate")

    def test_an_unknown_family_falls_through_to_generate(self):
        self.assertEqual(collect.model_kind("something-new"), "generate")
        self.assertEqual(collect.model_kind(None), "generate")


class ModelLabelTest(unittest.TestCase):
    def test_library_models_drop_the_namespace(self):
        # registry.ollama.ai/library/<name>/<tag> is the ordinary case: the
        # namespace shorthand only fires for Ollama's own registry.
        self.assertEqual(
            collect.model_label("registry.ollama.ai", "library",
                                "llama3.2", "3b"),
            "llama3.2:3b")

    def test_non_library_namespaces_under_the_official_registry_are_kept(self):
        self.assertEqual(
            collect.model_label("registry.ollama.ai", "someone", "model",
                                "q4"),
            "someone/model:q4")

    def test_ollama_com_is_also_the_official_registry(self):
        # ollama.com is Ollama's other first-party registry name; it gets the
        # same namespace-dropping treatment as registry.ollama.ai.
        self.assertEqual(
            collect.model_label("ollama.com", "library", "llama3.2", "3b"),
            "llama3.2:3b")

    def test_a_foreign_registry_keeps_its_own_prefix(self):
        # This is the real-world bug: hf.co/bartowski/... is an ordinary
        # Ollama workflow, and the registry component is part of the name
        # Ollama itself expects back on every API call -- dropping it (as the
        # old 3-argument model_label did, treating "hf.co" as a namespace)
        # produces a name Ollama does not recognize.
        self.assertEqual(
            collect.model_label("hf.co", "bartowski",
                                "Llama-3.2-3B-Instruct-GGUF", "Q4_K_M"),
            "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M")


class NormalizeLoadedTest(unittest.TestCase):
    def test_shapes_a_real_ps_response(self):
        payload = {"models": [{
            "name": "llama3.2:3b",
            "size": 4000000000,
            "size_vram": 4000000000,
            "expires_at": "2026-08-10T12:05:00-05:00",
            "details": {"parameter_size": "3.2B",
                        "quantization_level": "Q4_K_M",
                        "family": "llama"},
        }]}
        loaded = collect.normalize_loaded(payload)
        self.assertEqual(len(loaded), 1)
        entry = loaded[0]
        self.assertEqual(entry["name"], "llama3.2:3b")
        self.assertEqual(entry["sizeBytes"], 4000000000)
        self.assertEqual(entry["vramBytes"], 4000000000)
        self.assertEqual(entry["processor"], "gpu")
        self.assertEqual(entry["gpuPercent"], 100)
        self.assertEqual(entry["parameterSize"], "3.2B")
        self.assertEqual(entry["quantization"], "Q4_K_M")
        self.assertEqual(entry["kind"], "generate")
        self.assertEqual(entry["expiresAt"], 1786381500)

    def test_an_empty_response_is_an_empty_list(self):
        self.assertEqual(collect.normalize_loaded({"models": []}), [])
        self.assertEqual(collect.normalize_loaded({}), [])
        self.assertEqual(collect.normalize_loaded(None), [])

    def test_missing_details_do_not_raise(self):
        loaded = collect.normalize_loaded(
            {"models": [{"name": "x:1", "size": 10, "size_vram": 0}]})
        self.assertEqual(loaded[0]["parameterSize"], "")
        self.assertEqual(loaded[0]["processor"], "cpu")
        self.assertIsNone(loaded[0]["expiresAt"])


class ScanInstalledTest(unittest.TestCase):
    def test_reads_the_fixture_tree(self):
        entries, unique_bytes = collect.scan_installed(
            os.path.join(FIXTURES, "models"))
        self.assertGreaterEqual(len(entries), 10)
        names = [entry["name"] for entry in entries]
        self.assertIn("llama3.2:3b", names)
        self.assertIn("nomic-embed-text:latest", names)
        self.assertGreater(unique_bytes, 0)

    def test_a_foreign_registry_model_keeps_its_full_name(self):
        # Pins the real-world bug end to end: a manifest under a non-Ollama
        # registry (manifests/hf.co/someone/some-model/Q4_K_M) must render
        # with the registry prefix intact, matching what Ollama itself
        # expects back on /api/generate or /api/embed.
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        by_name = {entry["name"]: entry for entry in entries}
        self.assertIn("hf.co/someone/some-model:Q4_K_M", by_name)
        entry = by_name["hf.co/someone/some-model:Q4_K_M"]
        self.assertEqual(entry["quantization"], "Q4_K_M")
        self.assertEqual(entry["kind"], "generate")

    def test_entries_are_sorted_by_name(self):
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        self.assertEqual(names_of(entries), sorted(names_of(entries)))

    def test_the_embedding_model_is_tagged_embed(self):
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(by_name["nomic-embed-text:latest"]["kind"], "embed")
        self.assertEqual(by_name["nomic-embed-text:latest"]["family"],
                         "nomic-bert")

    def test_unique_total_never_exceeds_the_sum_of_rows(self):
        # Models share blobs, so the unique-digest total is <= the row sum.
        # The README documents this, because it reads as a bug otherwise.
        entries, unique_bytes = collect.scan_installed(
            os.path.join(FIXTURES, "models"))
        row_sum = sum(entry["sizeBytes"] for entry in entries)
        self.assertLessEqual(unique_bytes, row_sum)

    def test_a_missing_root_is_empty_not_an_error(self):
        entries, unique_bytes = collect.scan_installed("/nonexistent/models")
        self.assertEqual(entries, [])
        self.assertEqual(unique_bytes, 0)

    def test_a_manifest_that_parses_but_is_not_an_object_is_skipped(self):
        # A truncated or corrupted write can parse cleanly as a JSON array.
        # It must cost us that one model, not the whole inventory.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "models")
            shutil.copytree(os.path.join(FIXTURES, "models"), root)
            bad = os.path.join(root, "manifests", "registry.ollama.ai",
                               "library", "corrupt", "latest")
            os.makedirs(os.path.dirname(bad), exist_ok=True)
            with open(bad, "w") as handle:
                handle.write("[1, 2, 3]")

            entries, unique_bytes = collect.scan_installed(root)

            names = [entry["name"] for entry in entries]
            self.assertNotIn("corrupt:latest", names)
            self.assertIn("llama3.2:3b", names)
            self.assertGreaterEqual(len(entries), 10)
            self.assertGreater(unique_bytes, 0)

    def test_a_manifest_with_wrong_shaped_config_and_layers_is_survivable(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "models")
            shutil.copytree(os.path.join(FIXTURES, "models"), root)
            bad = os.path.join(root, "manifests", "registry.ollama.ai",
                               "library", "weird", "latest")
            os.makedirs(os.path.dirname(bad), exist_ok=True)
            with open(bad, "w") as handle:
                json.dump({"config": "not-a-dict",
                           "layers": ["also-not-a-dict", {"size": 5}]}, handle)

            entries, unique_bytes = collect.scan_installed(root)

            by_name = {entry["name"]: entry for entry in entries}
            # It survives and is listed, counting only the one usable layer.
            self.assertIn("weird:latest", by_name)
            self.assertEqual(by_name["weird:latest"]["sizeBytes"], 5)
            self.assertIn("llama3.2:3b", by_name)

    def test_reads_the_four_parameters_from_the_params_layer(self):
        # Ollama stores parameters as their own manifest layer, blob = plain
        # JSON. nomic-embed-text's fixture manifest already declares a params
        # layer digest (sha256-ce4a164f...); its blob holds {"num_ctx":8192},
        # which is nomic-embed-text's real value on the target machine, so the
        # fixture stays faithful. Only the four the editor owns would be
        # surfaced if others were present -- a model declaring `stop` alone
        # reports {} rather than leaking a list the panel has no idiom for.
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(by_name["nomic-embed-text:latest"]["parameters"],
                          {"num_ctx": 8192})

    def test_a_model_with_no_params_layer_reports_an_empty_dict(self):
        # Not None: Model.js and Panel.qml both index this, and a null would
        # make every consumer guard for it. qwen2.5:7b's fixture manifest
        # carries no params layer at all.
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(by_name["qwen2.5:7b"]["parameters"], {})

    def test_a_params_layer_whose_blob_is_absent_reports_an_empty_dict(self):
        # deepseek-r1:latest's fixture manifest declares a params layer
        # digest, but (like six of the other seven fixture models that
        # declare one) no blob for that digest exists on disk. Same
        # principle as the config blob above it: a params layer that cannot
        # be read must cost that one model's parameters, not the inventory.
        entries, _ = collect.scan_installed(os.path.join(FIXTURES, "models"))
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(by_name["deepseek-r1:latest"]["parameters"], {})

    def test_a_malformed_params_blob_costs_that_model_only(self):
        # Same principle as the manifest-shape tests above, one layer down:
        # a params blob that exists but fails to parse must cost one model's
        # parameters, not the whole inventory. Injected into a scratch copy
        # of the fixture tree -- like the other corruption tests in this
        # class -- rather than checked in, so the tracked fixture tree stays
        # free of deliberately-broken data. ministral-3:3b's manifest already
        # declares this digest as its params layer; no blob exists for it in
        # the checked-in tree.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "models")
            shutil.copytree(os.path.join(FIXTURES, "models"), root)
            bad = os.path.join(
                root, "blobs",
                "sha256-e0daf17ff83eace4813f9e8554b262f6cc33ad880ff8"
                "df41a156ff9ef5522ddb")
            with open(bad, "w") as handle:
                handle.write("{not json")

            entries, _ = collect.scan_installed(root)

            by_name = {entry["name"]: entry for entry in entries}
            self.assertEqual(by_name["ministral-3:3b"]["parameters"], {})
            self.assertIn("llama3.2:3b", by_name)


def names_of(entries):
    return [entry["name"] for entry in entries]


class UnitFromShowTest(unittest.TestCase):
    def test_shapes_the_stopped_fixture(self):
        show = collect.parse_show(fixture_text("stopped", "systemctl.txt"))
        unit = collect.unit_from_show(show, uptime_sec=1000.0, now_sec=5000.0)
        self.assertEqual(unit["name"], "ollama.service")
        self.assertEqual(unit["activeState"], "inactive")
        self.assertEqual(unit["loadState"], "loaded")
        self.assertEqual(unit["unitFileState"], "disabled")
        self.assertIsNone(unit["startedAt"])
        self.assertEqual(unit["nRestarts"], 0)

    def test_non_numeric_restarts_degrade_to_zero(self):
        unit = collect.unit_from_show({"NRestarts": "[not set]"}, 1.0, 2.0)
        self.assertEqual(unit["nRestarts"], 0)


import subprocess


EXPECTED_STATUS = {
    "running": "running",
    "stopped": "stopped",
    "starting": "starting",
    "stopping": "stopping",
    "failed": "failed",
    "foreign": "foreign",
    "missing": "missing",
    # active with the API refused: the wedged case. Still `starting` -- the
    # 15-second relabel that distinguishes it is presentation, in Model.js.
    "wedged": "starting",
}


class FixtureReplayTest(unittest.TestCase):
    def snapshot_for(self, state):
        source = collect.FixtureSource(
            os.path.join(FIXTURES, state), "http://127.0.0.1:11434")
        return collect.collect(source, now_sec=5000.0, uptime_sec=1000.0)

    def test_every_fixture_resolves_to_its_state(self):
        for state, expected in EXPECTED_STATUS.items():
            with self.subTest(state=state):
                self.assertEqual(self.snapshot_for(state)["status"], expected)

    def test_running_reports_a_server_version_and_no_client_version(self):
        api = self.snapshot_for("running")["api"]
        self.assertTrue(api["reachable"])
        self.assertTrue(api["serverVersion"])
        # The client version is only looked up when the API is silent, so the
        # header never has to render a blank.
        self.assertIsNone(api["clientVersion"])

    def test_stopped_reports_a_client_version_and_no_server_version(self):
        api = self.snapshot_for("stopped")["api"]
        self.assertFalse(api["reachable"])
        self.assertIsNone(api["serverVersion"])
        self.assertTrue(api["clientVersion"])

    def test_the_installed_list_survives_the_server_being_down(self):
        # The whole reason the inventory is read from disk: a stopped panel is
        # still informative.
        snapshot = self.snapshot_for("stopped")
        self.assertGreaterEqual(snapshot["summary"]["installedCount"], 10)
        self.assertGreater(snapshot["summary"]["installedBytes"], 0)

    def test_loaded_is_empty_whenever_the_api_is_silent(self):
        for state in ("stopped", "failed", "missing", "starting", "wedged"):
            with self.subTest(state=state):
                snapshot = self.snapshot_for(state)
                self.assertEqual(snapshot["loaded"], [])
                self.assertEqual(snapshot["summary"]["loadedCount"], 0)

    def test_failed_carries_its_reason_code(self):
        # The failure *reason* is in the MVP via systemd's Result property;
        # only the journal log text is deferred.
        self.assertEqual(self.snapshot_for("failed")["unit"]["result"],
                         "exit-code")

    def test_foreign_has_a_live_api_and_an_inactive_unit(self):
        snapshot = self.snapshot_for("foreign")
        self.assertTrue(snapshot["api"]["reachable"])
        self.assertEqual(snapshot["unit"]["activeState"], "inactive")

    def test_every_snapshot_is_json_serialisable(self):
        for state in EXPECTED_STATUS:
            with self.subTest(state=state):
                json.dumps(self.snapshot_for(state))

    def test_summary_counts_match_the_lists(self):
        for state in EXPECTED_STATUS:
            with self.subTest(state=state):
                snapshot = self.snapshot_for(state)
                self.assertEqual(snapshot["summary"]["loadedCount"],
                                 len(snapshot["loaded"]))
                self.assertEqual(snapshot["summary"]["installedCount"],
                                 len(snapshot["installed"]))

    def test_a_fixture_without_systemctl_txt_is_an_error(self):
        source = collect.FixtureSource(os.path.join(FIXTURES, "models"),
                                       "http://127.0.0.1:11434")
        with self.assertRaises(collect.CollectError):
            collect.collect(source, now_sec=1.0, uptime_sec=1.0)


class CommandLineTest(unittest.TestCase):
    script = os.path.join(ROOT, "scripts", "colophon_collect.py")

    def run_cli(self, state, extra=None):
        env = dict(os.environ)
        env["COLOPHON_FIXTURE"] = os.path.join(FIXTURES, state)
        return subprocess.run(
            ["python3", self.script] + (extra or []),
            capture_output=True, text=True, env=env, timeout=20)

    def test_prints_one_json_object_and_exits_zero(self):
        result = self.run_cli("stopped")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["schema"], 1)

    def test_api_base_is_echoed_into_the_snapshot(self):
        result = self.run_cli("stopped", ["--api-base", "http://10.0.0.9:1234"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["api"]["base"],
                         "http://10.0.0.9:1234")

    def test_an_unknown_argument_exits_two(self):
        result = self.run_cli("stopped", ["--wat"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument", result.stderr)

    def test_a_broken_fixture_exits_one_with_a_message(self):
        env = dict(os.environ)
        env["COLOPHON_FIXTURE"] = "/nonexistent/fixture"
        result = subprocess.run(["python3", self.script],
                                capture_output=True, text=True, env=env,
                                timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn("systemctl.txt", result.stderr)


class ApiGetFailureTest(unittest.TestCase):
    def test_a_truncated_response_does_not_raise(self):
        # A server that dies mid-response raises http.client.IncompleteRead,
        # which is NOT an OSError/URLError/ValueError/TimeoutError. Uncaught,
        # it exits with a traceback that Service.qml would paste into the
        # panel's error strip.
        import http.server
        import threading

        class Truncating(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b'{"version":"0.')
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass  # keep test output pristine

        server = http.server.HTTPServer(("127.0.0.1", 0), Truncating)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_address[1])
            payload, latency = collect.api_get(base, "/api/version", 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        # Treated as "did not answer", exactly like a refused connection.
        self.assertIsNone(payload)
        self.assertIsNone(latency)
