"""Tests for authenticated conversation file delivery."""

import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from deep_agent_app.agent.backend import WorkspaceLayout, WorkspaceScope, bind_workspace
from deep_agent_app.agent.tools.files import present_file
from deep_agent_app.artifacts import artifact_metadata
from deep_agent_app.models import Thread, UserWorkspace


async def response_bytes(response) -> bytes:
    content = response.streaming_content
    if hasattr(content, "__aiter__"):
        return b"".join([chunk async for chunk in content])
    return b"".join(content)


class PresentFileToolTests(TestCase):
    def test_tool_presents_only_existing_safe_regular_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspaces"
            layout = WorkspaceLayout(root)
            scope = WorkspaceScope("workspace-1", "thread-1")
            conversation = layout.ensure_conversation(scope).conversation_root
            (conversation / "report.pdf").write_bytes(b"pdf")
            (conversation / ".private.txt").write_text("private", encoding="utf-8")

            with (
                patch("deep_agent_app.agent.backend.AGENT_WORKSPACE_ROOT", root),
                bind_workspace(scope.workspace_id, scope.thread_id),
            ):
                ready = present_file.invoke(
                    {"path": "/report.pdf", "title": "Quarterly report"}
                )
                missing = present_file.invoke({"path": "/missing.pdf"})
                hidden = present_file.invoke({"path": "/.private.txt"})
                traversal = present_file.invoke({"path": "/../report.pdf"})

            self.assertEqual(ready, "File 'Quarterly report' is ready for the user.")
            for result in (missing, hidden, traversal):
                self.assertTrue(result.startswith("Invalid present_file path:"))
                self.assertNotIn(str(root), result)


class ArtifactMetadataTests(TestCase):
    def test_preview_limits_and_office_archive_validation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            large_text = root / "large.txt"
            large_text.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
            invalid_office = root / "invalid.docx"
            invalid_office.write_bytes(b"not a zip")
            too_many_entries = root / "many.xlsx"
            with zipfile.ZipFile(too_many_entries, "w") as archive:
                for index in range(2_001):
                    archive.writestr(f"entry-{index}", b"")

            self.assertFalse(artifact_metadata(large_text).preview_allowed)
            self.assertEqual(
                artifact_metadata(invalid_office).preview_reason,
                "The Office file is not a valid archive.",
            )
            self.assertEqual(
                artifact_metadata(too_many_entries).preview_reason,
                "The Office file has too many archive entries to preview.",
            )


class ThreadFileApiTests(TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.workspace_root = Path(self.temporary_directory.name) / "workspaces"
        workspace_patcher = patch(
            "deep_agent_app.agent.backend.AGENT_WORKSPACE_ROOT",
            self.workspace_root,
        )
        workspace_patcher.start()
        self.addCleanup(workspace_patcher.stop)

        self.user = User.objects.create_user("file-owner")
        self.other = User.objects.create_user("other-owner")
        self.thread = Thread.objects.create(id="owned-thread", user=self.user)
        self.other_thread = Thread.objects.create(id="other-thread", user=self.other)
        self.workspace = UserWorkspace.objects.create(user=self.user)
        self.other_workspace = UserWorkspace.objects.create(user=self.other)
        self.conversation = self.workspace_root / self.workspace.id.hex / self.thread.id
        self.conversation.mkdir(parents=True)

    def write_file(self, name: str, content: bytes) -> Path:
        path = self.conversation / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def url(self, path: str, *, thread_id: str | None = None) -> str:
        return f"/api/threads/{thread_id or self.thread.id}/files/{path}"

    async def test_authentication_ownership_and_unsafe_paths_are_hidden(self):
        self.write_file("report.txt", b"private")
        unauthenticated = await self.async_client.get(self.url("report.txt"))
        self.assertEqual(unauthenticated.status_code, 401)

        await self.async_client.aforce_login(self.user)
        cross_user = await self.async_client.get(
            self.url("report.txt", thread_id=self.other_thread.id)
        )
        traversal = await self.async_client.get(self.url("%2e%2e/report.txt"))
        hidden = await self.async_client.get(self.url(".secret"))

        self.assertEqual(cross_user.status_code, 404)
        self.assertEqual(traversal.status_code, 404)
        self.assertEqual(hidden.status_code, 404)
        for response in (cross_user, traversal, hidden):
            self.assertNotIn(str(self.workspace_root), response.content.decode())

    async def test_head_preview_and_download_stream_exact_bytes(self):
        payload = b"first,second\n1,2\n"
        self.write_file("sales report.csv", payload)
        await self.async_client.aforce_login(self.user)
        url = self.url("sales%20report.csv")

        head = await self.async_client.head(url)
        preview = await self.async_client.get(url)
        download = await self.async_client.get(f"{url}?download=1")

        self.assertEqual(head.status_code, 200)
        self.assertEqual(head["Content-Length"], str(len(payload)))
        self.assertEqual(head["X-Artifact-Preview"], "available")
        self.assertEqual(head["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(await response_bytes(preview), payload)
        self.assertEqual(await response_bytes(download), payload)
        self.assertIn("inline", preview["Content-Disposition"])
        self.assertIn("attachment", download["Content-Disposition"])
        self.assertEqual(download["Cache-Control"], "private, no-store")
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertEqual(download["Cross-Origin-Resource-Policy"], "same-origin")

    async def test_html_and_svg_previews_receive_sandbox_csp(self):
        self.write_file(
            "dashboard.html", b"<script>document.body.textContent='ok'</script>"
        )
        self.write_file("chart.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        await self.async_client.aforce_login(self.user)

        html = await self.async_client.get(self.url("dashboard.html"))
        svg = await self.async_client.get(self.url("chart.svg"))

        self.assertEqual(html.status_code, 200)
        html_csp = html["Content-Security-Policy"]
        self.assertIn("sandbox allow-scripts", html_csp)
        self.assertIn(
            "script-src 'unsafe-inline' blob: "
            "https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
            html_csp,
        )
        self.assertIn(
            "style-src 'unsafe-inline' https://fonts.googleapis.com "
            "https://cdn.jsdelivr.net",
            html_csp,
        )
        self.assertIn("font-src data: https://fonts.gstatic.com", html_csp)
        self.assertIn("connect-src 'none'", html_csp)
        self.assertNotIn("allow-same-origin", html_csp)
        self.assertEqual(html["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("sandbox", svg["Content-Security-Policy"])

    async def test_unsupported_and_oversized_files_remain_downloadable(self):
        self.write_file("archive.bin", b"opaque")
        self.write_file("large.txt", b"x" * (5 * 1024 * 1024 + 1))
        await self.async_client.aforce_login(self.user)

        for name in ("archive.bin", "large.txt"):
            with self.subTest(name=name):
                head = await self.async_client.head(self.url(name))
                preview = await self.async_client.get(self.url(name))
                download = await self.async_client.get(f"{self.url(name)}?download=1")
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head["X-Artifact-Preview"], "unavailable")
                self.assertEqual(preview.status_code, 415)
                self.assertEqual(download.status_code, 200)
                self.assertIn("attachment", download["Content-Disposition"])
                await response_bytes(download)
