"""Per-conversation filesystem and Bubblewrap execution backends."""

from __future__ import annotations

import json
import logging
import os
import re
import select
import shutil
import signal
import subprocess
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileUploadResponse,
    LsResult,
    SandboxBackendProtocol,
    WriteResult,
)
from django.core.exceptions import ImproperlyConfigured
from langchain.agents.middleware import AgentMiddleware

from deep_agent_app.utilities.constants import BASE_DIR, SKILLS_ROOT

AGENT_WORKSPACE_ROOT = BASE_DIR / "tmp"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SANDBOX_READY_MARKER = "__DEEP_AGENT_SANDBOX_READY__"
_NETWORK_SETUP_TIMEOUT_SECONDS = 5
_SANDBOX_RESOLV_CONF = b"nameserver 10.0.2.3\noptions timeout:2 attempts:2\n"
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    workspace_id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    user_root: Path
    conversation_root: Path


@dataclass(slots=True)
class _SandboxNetwork:
    process: subprocess.Popen[str]
    exit_fd: int


class _SandboxNetworkError(RuntimeError):
    """Raised when isolated outbound networking cannot be initialized."""


_ACTIVE_SCOPE: ContextVar[WorkspaceScope | None] = ContextVar(
    "deep_agent_workspace_scope",
    default=None,
)


def _safe_segment(value: object, *, name: str) -> str:
    segment = str(value)
    if _SAFE_SEGMENT.fullmatch(segment) is None:
        raise ValueError(
            f"{name} must contain only letters, numbers, hyphens, and underscores"
        )
    return segment


def _private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise ImproperlyConfigured(f"workspace path must not be a symlink: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path.resolve()


class WorkspaceLayout:
    """Resolve trusted host paths for one authenticated agent turn."""

    def __init__(self, root: str | Path = AGENT_WORKSPACE_ROOT):
        self.root = _private_directory(Path(root).expanduser().resolve())

    def paths(self, scope: WorkspaceScope) -> WorkspacePaths:
        workspace_id = _safe_segment(scope.workspace_id, name="workspace_id")
        thread_id = _safe_segment(scope.thread_id, name="thread_id")
        user_root = self.root / workspace_id
        conversation_root = user_root / thread_id
        return WorkspacePaths(
            user_root=user_root,
            conversation_root=conversation_root,
        )

    def ensure_conversation(self, scope: WorkspaceScope) -> WorkspacePaths:
        paths = self.paths(scope)
        _private_directory(paths.user_root)
        _private_directory(paths.conversation_root)
        return paths

    def discard_empty_conversation(self, scope: WorkspaceScope) -> None:
        paths = self.paths(scope)
        try:
            paths.conversation_root.rmdir()
        except OSError:
            return
        try:
            paths.user_root.rmdir()
        except OSError:
            pass

    def delete_conversation(self, workspace_id: object, thread_id: object) -> None:
        scope = WorkspaceScope(
            workspace_id=_safe_segment(workspace_id, name="workspace_id"),
            thread_id=_safe_segment(thread_id, name="thread_id"),
        )
        user_root = self.root / scope.workspace_id
        if user_root.is_symlink():
            raise ImproperlyConfigured("user workspace root must not be a symlink")
        target = user_root / scope.thread_id
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            resolved = target.resolve()
            if resolved.parent != user_root.resolve():
                raise ImproperlyConfigured("conversation workspace escapes its user root")
            shutil.rmtree(resolved)
        try:
            user_root.rmdir()
        except OSError:
            pass


def current_workspace_scope() -> WorkspaceScope:
    scope = _ACTIVE_SCOPE.get()
    if scope is None:
        raise RuntimeError("agent workspace is not bound to an authenticated turn")
    return scope


@contextmanager
def bind_workspace(workspace_id: object, thread_id: object):
    """Bind filesystem calls in this context to one user and conversation."""
    scope = WorkspaceScope(
        workspace_id=_safe_segment(workspace_id, name="workspace_id"),
        thread_id=_safe_segment(thread_id, name="thread_id"),
    )
    token = _ACTIVE_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _ACTIVE_SCOPE.reset(token)


class WorkspaceContextMiddleware(AgentMiddleware):
    """Bind the shared backend to the authenticated context around tool calls."""

    @staticmethod
    def _scope(request) -> tuple[str, str]:
        context = request.runtime.context if request.runtime else None
        if context is None or not context.workspace_id or not context.thread_id:
            raise RuntimeError("agent turn has no authenticated workspace context")
        return context.workspace_id, context.thread_id

    def wrap_tool_call(self, request, handler):
        with bind_workspace(*self._scope(request)):
            return handler(request)

    async def awrap_tool_call(self, request, handler):
        with bind_workspace(*self._scope(request)):
            return await handler(request)


class ScopedFilesystemBackend(FilesystemBackend):
    """Filesystem backend whose root is selected from the active turn."""

    def __init__(
        self,
        workspace_root: str | Path = AGENT_WORKSPACE_ROOT,
        *,
        user_root: bool = False,
    ):
        self.layout = WorkspaceLayout(workspace_root)
        self._use_user_root = user_root
        super().__init__(root_dir=self.layout.root, virtual_mode=True)

    @property
    def cwd(self) -> Path:
        paths = self.layout.paths(current_workspace_scope())
        return paths.user_root if self._use_user_root else paths.conversation_root

    @cwd.setter
    def cwd(self, value: str | Path) -> None:
        # FilesystemBackend assigns cwd during initialization. Runtime access is
        # deliberately resolved from the ContextVar instead of this placeholder.
        self._initial_cwd = Path(value).resolve()

    def _ensure_conversation(self) -> None:
        if not self._use_user_root:
            self.layout.ensure_conversation(current_workspace_scope())

    def ls(self, path: str) -> LsResult:
        # A new conversation has no directory until its first mutation. Treat
        # that missing root as an empty directory so CompositeBackend can still
        # include its virtual routes (for example /skills/ and /conversations/).
        if path == "/" and not self.cwd.exists():
            return LsResult(entries=[])
        return super().ls(path)

    def write(self, file_path: str, content: str) -> WriteResult:
        self._ensure_conversation()
        return super().write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        self._ensure_conversation()
        return super().edit(file_path, old_string, new_string, replace_all)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self._ensure_conversation()
        return super().upload_files(files)


class _ReadOnlyFilesystemMixin:
    """Reject mutations while preserving the backend's read operations."""

    _ERROR = "Permission denied: this filesystem is read-only."

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=self._ERROR)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        return EditResult(error=self._ERROR)

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=self._ERROR)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [
            FileUploadResponse(path=file_path, error=self._ERROR)
            for file_path, _content in files
        ]


