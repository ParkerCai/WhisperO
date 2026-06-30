from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from whispero import config as config_module
from whispero.config import _apply_env, _normalize
from whispero import rewrite


class RewriteHelperTests(unittest.TestCase):
    def test_spoken_punctuation_is_normalized_before_model(self):
        text = "hello comma world full stop new line are you there question mark"
        self.assertEqual(
            rewrite._apply_spoken_punctuation(text),
            "hello, world.\nare you there?",
        )

    def test_ambiguous_period_and_colon_are_not_rule_rewritten(self):
        text = "the jurassic period ended before the colon cancer screening"
        self.assertEqual(rewrite._apply_spoken_punctuation(text), text)

    def test_thinking_and_labels_are_stripped(self):
        text = '<think>reasoning goes here</think> Rewritten text: "Hello, world."'
        self.assertEqual(rewrite._clean_rewrite_output(text), "Hello, world.")

    def test_clean_output_capitalizes_first_character(self):
        self.assertEqual(
            rewrite._clean_rewrite_output("this is actually important"),
            "This is actually important",
        )

    def test_default_prompt_mentions_semantic_self_correction(self):
        prompt = _normalize({})["rewrite"]["prompt"]
        self.assertIn("self-correction", prompt)
        self.assertIn("final intended meaning", prompt)
        self.assertIn("Do not remove meaningful words", prompt)

    def test_semantic_cleanup_removes_course_correction_marker(self):
        text = "this is way too slow, actually never mind lets try it again"
        self.assertEqual(
            rewrite._apply_semantic_cleanup(text),
            "this is way too slow, lets try it again",
        )

    def test_semantic_cleanup_keeps_final_scratch_that_intent(self):
        text = "send this to alex scratch that send it to sarah instead"
        self.assertEqual(
            rewrite._apply_semantic_cleanup(text),
            "send it to sarah instead",
        )

    def test_semantic_cleanup_preserves_meaningful_actually(self):
        text = "this is actually important and we should keep the word actually here"
        self.assertEqual(rewrite._apply_semantic_cleanup(text), text)

    def test_default_model_path_is_used_when_config_path_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                self.assertEqual(
                    rewrite._resolve_model_path(""),
                    Path(tmpdir) / ".whispero" / "rewrite-models" / rewrite.DEFAULT_REWRITE_MODEL_FILE,
                )

    def test_cached_default_model_does_not_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch.object(Path, "home", return_value=Path(tmpdir)),
                mock.patch.object(rewrite, "DEFAULT_REWRITE_MODEL_SIZE", 3),
                mock.patch.object(rewrite.requests, "get") as mock_get,
            ):
                model_path = rewrite.get_default_rewrite_model_path()
                model_path.write_bytes(b"abc")
                self.assertEqual(rewrite.ensure_rewrite_model({}), model_path)
                mock_get.assert_not_called()

    def test_custom_cached_model_does_not_use_default_size_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "custom.gguf"
            model_path.write_bytes(b"not a real model")
            self.assertTrue(rewrite.is_rewrite_model_cached(model_path))

    def test_missing_custom_model_is_not_downloaded_as_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_model = Path(tmpdir) / "missing.gguf"
            with self.assertRaisesRegex(RuntimeError, "rewrite model not found"):
                rewrite.ensure_rewrite_model({"model_path": str(missing_model)})

    def test_windows_runtime_install_command_uses_cuda_wheel_index(self):
        with (
            mock.patch.object(rewrite.sys, "platform", "win32"),
            mock.patch.object(rewrite.sys, "executable", "python.exe"),
        ):
            command = rewrite._rewrite_runtime_install_command()
            self.assertEqual(
                command[:5],
                ["python.exe", "-m", "pip", "install", rewrite.REWRITE_RUNTIME_PACKAGE],
            )
            self.assertIn("--extra-index-url", command)
            self.assertIn(rewrite.REWRITE_RUNTIME_CUDA_INDEX_URL, command)

    def test_runtime_install_display_command_quotes_version_specifier(self):
        command = ["python", "-m", "pip", "install", rewrite.REWRITE_RUNTIME_PACKAGE]
        self.assertIn(
            f'"{rewrite.REWRITE_RUNTIME_PACKAGE}"',
            rewrite._format_command_for_display(command),
        )

    def test_runtime_install_is_skipped_when_available(self):
        with (
            mock.patch.object(rewrite, "_has_rewrite_runtime", return_value=True),
            mock.patch.object(rewrite.subprocess, "run") as mock_run,
        ):
            rewrite.ensure_rewrite_runtime()
            mock_run.assert_not_called()

    def test_runtime_install_failure_has_manual_command(self):
        with (
            mock.patch.object(rewrite, "_has_rewrite_runtime", return_value=False),
            mock.patch.object(rewrite.subprocess, "run", return_value=mock.Mock(returncode=1)),
        ):
            with self.assertRaisesRegex(RuntimeError, "Run this manually"):
                rewrite.ensure_rewrite_runtime()

    def test_runtime_install_success_rechecks_import(self):
        with (
            mock.patch.object(rewrite, "_has_rewrite_runtime", side_effect=[False, True]),
            mock.patch.object(rewrite.subprocess, "run", return_value=mock.Mock(returncode=0)) as mock_run,
            mock.patch.object(rewrite.importlib, "invalidate_caches") as mock_invalidate,
        ):
            rewrite.ensure_rewrite_runtime()
            mock_run.assert_called_once()
            mock_invalidate.assert_called_once()

    def test_runtime_install_is_not_attempted_inside_frozen_app(self):
        with (
            mock.patch.object(rewrite, "_has_rewrite_runtime", return_value=False),
            mock.patch.object(rewrite.sys, "frozen", True, create=True),
            mock.patch.object(rewrite.subprocess, "run") as mock_run,
        ):
            with self.assertRaisesRegex(RuntimeError, "not bundled"):
                rewrite.ensure_rewrite_runtime()
            mock_run.assert_not_called()

    def test_load_model_defaults_to_gpu_offload(self):
        fake_llama = types.SimpleNamespace(Llama=mock.Mock(return_value=object()))
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "model.gguf"
            model_path.write_bytes(b"model")
            with (
                mock.patch.object(rewrite, "_llm", None),
                mock.patch.object(rewrite, "_llm_key", None),
                mock.patch.object(rewrite, "ensure_rewrite_runtime"),
                mock.patch.dict(sys.modules, {"llama_cpp": fake_llama}),
            ):
                rewrite._load_model({"model_path": str(model_path)})
                self.assertEqual(fake_llama.Llama.call_args.kwargs["n_gpu_layers"], -1)


