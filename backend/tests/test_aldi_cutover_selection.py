from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "tools/verify_aldi_cutover_selection.py"
spec = importlib.util.spec_from_file_location("aldi_cutover_selection", SCRIPT)
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)

CONTAINER = "a" * 64
DIGEST = "b" * 64
IMAGE_ID = "sha256:" + "c" * 64


def fixture(*, raw_source=selection.RAW_SOURCE, image_id=IMAGE_ID,
            running=True, additional_api=False):
    container = {
        "Id": CONTAINER, "Image": image_id,
        "Config": {
            "Image": selection.IMAGE + ":production",
            "Labels": {"com.docker.compose.project": "hermes-deals",
                       "com.docker.compose.service": "api"},
        },
        "State": {"Running": running, "Health": {"Status": "healthy"}},
        "Mounts": [
            {"Type": "bind", "Source": raw_source, "Destination": "/data/raw", "RW": True},
            {"Type": "bind", "Source": selection.CONFIG_SOURCE,
             "Destination": "/app/config", "RW": False},
        ],
    }
    image = {"Id": IMAGE_ID,
             "RepoDigests": [selection.IMAGE + "@sha256:" + DIGEST]}
    calls = []

    def run(args):
        calls.append(args)
        if args[:3] == ["docker", "compose", "ps"]:
            return CONTAINER + "\n"
        if args[:3] == ["docker", "ps", "-a"]:
            return CONTAINER + ("\n" + "d" * 64 if additional_api else "") + "\n"
        if args[:2] == ["docker", "inspect"]:
            return json.dumps([container])
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps([image])
        raise AssertionError(args)

    return run, calls


class AldiCutoverSelectionTests(TestCase):
    def test_docker_reads_use_collector_context_without_shell_overrides(self):
        with patch.object(selection.subprocess, "run") as execute:
            execute.return_value.stdout = "ok"
            self.assertEqual(selection._run(["docker", "compose", "ps", "-q", "api"]), "ok")
        _, kwargs = execute.call_args
        self.assertEqual(kwargs["cwd"], selection.CHECKOUT)
        self.assertEqual(kwargs["env"]["HOME"], "/home/andris")
        self.assertNotIn("COMPOSE_FILE", kwargs["env"])
        self.assertTrue(kwargs["capture_output"])

    def test_same_compose_selection_has_pinned_image_and_adopted_bind(self):
        run, calls = fixture()
        selection.verify(CONTAINER, DIGEST, run=run)
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], ["docker", "compose", "ps", "-q", "api"])
        self.assertTrue(all(args[0] == "docker" for args in calls))

    def test_legacy_raw_bind_stops_before_image_lookup(self):
        run, calls = fixture(raw_source="/home/andris/hermes-deals/data/raw")
        with self.assertRaises(selection.Stop):
            selection.verify(CONTAINER, DIGEST, run=run)
        self.assertEqual(len(calls), 3)

    def test_duplicate_api_container_stops(self):
        run, calls = fixture(additional_api=True)
        with self.assertRaises(selection.Stop):
            selection.verify(CONTAINER, DIGEST, run=run)
        self.assertEqual(len(calls), 2)

    def test_wrong_image_or_stopped_api_stops(self):
        for changed in ({"image_id": "sha256:" + "e" * 64}, {"running": False}):
            with self.subTest(changed=changed):
                run, _ = fixture(**changed)
                with self.assertRaises(selection.Stop):
                    selection.verify(CONTAINER, DIGEST, run=run)

    def test_invalid_arguments_print_only_fixed_stop(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(selection, "_run", side_effect=AssertionError):
            result = selection.main(["--expected-container", "secret",
                                     "--expected-digest", DIGEST])
        self.assertEqual(result, 2)
        self.assertEqual(output.getvalue(), "ALDI_CUTOVER_SELECTION=STOP\n")
