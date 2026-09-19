"""Validated skill catalog and backend mounting for the Deep Agent."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re

import yaml
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.local_shell import LocalShellBackend
from django.core.exceptions import ImproperlyConfigured

from deep_agent_app.agent.backend import (
    AGENT_WORKSPACE_ROOT,
    BubblewrapBackend,
    ReadOnlyFilesystemBackend,
    ReadOnlyScopedFilesystemBackend,
)
from deep_agent_app.utilities.constants import DEEP_AGENT, SKILLS_ROOT

SkillSource = tuple[str, str]

# Deep Agents scans the direct children of every source. These are the small,
# trusted, repository-bundled skills available to the agent.
GENERAL_SKILL_SOURCES: tuple[SkillSource, ...] = (("/skills/general", "Company"),)
CONNECTED_SKILL_SOURCES: tuple[SkillSource, ...] = ()
MAIN_SKILL_SOURCES: tuple[SkillSource, ...] = (
    GENERAL_SKILL_SOURCES + CONNECTED_SKILL_SOURCES
)

MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
MAIN_SKILL_TOOL_NAMES = frozenset(
    {
        "ask_user",
        "present_ui",
        "present_report",
        "internet_search",
        "fetch_webpage_content",
    }
)


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    virtual_path: str
    requires_connection: bool
    required_tools: tuple[str, ...]

    def as_mention(self):
        return {
            "kind": "skill",
            "id": self.name,
            "label": self.name,
            "description": self.description,
            "path": self.virtual_path,
            "requires_connection": self.requires_connection,
        }


def main_skill_sources() -> tuple[SkillSource, ...]:
    return MAIN_SKILL_SOURCES


def connected_skill_sources() -> tuple[SkillSource, ...]:
    return CONNECTED_SKILL_SOURCES


def build_agent_backend() -> CompositeBackend:
    """Mount the current workspace, shared skills, and same-user workspaces."""
    sandbox = DEEP_AGENT.get("sandbox", "bubblewrap")
    if sandbox == "local_shell":
        default_backend = LocalShellBackend(
            root_dir=AGENT_WORKSPACE_ROOT,
            inherit_env=True,
        )
    elif sandbox == "bubblewrap":
        default_backend = BubblewrapBackend(
            workspace_root=AGENT_WORKSPACE_ROOT,
            skills_root=SKILLS_ROOT,
            network_access=True,
        )
    else:
        raise ImproperlyConfigured(
            "deep_agent.sandbox must be 'bubblewrap' or 'local_shell'"
        )

    return CompositeBackend(
        default=default_backend,
        routes={
            "/skills/": ReadOnlyFilesystemBackend(
                root_dir=SKILLS_ROOT,
                virtual_mode=True,
            ),
            "/conversations/": ReadOnlyScopedFilesystemBackend(
                AGENT_WORKSPACE_ROOT,
                user_root=True,
            ),
        },
    )


def _validated_source_root(
    skills_root: Path,
    virtual_root: str,
) -> Path:
    virtual_path = PurePosixPath(virtual_root)
    if (
        not virtual_root.startswith("/skills/")
        or ".." in virtual_path.parts
        or "~" in virtual_path.parts
    ):
        raise ImproperlyConfigured(f"invalid skill source path: {virtual_root}")

    relative_parts = virtual_path.parts[2:]
    root = skills_root.resolve()
    source_root = root.joinpath(*relative_parts).resolve()
    if not source_root.is_relative_to(root):
        raise ImproperlyConfigured(
            f"skill source escapes the configured root: {virtual_root}"
        )
    if not source_root.is_dir():
        raise ImproperlyConfigured(f"skill source directory is missing: {source_root}")
    return source_root


def _valid_skill_name(name: str) -> bool:
    if (
        not name
        or len(name) > MAX_SKILL_NAME_LENGTH
        or name.startswith("-")
        or name.endswith("-")
        or "--" in name
    ):
        return False
    return all(
        character == "-"
        or character.isdigit()
        or (character.isalpha() and character.islower())
        for character in name
    )


def _front_matter(path: Path) -> tuple[str, str, tuple[str, ...]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ImproperlyConfigured(
            f"cannot read skill metadata in {path}: {exc}"
        ) from exc

    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if match is None:
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: expected YAML between --- delimiters"
        )
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ImproperlyConfigured(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(metadata, Mapping):
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: front matter must be an object"
        )

    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not _valid_skill_name(name.strip()):
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: name must be a lowercase "
            "alphanumeric identifier with single hyphens"
        )
    if not isinstance(description, str) or not description.strip():
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: description must be a non-empty string"
        )
    name = name.strip()
    description = description.strip()
    if name != path.parent.name:
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: name '{name}' must match "
            f"directory '{path.parent.name}'"
        )
    if len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: description exceeds "
            f"{MAX_SKILL_DESCRIPTION_LENGTH} characters"
        )
    required_tools = metadata.get("required-tools", [])
    if not isinstance(required_tools, list) or not all(
        isinstance(tool, str) for tool in required_tools
    ):
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: required-tools must be a list of tool names"
        )
    unknown_tools = set(required_tools) - MAIN_SKILL_TOOL_NAMES
    if unknown_tools:
        raise ImproperlyConfigured(
            f"invalid skill metadata in {path}: unavailable tool "
            f"{sorted(unknown_tools)[0]!r}"
        )
    return name, description, tuple(dict.fromkeys(required_tools))


@lru_cache(maxsize=8)
def _load_skill_catalog(
    skills_root: Path,
    sources: tuple[SkillSource, ...],
) -> tuple[SkillMetadata, ...]:
    by_name: dict[str, SkillMetadata] = {}
    seen_sources: set[str] = set()
    connected_roots = {path.rstrip("/") for path, _label in CONNECTED_SKILL_SOURCES}
    resolved_skills_root = skills_root.resolve()

    for virtual_root, _label in sources:
        virtual_root = virtual_root.rstrip("/")
        if virtual_root in seen_sources:
            raise ImproperlyConfigured(f"duplicate skill source path: {virtual_root}")
        seen_sources.add(virtual_root)
        source_root = _validated_source_root(skills_root, virtual_root)

        root_skill = source_root / "SKILL.md"
        if root_skill.exists():
            expected = source_root / "<skill-name>" / "SKILL.md"
            raise ImproperlyConfigured(
                f"misplaced skill file {root_skill}: put it in {expected}"
            )

        for directory in sorted(
            path for path in source_root.iterdir() if path.is_dir()
        ):
            resolved_directory = directory.resolve()
            if not resolved_directory.is_relative_to(resolved_skills_root):
                raise ImproperlyConfigured(
                    f"skill directory escapes the configured root: {directory}"
                )
            skill_file = directory / "SKILL.md"
            if not skill_file.is_file():
                raise ImproperlyConfigured(
                    f"skill directory has no SKILL.md: {directory}"
                )
            name, description, required_tools = _front_matter(skill_file)
            virtual_path = f"{virtual_root}/{directory.name}/SKILL.md"
            if name in by_name:
                raise ImproperlyConfigured(
                    f"duplicate skill name '{name}': {virtual_path} conflicts with "
                    f"{by_name[name].virtual_path}"
                )
            by_name[name] = SkillMetadata(
                name=name,
                description=description,
                virtual_path=virtual_path,
                requires_connection=virtual_root in connected_roots,
                required_tools=required_tools,
            )

    return tuple(sorted(by_name.values(), key=lambda item: item.name))


def skill_catalog(
    sources: Iterable[SkillSource] = MAIN_SKILL_SOURCES,
) -> tuple[SkillMetadata, ...]:
    """Return the validated process-cached catalog for these sources."""
    return _load_skill_catalog(SKILLS_ROOT, tuple(sources))


def resolve_skill(name: str) -> SkillMetadata | None:
    return next((skill for skill in skill_catalog() if skill.name == name), None)


def discover_skills():
    return [skill.as_mention() for skill in skill_catalog()]
