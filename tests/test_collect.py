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
        self.assertEqual(collect.model_label("library", "llama3.2", "3b"),
                         "llama3.2:3b")

    def test_other_namespaces_are_kept(self):
        self.assertEqual(collect.model_label("hf.co", "someone", "q4"),
                         "hf.co/someone:q4")


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
        self.assertGreaterEqual(len(entries), 9)
        names = [entry["name"] for entry in entries]
        self.assertIn("llama3.2:3b", names)
        self.assertIn("nomic-embed-text:latest", names)
        self.assertGreater(unique_bytes, 0)

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
            self.assertGreaterEqual(len(entries), 9)
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