class ReadOnlyFilesystemBackend(_ReadOnlyFilesystemMixin, FilesystemBackend):
    """Static read-only filesystem route."""


class ReadOnlyScopedFilesystemBackend(
    _ReadOnlyFilesystemMixin,
    ScopedFilesystemBackend,
):
    """Context-scoped read-only filesystem route."""


class BubblewrapBackend(ScopedFilesystemBackend, SandboxBackendProtocol):
    """Run unrestricted shell syntax inside a minimal Bubblewrap filesystem."""

    def __init__(
        self,
        workspace_root: str | Path = AGENT_WORKSPACE_ROOT,
        *,
        skills_root: str | Path = SKILLS_ROOT,
        bwrap_path: str | Path | None = None,
        network_access: bool = False,
        slirp4netns_path: str | Path | None = None,
        timeout: int = 120,
        max_output_bytes: int = 100_000,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")

        super().__init__(workspace_root)
        self.skills_root = Path(skills_root).resolve()
        if not self.skills_root.is_dir():
            raise ImproperlyConfigured(
                f"skills directory is missing: {self.skills_root}"
            )

        executable = str(bwrap_path) if bwrap_path else shutil.which("bwrap")
        if not executable or not os.access(executable, os.X_OK):
            raise ImproperlyConfigured(
                "Bubblewrap is required for agent execution; install the 'bubblewrap' package"
            )
        self.bwrap_path = str(Path(executable).resolve())
        self.network_access = network_access
        self.slirp4netns_path: str | None = None
        if network_access:
            network_executable = (
                str(slirp4netns_path)
                if slirp4netns_path
                else shutil.which("slirp4netns")
            )
            if not network_executable or not os.access(network_executable, os.X_OK):
                raise ImproperlyConfigured(
                    "slirp4netns is required for isolated agent network access; "
                    "install the 'slirp4netns' package"
                )
            self.slirp4netns_path = str(Path(network_executable).resolve())
        self.default_timeout = timeout
        self.max_output_bytes = max_output_bytes
        self._sandbox_id = f"bwrap-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        return self._sandbox_id

    def _command(
        self,
        command: str,
        *,
        info_fd: int | None = None,
        resolv_fd: int | None = None,
    ) -> list[str]:
        paths = self.layout.paths(current_workspace_scope())
        argv = [
            self.bwrap_path,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--bind",
            str(paths.conversation_root),
            "/workspace",
            "--ro-bind",
            str(paths.user_root),
            "/conversations",
            "--ro-bind",
            str(self.skills_root),
            "/skills",
            "--tmpfs",
            "/tmp",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--dir",
            "/etc",
        ]
        if self.network_access:
            if info_fd is None or resolv_fd is None:
                raise RuntimeError("network file descriptors are required")
            argv.extend(
                [
                    "--info-fd",
                    str(info_fd),
                    "--ro-bind",
                    "/etc/ssl",
                    "/etc/ssl",
                    "--ro-bind-try",
                    "/etc/hosts",
                    "/etc/hosts",
                    "--ro-bind-try",
                    "/etc/nsswitch.conf",
                    "/etc/nsswitch.conf",
                    "--ro-bind-data",
                    str(resolv_fd),
                    "/etc/resolv.conf",
                ]
            )
        argv.extend(
            [
                "--chdir",
                "/workspace",
                "--clearenv",
                "--setenv",
                "PATH",
                "/workspace/.venv/bin:/usr/bin:/bin",
                "--setenv",
                "HOME",
                "/workspace",
                "--setenv",
                "TMPDIR",
                "/tmp",
                "--setenv",
                "LANG",
                "C.UTF-8",
                "--setenv",
                "GIT_TERMINAL_PROMPT",
                "0",
                "--setenv",
                "PIP_NO_INPUT",
                "1",
                "--setenv",
                "PIP_DISABLE_PIP_VERSION_CHECK",
                "1",
                "/bin/sh",
                "-lc",
                self._sandbox_shell(),
                "deep-agent",
                command,
            ]
        )
        return argv

    def _sandbox_shell(self) -> str:
        wait_for_network = ""
        if self.network_access:
            wait_for_network = (
                "attempt=0; "
                "until grep -q '^tap0' /proc/net/route; do "
                "attempt=$((attempt + 1)); "
                "if [ \"$attempt\" -ge 200 ]; then "
                "echo 'Sandbox network setup timed out.' >&2; exit 125; "
                "fi; "
                "sleep 0.01; "
                "done; "
            )
        return (
            f"{wait_for_network}"
            f"printf '{_SANDBOX_READY_MARKER}\\n' >&2; "
            'exec /bin/sh -lc "$1"'
        )

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _network_fds() -> tuple[int, int, int]:
        info_read, info_write = os.pipe()
        try:
            resolv_fd = os.memfd_create("deep-agent-resolv")
            os.write(resolv_fd, _SANDBOX_RESOLV_CONF)
            os.lseek(resolv_fd, 0, os.SEEK_SET)
        except OSError:
            os.close(info_read)
            os.close(info_write)
            raise
        return info_read, info_write, resolv_fd

    @staticmethod
    def _sandbox_child_pid(info_fd: int) -> int:
        ready, _writable, _errors = select.select(
            [info_fd],
            [],
            [],
            _NETWORK_SETUP_TIMEOUT_SECONDS,
        )
        if not ready:
            raise _SandboxNetworkError("Bubblewrap did not report its child process")
        payload = os.read(info_fd, 65_536)
        if not payload:
            raise _SandboxNetworkError("Bubblewrap exited before network setup")
        try:
            child_pid = json.loads(payload)["child-pid"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise _SandboxNetworkError("Bubblewrap returned invalid process data") from exc
        if not isinstance(child_pid, int) or child_pid <= 0:
            raise _SandboxNetworkError("Bubblewrap returned an invalid child process")
        return child_pid

    def _start_network(self, child_pid: int) -> _SandboxNetwork:
        if self.slirp4netns_path is None:
            raise _SandboxNetworkError("slirp4netns is not configured")

        ready_read, ready_write = os.pipe()
        exit_read, exit_write = os.pipe()
        try:
            process = subprocess.Popen(  # noqa: S603
                [
                    self.slirp4netns_path,
                    "--configure",
                    "--mtu=65520",
                    "--disable-host-loopback",
                    "--enable-seccomp",
                    "--ready-fd",
                    str(ready_write),
                    "--exit-fd",
                    str(exit_read),
                    str(child_pid),
                    "tap0",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={},
                pass_fds=(ready_write, exit_read),
                start_new_session=True,
            )
        except OSError as exc:
            os.close(ready_read)
            os.close(exit_write)
            raise _SandboxNetworkError("Could not start slirp4netns") from exc
        finally:
            os.close(ready_write)
            os.close(exit_read)

        try:
            try:
                ready, _writable, _errors = select.select(
                    [ready_read],
                    [],
                    [],
                    _NETWORK_SETUP_TIMEOUT_SECONDS,
                )
                status = os.read(ready_read, 1) if ready else b""
            except OSError as exc:
                self._kill_process_group(process)
                process.communicate()
                os.close(exit_write)
                raise _SandboxNetworkError(
                    "Could not read slirp4netns startup status"
                ) from exc
        finally:
            os.close(ready_read)

        if status != b"1":
            self._kill_process_group(process)
            stdout, stderr = process.communicate()
            os.close(exit_write)
            detail = stderr.strip() or stdout.strip() or "no detail"
            raise _SandboxNetworkError(f"slirp4netns setup failed: {detail}")
        return _SandboxNetwork(process=process, exit_fd=exit_write)

    def _stop_network(self, network: _SandboxNetwork) -> None:
        os.close(network.exit_fd)
        try:
            stdout, stderr = network.process.communicate(
                timeout=_NETWORK_SETUP_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            self._kill_process_group(network.process)
            stdout, stderr = network.process.communicate()
        if network.process.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "no detail"
            log.error("slirp4netns stopped unexpectedly: %s", detail)

    def _network_unavailable(
        self,
        detail: str,
        scope: WorkspaceScope,
        *,
        workspace_existed: bool,
    ) -> ExecuteResponse:
        log.error("Sandbox network setup failed: %s", detail)
        if not workspace_existed:
            self.layout.discard_empty_conversation(scope)
        return ExecuteResponse(
            output="Sandbox network unavailable. The command was not run.",
            exit_code=1,
        )

    @staticmethod
    def _strip_ready_marker(stderr: str) -> tuple[bool, str]:
        marker = f"{_SANDBOX_READY_MARKER}\n"
        if marker not in stderr:
            return False, stderr
        return True, stderr.replace(marker, "", 1)

    def _sandbox_unavailable(
        self,
        stderr: str,
        scope: WorkspaceScope,
        *,
        workspace_existed: bool,
    ) -> ExecuteResponse:
        log.error("Bubblewrap sandbox setup failed: %s", stderr.strip() or "no detail")
        if not workspace_existed:
            self.layout.discard_empty_conversation(scope)
        if "RTM_NEWADDR" in stderr:
            message = (
                "Sandbox unavailable because the host blocked its isolated network "
                "namespace. The command was not run."
            )
        else:
            message = "Sandbox unavailable. The command was not run."
        return ExecuteResponse(output=message, exit_code=1)

    def _response(self, stdout: str, stderr: str, exit_code: int) -> ExecuteResponse:
        parts = [stdout] if stdout else []
        if stderr:
            parts.extend(f"[stderr] {line}" for line in stderr.rstrip().splitlines())
        output = "\n".join(parts) if parts else "<no output>"
        truncated = len(output) > self.max_output_bytes
        if truncated:
            output = (
                output[: self.max_output_bytes]
                + f"\n\n... Output truncated at {self.max_output_bytes} bytes."
            )
        if exit_code != 0:
            output = f"{output.rstrip()}\n\nExit code: {exit_code}"
        return ExecuteResponse(
            output=output,
            exit_code=exit_code,
            truncated=truncated,
        )

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        if not isinstance(command, str) or not command.strip():
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
            )

        effective_timeout = self.default_timeout if timeout is None else timeout
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")

        scope = current_workspace_scope()
        paths = self.layout.paths(scope)
        workspace_existed = paths.conversation_root.exists()
        self.layout.ensure_conversation(scope)

        info_read: int | None = None
        info_write: int | None = None
        resolv_fd: int | None = None
        pass_fds: tuple[int, ...] = ()
        if self.network_access:
            try:
                info_read, info_write, resolv_fd = self._network_fds()
            except OSError:
                log.exception("Could not create sandbox network descriptors")
                return self._network_unavailable(
                    "Could not create network descriptors",
                    scope,
                    workspace_existed=workspace_existed,
                )
            pass_fds = (info_write, resolv_fd)

        try:
            process = subprocess.Popen(  # noqa: S603
                self._command(
                    command,
                    info_fd=info_write,
                    resolv_fd=resolv_fd,
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={},
                pass_fds=pass_fds,
                start_new_session=True,
            )
        except OSError:
            log.exception("Could not start Bubblewrap sandbox")
            if info_read is not None:
                os.close(info_read)
            if not workspace_existed:
                self.layout.discard_empty_conversation(scope)
            return ExecuteResponse(
                output="Sandbox unavailable. The command was not run.",
                exit_code=1,
            )
        finally:
            if info_write is not None:
                os.close(info_write)
            if resolv_fd is not None:
                os.close(resolv_fd)

        network: _SandboxNetwork | None = None
        if info_read is not None:
            try:
                child_pid = self._sandbox_child_pid(info_read)
            except (OSError, _SandboxNetworkError) as exc:
                self._kill_process_group(process)
                stdout, stderr = process.communicate()
                return self._sandbox_unavailable(
                    stderr or str(exc),
                    scope,
                    workspace_existed=workspace_existed,
                )
            finally:
                os.close(info_read)

            try:
                network = self._start_network(child_pid)
            except _SandboxNetworkError as exc:
                self._kill_process_group(process)
                process.communicate()
                return self._network_unavailable(
                    str(exc),
                    scope,
                    workspace_existed=workspace_existed,
                )

        try:
            stdout, stderr = process.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            process.communicate()
            return ExecuteResponse(
                output=f"Error: Command timed out after {effective_timeout} seconds.",
                exit_code=124,
            )
        finally:
            if network is not None:
                self._stop_network(network)

        sandbox_started, stderr = self._strip_ready_marker(stderr)
        if not sandbox_started:
            return self._sandbox_unavailable(
                stderr,
                scope,
                workspace_existed=workspace_existed,
            )
        return self._response(stdout, stderr, process.returncode)


def delete_conversation_workspace(workspace_id: object, thread_id: object) -> None:
    WorkspaceLayout().delete_conversation(workspace_id, thread_id)


def migrate_legacy_user_workspace(
    legacy_user_id: object,
    workspace_id: object,
    *,
    workspace_root: str | Path | None = None,
) -> None:
    """Move the pre-UUID user directory without overwriting newer data."""
    layout = WorkspaceLayout(workspace_root or AGENT_WORKSPACE_ROOT)
    legacy_name = _safe_segment(legacy_user_id, name="legacy_user_id")
    workspace_name = _safe_segment(workspace_id, name="workspace_id")
    legacy_root = layout.root / legacy_name
    destination_root = layout.root / workspace_name
    if not legacy_root.exists() or legacy_root == destination_root:
        return
    if legacy_root.is_symlink() or destination_root.is_symlink():
        raise ImproperlyConfigured("workspace path must not be a symlink")
    if destination_root.exists():
        log.error(
            "Cannot migrate legacy workspace %s because %s already exists",
            legacy_root,
            destination_root,
        )
        return
    try:
        legacy_root.rename(destination_root)
    except FileNotFoundError:
        # Another request completed the same atomic rename first.
        return
    destination_root.chmod(0o700)


__all__ = [
    "AGENT_WORKSPACE_ROOT",
    "BubblewrapBackend",
    "ReadOnlyFilesystemBackend",
    "ReadOnlyScopedFilesystemBackend",
    "ScopedFilesystemBackend",
    "WorkspaceContextMiddleware",
    "bind_workspace",
    "current_workspace_scope",
    "delete_conversation_workspace",
    "migrate_legacy_user_workspace",
]
