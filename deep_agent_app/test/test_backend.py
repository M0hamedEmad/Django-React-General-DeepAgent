"""Security and isolation tests for the local agent sandbox."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.local_shell import LocalShellBackend
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from deep_agent_app.agent.backend import (
    BubblewrapBackend,
    ReadOnlyFilesystemBackend,
    ReadOnlyScopedFilesystemBackend,
    ScopedFilesystemBackend,
    WorkspaceLayout,
    WorkspaceContextMiddleware,
    WorkspaceScope,
    bind_workspace,
    current_workspace_scope,
    migrate_legacy_user_workspace,
)


class WorkspaceBackendTests(SimpleTestCase):
    def test_read_only_backends_reject_every_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "note.txt").write_text("safe", encoding="utf-8")
            layout = WorkspaceLayout(root / "workspaces")
            layout.paths(
                WorkspaceScope(workspace_id="workspace-1", thread_id="thread-1")
            )

            static = ReadOnlyFilesystemBackend(root_dir=root, virtual_mode=True)
            scoped = ReadOnlyScopedFilesystemBackend(
                workspace_root=layout.root,
                user_root=True,
            )

            self.assertEqual(static.read("/note.txt").file_data["content"], "safe")
            self.assertTrue(static.write("/new.txt", "content").error)
            self.assertTrue(static.edit("/note.txt", "safe", "changed").error)
            self.assertTrue(static.delete("/note.txt").error)
            self.assertTrue(static.upload_files([("/upload.txt", b"content")])[0].error)

            with bind_workspace(workspace_id="workspace-1", thread_id="thread-1"):
                self.assertTrue(scoped.write("/other.txt", "content").error)

    def test_workspace_is_created_only_when_mutated(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspaces"
            current = ScopedFilesystemBackend(root)
            scope = WorkspaceScope(workspace_id="workspace-1", thread_id="thread-1")
            conversation_root = current.layout.paths(scope).conversation_root

            with bind_workspace("workspace-1", "thread-1"):
                self.assertTrue(current.read("/missing.txt").error)
            self.assertFalse(conversation_root.exists())

            with bind_workspace("workspace-1", "thread-1"):
                self.assertIsNone(current.write("/created.txt", "content").error)
            self.assertTrue(conversation_root.is_dir())

    def test_uncreated_workspace_root_lists_virtual_routes_without_creation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workspace_root = root / "workspaces"
            skills_root = root / "skills"
            skills_root.mkdir()
            current = ScopedFilesystemBackend(workspace_root)
            composite = CompositeBackend(
                default=current,
                routes={
                    "/skills/": ReadOnlyFilesystemBackend(
                        root_dir=skills_root,
                        virtual_mode=True,
                    ),
                    "/conversations/": ReadOnlyScopedFilesystemBackend(
                        workspace_root,
                        user_root=True,
                    ),
                },
            )
            scope = WorkspaceScope(
                workspace_id="workspace-1",
                thread_id="thread-1",
            )
            conversation_root = current.layout.paths(scope).conversation_root

            with bind_workspace(scope.workspace_id, scope.thread_id):
                sync_result = composite.ls("/")
                async_result = async_to_sync(composite.als)("/")

            expected = ["/conversations/", "/skills/"]
            self.assertEqual(
                [entry["path"] for entry in sync_result.entries],
                expected,
            )
            self.assertEqual(
                [entry["path"] for entry in async_result.entries],
                expected,
            )
            self.assertFalse(conversation_root.exists())

    def test_conversation_and_user_roots_follow_the_active_scope(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspaces"
            conversations = ScopedFilesystemBackend(root, user_root=True)
            current = ScopedFilesystemBackend(root)

            with bind_workspace("7", "chat-a"):
                self.assertIsNone(current.write("/own.txt", "alpha").error)
            with bind_workspace("7", "chat-b"):
                self.assertIsNone(current.write("/own.txt", "beta").error)
            with bind_workspace("8", "chat-c"):
                self.assertIsNone(current.write("/own.txt", "private").error)

            with bind_workspace("7", "chat-a"):
                own = current.read("/own.txt")
                sibling = conversations.read("/chat-b/own.txt")
                with self.assertRaisesRegex(ValueError, "traversal"):
                    conversations.read("/../8/chat-c/own.txt")

            self.assertEqual(own.file_data["content"], "alpha")
            self.assertEqual(sibling.file_data["content"], "beta")

    def test_workspace_segments_reject_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "letters, numbers"):
            with bind_workspace("7", "../escape"):
                pass

    def test_middleware_binds_and_resets_the_authenticated_scope(self):
        middleware = WorkspaceContextMiddleware()
        request = SimpleNamespace(
            runtime=SimpleNamespace(
                context=SimpleNamespace(workspace_id="workspace-7", thread_id="chat-a")
            )
        )

        scope = middleware.wrap_tool_call(
            request,
            lambda _request: current_workspace_scope(),
        )

        self.assertEqual(
            (scope.workspace_id, scope.thread_id),
            ("workspace-7", "chat-a"),
        )
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            current_workspace_scope()

    def test_delete_removes_only_the_requested_conversation(self):
        with TemporaryDirectory() as directory:
            layout = WorkspaceLayout(Path(directory) / "workspaces")
            with bind_workspace("7", "chat-a"):
                paths_a = layout.ensure_conversation(current_workspace_scope())
                (paths_a.conversation_root / "a.txt").write_text("a")
            with bind_workspace("7", "chat-b"):
                paths_b = layout.ensure_conversation(current_workspace_scope())
                (paths_b.conversation_root / "b.txt").write_text("b")

            layout.delete_conversation("7", "chat-a")

            self.assertFalse(paths_a.conversation_root.exists())
            self.assertTrue(paths_b.conversation_root.exists())

    def test_legacy_numeric_user_workspace_is_moved_to_uuid(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspaces"
            legacy_file = root / "7" / "chat-a" / "note.txt"
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_text("preserved", encoding="utf-8")

            migrate_legacy_user_workspace(
                "7",
                "workspace-uuid",
                workspace_root=root,
            )

            migrated = root / "workspace-uuid" / "chat-a" / "note.txt"
            self.assertEqual(migrated.read_text(encoding="utf-8"), "preserved")
            self.assertFalse((root / "7").exists())


class BubblewrapBackendTests(SimpleTestCase):
    def _backend(
        self,
        directory,
        *,
        max_output_bytes=100_000,
        network_access=False,
    ):
        root = Path(directory)
        skills = root / "skills"
        skills.mkdir()
        (skills / "SKILL.md").write_text("public skill", encoding="utf-8")
        return BubblewrapBackend(
            workspace_root=root / "workspaces",
            skills_root=skills,
            bwrap_path=shutil.which("bwrap") or "/usr/bin/bwrap",
            network_access=network_access,
            slirp4netns_path=(
                shutil.which("slirp4netns") or "/usr/bin/slirp4netns"
            ),
            max_output_bytes=max_output_bytes,
        )

    def test_execute_uses_argument_vector_and_minimal_mounts(self):
        with TemporaryDirectory() as directory:
            backend = self._backend(directory, max_output_bytes=8)
            process = Mock(pid=321, returncode=3)
            process.communicate.return_value = (
                "123456789",
                "__DEEP_AGENT_SANDBOX_READY__\nwarning",
            )

            with (
                bind_workspace("7", "chat-a"),
                patch(
                    "deep_agent_app.agent.backend.subprocess.Popen",
                    return_value=process,
                ) as popen,
            ):
                response = backend.execute("printf safe")

            argv = popen.call_args.args[0]
            self.assertEqual(argv[-1], "printf safe")
            self.assertIn("__DEEP_AGENT_SANDBOX_READY__", argv[-3])
            self.assertIn("--unshare-all", argv)
            self.assertIn("--clearenv", argv)
            self.assertNotIn("--share-net", argv)
            self.assertNotIn("shell", popen.call_args.kwargs)
            self.assertEqual(popen.call_args.kwargs["env"], {})
            self.assertEqual(response.exit_code, 3)
            self.assertTrue(response.truncated)
            self.assertIn("Exit code: 3", response.output)

    def test_network_mode_uses_private_namespace_and_workspace_venv(self):
        with TemporaryDirectory() as directory:
            backend = self._backend(directory, network_access=True)
            with bind_workspace("7", "chat-a"):
                backend.layout.ensure_conversation(current_workspace_scope())
                argv = backend._command("pip install idna", info_fd=10, resolv_fd=11)

            self.assertIn("--unshare-all", argv)
            self.assertNotIn("--share-net", argv)
            self.assertEqual(argv[argv.index("--info-fd") + 1], "10")
            self.assertEqual(argv[argv.index("--ro-bind-data") + 1], "11")
            self.assertIn("/etc/resolv.conf", argv)
            self.assertIn("/workspace/.venv/bin:/usr/bin:/bin", argv)
            self.assertIn("PIP_NO_INPUT", argv)

    def test_network_bridge_blocks_host_loopback_and_enables_seccomp(self):
        with TemporaryDirectory() as directory:
            backend = self._backend(directory, network_access=True)
            process = Mock(pid=321, returncode=0)
            process.communicate.return_value = ("", "")
            with (
                patch(
                    "deep_agent_app.agent.backend.subprocess.Popen",
                    return_value=process,
                ) as popen,
                patch(
                    "deep_agent_app.agent.backend.select.select",
                    return_value=([1], [], []),
                ),
                patch("deep_agent_app.agent.backend.os.read", return_value=b"1"),
            ):
                network = backend._start_network(456)
                backend._stop_network(network)

            argv = popen.call_args.args[0]
            self.assertIn("--disable-host-loopback", argv)
            self.assertIn("--enable-seccomp", argv)
            self.assertNotIn("--enable-sandbox", argv)
            self.assertEqual(argv[-2:], ["456", "tap0"])

    def test_sandbox_setup_error_is_sanitized_and_does_not_leave_empty_workspace(self):
        with TemporaryDirectory() as directory:
            backend = self._backend(directory)
            process = Mock(pid=321, returncode=1)
            process.communicate.return_value = (
                "",
                "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted",
            )

            with (
                bind_workspace("workspace-7", "chat-a"),
                patch(
                    "deep_agent_app.agent.backend.subprocess.Popen",
                    return_value=process,
                ),
                self.assertLogs("deep_agent_app.agent.backend", level="ERROR"),
            ):
                response = backend.execute("pwd")

            self.assertEqual(response.exit_code, 1)
            self.assertIn("host blocked", response.output)
            self.assertNotIn("RTM_NEWADDR", response.output)
            self.assertFalse(
                (Path(directory) / "workspaces" / "workspace-7" / "chat-a").exists()
            )

    def test_timeout_kills_the_sandbox_process_group(self):
        with TemporaryDirectory() as directory:
            backend = self._backend(directory)
            process = Mock(pid=321)
            process.communicate.side_effect = [
                subprocess.TimeoutExpired("bwrap", 1),
                ("", ""),
            ]

            with (
                bind_workspace("7", "chat-a"),
                patch(
                    "deep_agent_app.agent.backend.subprocess.Popen",
                    return_value=process,
                ),
                patch("deep_agent_app.agent.backend.os.killpg") as killpg,
            ):
                response = backend.execute("sleep 60", timeout=1)

            killpg.assert_called_once_with(321, 9)
            self.assertEqual(response.exit_code, 124)
            self.assertIn("timed out", response.output)

    def test_missing_bubblewrap_fails_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / "skills"
            skills.mkdir()

            with self.assertRaisesRegex(
                ImproperlyConfigured,
                "Bubblewrap is required",
            ):
                BubblewrapBackend(
                    workspace_root=root / "workspaces",
                    skills_root=skills,
                    bwrap_path=root / "missing-bwrap",
                )

    def test_missing_network_helper_fails_closed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / "skills"
            skills.mkdir()

            with self.assertRaisesRegex(
                ImproperlyConfigured,
                "slirp4netns is required",
            ):
                BubblewrapBackend(
                    workspace_root=root / "workspaces",
                    skills_root=skills,
                    bwrap_path=shutil.which("bwrap") or "/usr/bin/bwrap",
                    network_access=True,
                    slirp4netns_path=root / "missing-slirp4netns",
                )

    @skipUnless(shutil.which("bwrap"), "Bubblewrap is not installed")
    def test_real_sandbox_hides_host_and_enforces_read_only_mounts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self._backend(directory)
            sibling = ScopedFilesystemBackend(root / "workspaces")
            with bind_workspace("7", "chat-b"):
                sibling.write("/shared.txt", "same user")

            command = " ; ".join(
                [
                    'test "$(pwd)" = /workspace',
                    "test -r /skills/SKILL.md",
                    "test -r /conversations/chat-b/shared.txt",
                    "test ! -e /home",
                    "test ! -e /var/run/docker.sock",
                    "if touch /skills/blocked 2>/dev/null; then exit 10; fi",
                    "if touch /conversations/blocked 2>/dev/null; then exit 11; fi",
                    "touch /workspace/allowed",
                ]
            )
            with bind_workspace("7", "chat-a"):
                response = backend.execute(command)

            self.assertEqual(response.exit_code, 0, response.output)
            self.assertTrue(
                (root / "workspaces" / "7" / "chat-a" / "allowed").is_file()
            )
            self.assertFalse((root / "skills" / "blocked").exists())
            self.assertFalse((root / "workspaces" / "7" / "blocked").exists())

    @skipUnless(
        os.environ.get("DEEP_AGENT_RUN_NETWORK_TESTS") == "1",
        "network sandbox tests are opt-in",
    )
    @skipUnless(
        shutil.which("bwrap") and shutil.which("slirp4netns"),
        "Bubblewrap and slirp4netns are required",
    )
    def test_real_network_supports_workspace_venv_and_pip(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = self._backend(directory, network_access=True)
            with bind_workspace("7", "chat-a"):
                response = backend.execute(
                    "python3 -m venv .venv && "
                    "pip install --no-cache-dir idna==3.10 && "
                    'python -c "import idna; print(idna.__version__)"',
                    timeout=120,
                )

            self.assertEqual(response.exit_code, 0, response.output)
            self.assertIn("Successfully installed idna-3.10", response.output)
            self.assertTrue(
                (
                    root
                    / "workspaces"
                    / "7"
                    / "chat-a"
                    / ".venv"
                    / "bin"
                    / "python"
                ).exists()
            )


class BackendSelectionTests(SimpleTestCase):
    def test_missing_setting_defaults_to_bubblewrap(self):
        from deep_agent_app.agent import skills

        with TemporaryDirectory() as directory:
            with (
                patch.object(skills, "AGENT_WORKSPACE_ROOT", Path(directory)),
                patch.object(skills, "DEEP_AGENT", {}),
                patch.object(skills, "BubblewrapBackend") as bubblewrap,
            ):
                backend = skills.build_agent_backend()

        self.assertIs(backend.default, bubblewrap.return_value)

    def test_local_shell_setting_uses_local_shell_backend(self):
        from deep_agent_app.agent import skills

        with TemporaryDirectory() as directory:
            with (
                patch.object(skills, "AGENT_WORKSPACE_ROOT", Path(directory)),
                patch.object(skills, "DEEP_AGENT", {"sandbox": "local_shell"}),
            ):
                backend = skills.build_agent_backend()

        self.assertIsInstance(backend.default, LocalShellBackend)

    def test_invalid_setting_is_rejected(self):
        from deep_agent_app.agent import skills

        with (
            patch.object(skills, "DEEP_AGENT", {"sandbox": "typo"}),
            self.assertRaisesRegex(ImproperlyConfigured, "bubblewrap.*local_shell"),
        ):
            skills.build_agent_backend()