class RewriteConfigTests(unittest.TestCase):
    def test_rewrite_env_numeric_values_are_coerced(self):
        env = {
            "WHISPERO_REWRITE_CONTEXT_WINDOW": "4096",
            "WHISPERO_REWRITE_MAX_TOKENS": "96",
            "WHISPERO_REWRITE_TEMPERATURE": "0.35",
            "WHISPERO_REWRITE_THREADS": "4",
            "WHISPERO_REWRITE_GPU_LAYERS": "-1",
        }
        with mock.patch.dict(config_module.os.environ, env, clear=True):
            rewrite_config = _apply_env(_normalize({}))["rewrite"]

        self.assertEqual(rewrite_config["context_window"], 4096)
        self.assertEqual(rewrite_config["max_tokens"], 96)
        self.assertEqual(rewrite_config["temperature"], 0.35)
        self.assertEqual(rewrite_config["threads"], 4)
        self.assertEqual(rewrite_config["gpu_layers"], -1)

        self.assertIs(type(rewrite_config["context_window"]), int)
        self.assertIs(type(rewrite_config["max_tokens"]), int)
        self.assertIs(type(rewrite_config["temperature"]), float)
        self.assertIs(type(rewrite_config["threads"]), int)
        self.assertIs(type(rewrite_config["gpu_layers"]), int)


if __name__ == "__main__":
    unittest.main()
