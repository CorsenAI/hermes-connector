"""Companion installation and local pairing-code tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_connector_installer_test", ROOT / "scripts" / "install_companion.py"
)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(installer)


class CompanionInstallerTests(unittest.TestCase):
    def test_plugin_target_symlink_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            plugins = home / "plugins"
            destination = plugins / "other-plugin"
            destination.mkdir(parents=True)
            marker = destination / "keep.txt"
            marker.write_text("untouched", encoding="utf-8")
            target = plugins / installer.PLUGIN_NAME
            try:
                target.symlink_to(destination, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "unsafe Hermes plugin target"):
                installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertTrue(target.is_symlink())

    def test_plugins_directory_symlink_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            home.mkdir()
            destination = Path(temp) / "other-plugins"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_text("untouched", encoding="utf-8")
            try:
                (home / "plugins").symlink_to(destination, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "unsafe Hermes plugins directory"):
                installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertFalse((destination / installer.PLUGIN_NAME).exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows junction semantics")
    def test_plugins_directory_junction_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            home.mkdir()
            destination = Path(temp) / "other-plugins"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_text("untouched", encoding="utf-8")
            junction = home / "plugins"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(destination)],
                capture_output=True,
                text=True,
            )
            if created.returncode:
                self.skipTest(f"directory junctions are unavailable: {created.stderr or created.stdout}")
            try:
                with self.assertRaisesRegex(RuntimeError, "unsafe Hermes plugins directory"):
                    installer.install(ROOT / "hermes-plugin", home)
            finally:
                os.rmdir(junction)
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertFalse((destination / installer.PLUGIN_NAME).exists())

    def test_install_lock_symlink_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            root.mkdir()
            destination = Path(temp) / "keep.txt"
            destination.write_text("untouched", encoding="utf-8")
            lock = root / installer.INSTALL_LOCK_NAME
            try:
                lock.symlink_to(destination)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "unsafe Hermes Connector install lock"):
                with installer.installation_lock(root):
                    pass
            self.assertEqual(destination.read_text(encoding="utf-8"), "untouched")

    def test_config_symlink_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            home.mkdir()
            destination = Path(temp) / "keep.yaml"
            destination.write_text("plugins:\n  enabled: [keep]\n", encoding="utf-8")
            config = home / "config.yaml"
            try:
                config.symlink_to(destination)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "unsafe Hermes config target"):
                installer.config_snapshot(home)
            self.assertEqual(
                destination.read_text(encoding="utf-8"), "plugins:\n  enabled: [keep]\n"
            )

    def test_profile_home_normalizes_to_shared_hermes_root(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(profile)}):
                self.assertEqual(installer.default_hermes_home(), Path(temp).resolve())
            self.assertEqual(installer.normalize_hermes_home(profile), Path(temp).resolve())

    def test_shared_home_and_existing_profiles_receive_the_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            work = root / "profiles" / "work"
            work.mkdir(parents=True)
            (work / "config.yaml").write_text("plugins:\n  enabled: []\n", encoding="utf-8")
            ignored = root / "profiles" / "incomplete"
            ignored.mkdir(parents=True)

            homes = installer.installation_homes(root)
            self.assertEqual(homes, [root.resolve(), work.resolve()])
            for home in homes:
                target, _ = installer.install(ROOT / "hermes-plugin", home)
                self.assertTrue((target / "plugin.yaml").is_file())
            self.assertFalse((ignored / "plugins" / installer.PLUGIN_NAME).exists())

    def test_multi_profile_install_replaces_stale_021_payload_byte_for_byte(self):
        """A 0.2.1 label must not hide a protocol-v3 broker in any profile."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            profiles = [
                root / "profiles" / "personal",
                root / "profiles" / "work",
            ]
            for profile in profiles:
                profile.mkdir(parents=True)
                (profile / "config.yaml").write_text(
                    "plugins:\n  enabled: []\n", encoding="utf-8"
                )

            source = ROOT / "hermes-plugin"
            expected_homes = [root.resolve(), *(profile.resolve() for profile in profiles)]
            for home in expected_homes:
                target = home / "plugins" / installer.PLUGIN_NAME
                target.mkdir(parents=True)
                for name in installer.PLUGIN_FILES:
                    (target / name).write_bytes(f"stale payload: {name}\n".encode("utf-8"))
                (target / "plugin.yaml").write_text(
                    "name: hermes-connector\nversion: 0.2.1\n", encoding="utf-8"
                )
                (target / "broker.py").write_text(
                    "PROTOCOL_VERSION = 3\nDEFAULT_PORT = 8765\n", encoding="utf-8"
                )
                (target / "stale-only.txt").write_text("remove me", encoding="utf-8")

            result = installer.main([
                "--hermes-home", str(root),
                "--source", str(source),
                "--no-enable",
                "--no-show-code",
            ])

            self.assertEqual(result, 0)
            self.assertEqual(installer.installation_homes(root), expected_homes)
            source_bytes = {
                name: (source / name).read_bytes() for name in installer.PLUGIN_FILES
            }
            for home in expected_homes:
                target = home / "plugins" / installer.PLUGIN_NAME
                self.assertEqual(
                    {path.name for path in target.iterdir() if path.is_file()},
                    set(installer.PLUGIN_FILES),
                )
                for name, expected in source_bytes.items():
                    with self.subTest(home=home, payload=name):
                        self.assertEqual((target / name).read_bytes(), expected)

                installed_manifest = (target / "plugin.yaml").read_text(encoding="utf-8")
                installed_broker = (target / "broker.py").read_text(encoding="utf-8")
                self.assertRegex(installed_manifest, r"(?m)^version:\s*0\.2\.4\s*$")
                self.assertRegex(installed_broker, r"(?m)^PROTOCOL_VERSION\s*=\s*4\s*$")
                self.assertRegex(installed_broker, r"(?m)^DEFAULT_PORT\s*=\s*8766\s*$")

    def test_release_version_protocol_and_port_contract_is_consistent(self):
        plugin_source = (ROOT / "hermes-plugin" / "plugin.yaml").read_text(
            encoding="utf-8"
        )
        broker_source = (ROOT / "hermes-plugin" / "broker.py").read_text(
            encoding="utf-8"
        )
        bridge_client_source = (ROOT / "hermes-plugin" / "bridge_client.py").read_text(
            encoding="utf-8"
        )
        extension_manifest = json.loads(
            (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
        )
        extension_protocol = (ROOT / "extension" / "src" / "protocol.js").read_text(
            encoding="utf-8"
        )

        plugin_version = re.search(r"(?m)^version:\s*([^\s]+)\s*$", plugin_source)
        broker_protocol = re.search(
            r"(?m)^PROTOCOL_VERSION\s*=\s*(\d+)\s*$", broker_source
        )
        broker_port = re.search(r"(?m)^DEFAULT_PORT\s*=\s*(\d+)\s*$", broker_source)
        extension_protocol_version = re.search(
            r"PROTOCOL_VERSION\s*=\s*(\d+)", extension_protocol
        )
        extension_port = re.search(
            r'DEFAULT_BRIDGE_URL\s*=\s*"ws://127\.0\.0\.1:(\d+)/?"',
            extension_protocol,
        )

        for label, match in (
            ("plugin version", plugin_version),
            ("broker protocol", broker_protocol),
            ("broker port", broker_port),
            ("extension protocol", extension_protocol_version),
            ("extension port", extension_port),
        ):
            with self.subTest(contract=label):
                self.assertIsNotNone(match, f"missing {label} declaration")

        self.assertEqual(extension_manifest["version"], "0.2.4")
        self.assertEqual(plugin_version.group(1), extension_manifest["version"])
        self.assertEqual(int(broker_protocol.group(1)), 4)
        self.assertEqual(int(extension_protocol_version.group(1)), 4)
        self.assertEqual(broker_protocol.group(1), extension_protocol_version.group(1))
        self.assertEqual(int(broker_port.group(1)), 8766)
        self.assertEqual(broker_port.group(1), extension_port.group(1))
        self.assertIn("broker.PROTOCOL_VERSION", bridge_client_source)
        self.assertIn("broker.DEFAULT_PORT", bridge_client_source)

        payload_files = {
            path.name for path in (ROOT / "hermes-plugin").iterdir() if path.is_file()
        }
        self.assertEqual(set(installer.PLUGIN_FILES), payload_files)

    def test_profiles_directory_symlink_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            root.mkdir()
            destination = Path(temp) / "outside-profiles"
            work = destination / "work"
            work.mkdir(parents=True)
            marker = work / "config.yaml"
            marker.write_text("plugins:\n  enabled: [keep]\n", encoding="utf-8")
            profiles = root / "profiles"
            try:
                profiles.symlink_to(destination, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(RuntimeError, "unsafe Hermes profiles directory"):
                installer.installation_homes(root)
            self.assertEqual(marker.read_text(encoding="utf-8"), "plugins:\n  enabled: [keep]\n")

    @unittest.skipUnless(sys.platform == "win32", "Windows junction semantics")
    def test_profiles_directory_junction_is_rejected_without_touching_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            root.mkdir()
            destination = Path(temp) / "outside-profiles"
            work = destination / "work"
            work.mkdir(parents=True)
            marker = work / "config.yaml"
            marker.write_text("plugins:\n  enabled: [keep]\n", encoding="utf-8")
            profiles = root / "profiles"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(profiles), str(destination)],
                capture_output=True,
                text=True,
            )
            if created.returncode:
                self.skipTest(f"directory junctions are unavailable: {created.stderr or created.stdout}")
            try:
                with self.assertRaisesRegex(RuntimeError, "unsafe Hermes profiles directory"):
                    installer.installation_homes(root)
            finally:
                os.rmdir(profiles)
            self.assertEqual(marker.read_text(encoding="utf-8"), "plugins:\n  enabled: [keep]\n")

    def test_enable_uses_the_exact_profile_home(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            profile.mkdir(parents=True)
            inventory = mock.Mock(stdout="[]")
            with mock.patch.object(installer, "find_hermes", return_value="hermes-test"), \
                    mock.patch.object(installer.subprocess, "run", side_effect=[inventory, mock.DEFAULT]) as run:
                installer.enable_plugin(profile)
            self.assertEqual(run.call_args_list[1].args[0], [
                "hermes-test", "plugins", "enable", "hermes-connector", "--no-allow-tool-override",
            ])
            self.assertTrue(
                Path(run.call_args_list[1].kwargs["env"]["HERMES_HOME"]).samefile(profile)
            )
            self.assertTrue(run.call_args_list[1].kwargs["check"])

    def test_enable_migrates_the_conflicting_legacy_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            profile.mkdir(parents=True)
            inventory = mock.Mock(stdout=json.dumps([{
                "name": "agent-bridge",
                "status": "enabled",
                "version": installer.LEGACY_PLUGIN_VERSION,
                "description": installer.LEGACY_DESCRIPTION_PREFIX + " legacy bridge",
            }]))
            with mock.patch.object(installer, "find_hermes", return_value="hermes-test"), \
                    mock.patch.object(installer.subprocess, "run", side_effect=[inventory, mock.DEFAULT, mock.DEFAULT]) as run:
                installer.enable_plugin(profile)
            commands = [item.args[0] for item in run.call_args_list]
            self.assertEqual(commands[1], ["hermes-test", "plugins", "disable", "agent-bridge"])
            self.assertEqual(commands[2], [
                "hermes-test", "plugins", "enable", "hermes-connector", "--no-allow-tool-override",
            ])

    def test_unrelated_agent_bridge_name_is_not_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            profile.mkdir(parents=True)
            inventory = mock.Mock(stdout=json.dumps([{
                "name": "agent-bridge",
                "status": "enabled",
                "version": "9.9.9",
                "description": "A different third-party integration",
            }]))
            with mock.patch.object(installer, "find_hermes", return_value="hermes-test"), \
                    mock.patch.object(installer.subprocess, "run", return_value=inventory) as run:
                with self.assertRaisesRegex(RuntimeError, "unrelated enabled plugin"):
                    installer.enable_plugin(profile)
            self.assertEqual(run.call_count, 1)

    def test_mixed_known_and_unrelated_agent_bridge_is_not_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            profile.mkdir(parents=True)
            inventory = mock.Mock(stdout=json.dumps([
                {
                    "name": "agent-bridge",
                    "status": "enabled",
                    "version": installer.LEGACY_PLUGIN_VERSION,
                    "description": installer.LEGACY_DESCRIPTION_PREFIX + " legacy bridge",
                },
                {
                    "name": "agent-bridge",
                    "status": "enabled",
                    "version": "9.9.9",
                    "description": "A different third-party integration",
                },
            ]))
            with mock.patch.object(installer, "find_hermes", return_value="hermes-test"), \
                    mock.patch.object(installer.subprocess, "run", return_value=inventory) as run:
                with self.assertRaisesRegex(RuntimeError, "unrelated enabled plugin"):
                    installer.enable_plugin(profile)
            self.assertEqual(run.call_count, 1)

    def test_failed_migration_restores_the_exact_plugin_config(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profiles" / "work"
            profile.mkdir(parents=True)
            config = profile / "config.yaml"
            original = (
                "plugins:\n"
                "  enabled: [agent-bridge]\n"
                "  entries:\n"
                "    agent-bridge:\n"
                "      allow_tool_override: true\n"
                "unrelated: keep-me\n"
            ).encode("utf-8")
            config.write_bytes(original)

            def run(command, **_kwargs):
                if command[2] == "list":
                    return mock.Mock(stdout=json.dumps([{
                        "name": "agent-bridge",
                        "status": "enabled",
                        "version": installer.LEGACY_PLUGIN_VERSION,
                        "description": installer.LEGACY_DESCRIPTION_PREFIX + " legacy bridge",
                    }]))
                if command[2:4] == ["disable", "agent-bridge"]:
                    config.write_text("plugins:\n  disabled: [agent-bridge]\n", encoding="utf-8")
                    return mock.DEFAULT
                config.write_text("plugins:\n  enabled: [hermes-connector]\n", encoding="utf-8")
                raise subprocess.CalledProcessError(1, command)

            with mock.patch.object(installer, "find_hermes", return_value="hermes-test"), \
                    mock.patch.object(installer.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.enable_plugin(profile)
            self.assertEqual(config.read_bytes(), original)

    def test_install_is_atomic_and_preserves_previous_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, previous = installer.install(ROOT / "hermes-plugin", home)
            self.assertIsNone(previous)
            self.assertEqual(
                {path.name for path in target.iterdir() if path.is_file()},
                set(installer.PLUGIN_FILES),
            )
            marker = target / "local-note.txt"
            marker.write_text("preserve me", encoding="utf-8")

            target2, previous2 = installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(target2, target)
            self.assertIsNotNone(previous2)
            self.assertEqual((previous2 / "local-note.txt").read_text(encoding="utf-8"), "preserve me")
            self.assertFalse((target2 / "local-note.txt").exists())

    def test_verification_failure_after_publish_restores_exact_previous_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            plugins = home / "plugins"
            target = plugins / installer.PLUGIN_NAME
            nested = target / "legacy-data"
            nested.mkdir(parents=True)
            (target / "plugin.yaml").write_bytes(b"old manifest\r\nversion: 0.1.0\r\n")
            (target / "legacy-only.bin").write_bytes(b"\x00old companion\xff")
            (nested / "keep.dat").write_bytes(b"exact nested bytes\x00")

            def snapshot_tree(root):
                return {
                    path.relative_to(root).as_posix(): (
                        None if path.is_dir() else path.read_bytes()
                    )
                    for path in root.rglob("*")
                }

            previous_snapshot = snapshot_tree(target)

            def reject_published_payload(source, published_target):
                self.assertTrue(published_target.samefile(target))
                self.assertEqual(
                    {path.name for path in published_target.iterdir() if path.is_file()},
                    set(installer.PLUGIN_FILES),
                )
                for name in installer.PLUGIN_FILES:
                    self.assertEqual(
                        (published_target / name).read_bytes(),
                        (source / name).read_bytes(),
                    )
                raise RuntimeError("simulated post-publication verification failure")

            with mock.patch.object(
                installer,
                "verify_installed_payload",
                side_effect=reject_published_payload,
            ) as verify:
                with self.assertRaisesRegex(RuntimeError, "post-publication"):
                    installer.install(ROOT / "hermes-plugin", home)

            verify.assert_called_once()
            self.assertEqual(snapshot_tree(target), previous_snapshot)
            self.assertEqual(
                {path.name for path in plugins.iterdir()},
                {installer.PLUGIN_NAME},
            )

    def test_keyboard_interrupt_between_payload_swaps_restores_previous_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, _ = installer.install(ROOT / "hermes-plugin", home)
            marker = target / "keep.txt"
            marker.write_text("previous payload", encoding="utf-8")
            real_replace = installer.os.replace

            def interrupt_staged_swap(source, destination):
                source_path = Path(source)
                destination_path = Path(destination)
                if (source_path.name.startswith(f".{installer.PLUGIN_NAME}-install-") and
                        destination_path == target):
                    raise KeyboardInterrupt()
                return real_replace(source, destination)

            with mock.patch.object(installer.os, "replace", side_effect=interrupt_staged_swap):
                with self.assertRaises(KeyboardInterrupt):
                    installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(marker.read_text(encoding="utf-8"), "previous payload")

    def test_keyboard_interrupt_after_backup_move_restores_previous_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, _ = installer.install(ROOT / "hermes-plugin", home)
            marker = target / "keep.txt"
            marker.write_text("previous payload", encoding="utf-8")
            real_replace = installer.os.replace
            interrupted = False

            def interrupt_after_backup(source, destination):
                nonlocal interrupted
                source_path = Path(source)
                destination_path = Path(destination)
                if source_path == target and destination_path.name.startswith(
                        f".{installer.PLUGIN_NAME}-previous-") and not interrupted:
                    interrupted = True
                    real_replace(source, destination)
                    raise KeyboardInterrupt()
                return real_replace(source, destination)

            with mock.patch.object(installer.os, "replace", side_effect=interrupt_after_backup):
                with self.assertRaises(KeyboardInterrupt):
                    installer.install(ROOT / "hermes-plugin", home)
            self.assertEqual(marker.read_text(encoding="utf-8"), "previous payload")

    def test_multi_profile_failure_rolls_back_every_config_and_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            profile = root / "profiles" / "work"
            original_configs = {}
            for home, label in ((root, "shared"), (profile, "work")):
                home.mkdir(parents=True, exist_ok=True)
                config = home / "config.yaml"
                content = f"plugins:\n  enabled: [old-{label}]\n".encode("utf-8")
                config.write_bytes(content)
                original_configs[config] = content
                payload = home / "plugins" / installer.PLUGIN_NAME
                payload.mkdir(parents=True)
                (payload / "old-marker.txt").write_text(label, encoding="utf-8")

            attempts = []

            def fail_second(home):
                attempts.append(home)
                (home / "config.yaml").write_text(
                    "plugins:\n  enabled: [hermes-connector]\n", encoding="utf-8"
                )
                if len(attempts) == 2:
                    raise RuntimeError("simulated second-profile failure")

            with mock.patch.object(installer, "enable_plugin", side_effect=fail_second):
                with self.assertRaisesRegex(RuntimeError, "second-profile failure"):
                    installer.main([
                        "--hermes-home", str(root),
                        "--source", str(ROOT / "hermes-plugin"),
                        "--no-show-code",
                    ])

            for config, content in original_configs.items():
                self.assertEqual(config.read_bytes(), content)
                payload = config.parent / "plugins" / installer.PLUGIN_NAME
                self.assertTrue((payload / "old-marker.txt").is_file())
                self.assertFalse((payload / "plugin.yaml").exists())

    def test_concurrent_installer_is_rejected_before_payload_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "hermes"
            with installer.installation_lock(root):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    installer.main([
                        "--hermes-home", str(root),
                        "--source", str(ROOT / "hermes-plugin"),
                        "--no-enable",
                        "--no-show-code",
                    ])
            self.assertFalse((root / "plugins" / installer.PLUGIN_NAME).exists())

    def test_pairing_code_is_persistent_and_not_in_bridge_status(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "hermes"
            target, _ = installer.install(ROOT / "hermes-plugin", home)
            first = installer.pairing_code(target, home)
            second = installer.pairing_code(target, home)
            self.assertEqual(first, second)
            self.assertRegex(first, re.compile(r"^[0-9a-f]{64}$"))
            client_source = (target / "bridge_client.py").read_text(encoding="utf-8")
            self.assertNotIn('"pairing_code": self.secret', client_source)


if __name__ == "__main__":
    unittest.main()
