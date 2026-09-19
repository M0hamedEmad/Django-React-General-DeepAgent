"""Trusted slash-command and @-mention catalogs for the composer and agent.

Skills come from validated ``SKILL.md`` files and subagents come from their
real Python definitions. Tools intentionally come from ``mentions.json`` so
the product controls which runtime tools are exposed in the composer. A JSON
entry may override agent/skill presentation or hide any mention with
``"exclude": true``. Descriptions also become trusted per-turn instructions.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
import json
import re

from django.core.exceptions import ImproperlyConfigured

from deep_agent_app.agent.skills import discover_skills

from .constants import CONFIG_DIR

CONFIG = CONFIG_DIR
MENTION_KINDS = ("skill", "agent", "tool")
SLASH_COMMAND_RE = re.compile(r"^/([\w-]+)(?:\s|$)")
MENTION_ID_RE = re.compile(r"^[\w-]+(?:/[\w-]+)*$")


@lru_cache(maxsize=1)
def commands():
    """Return configured fast prompts shown for ``/``."""
    data = read_json(CONFIG / "commands.json")
    if not isinstance(data, list):
        raise ImproperlyConfigured("commands.json must contain a JSON array")
    return data


def resolve_command(value=None, text=""):
    """Resolve one trusted slash command from an id or leading ``/id``."""
    explicit = value not in (None, "")
    if explicit:
        if not isinstance(value, str):
            raise ValueError("command must be a string")
        command_id = value
    else:
        match = SLASH_COMMAND_RE.match(text) if isinstance(text, str) else None
        if match is None:
            return None
        command_id = match.group(1)

    command = next((item for item in commands() if item.get("id") == command_id), None)
    if command is None and explicit:
        raise ValueError("unknown command")
    return command


def _label(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ").strip().title()


@lru_cache(maxsize=1)
def _configured_mentions():
    data = read_json(CONFIG / "mentions.json")
    if not isinstance(data, list):
        raise ImproperlyConfigured("mentions.json must contain a JSON array")

    configured = []
    seen = set()
    for index, item in enumerate(data, 1):
        if not isinstance(item, Mapping):
            raise ImproperlyConfigured(f"mentions.json item {index} must be an object")
        kind = item.get("kind")
        identifier = item.get("id")
        if kind not in MENTION_KINDS:
            raise ImproperlyConfigured(
                f"mentions.json item {index} has an invalid kind"
            )
        if not isinstance(identifier, str) or not MENTION_ID_RE.fullmatch(identifier):
            raise ImproperlyConfigured(f"mentions.json item {index} has an invalid id")
        key = (kind, identifier)
        if key in seen:
            raise ImproperlyConfigured(f"duplicate mention {kind}:{identifier}")
        seen.add(key)
        configured.append(dict(item))
    return tuple(configured)


def _instruction(item) -> str:
    identifier = item["id"]
    description = item["description"]
    purpose = f" Its purpose is: {description}" if description else ""
    if item["kind"] == "skill" and item.get("path"):
        return (
            f"The user explicitly selected the `{identifier}` skill.{purpose} "
            f"Read `{item['path']}` and follow it for this turn."
        )
    if item["kind"] == "agent":
        target = item.get("target", identifier)
        return (
            f"The user explicitly selected the `{identifier}` agent.{purpose} "
            f"Delegate the relevant work to `{target}`."
        )
    return (
        f"The user explicitly selected the `{identifier}` tool.{purpose} "
        "Use it for the relevant part of this turn."
    )


@lru_cache(maxsize=1)
def _mention_catalog():
    from deep_agent_app.agent.subagent import composer_subagents

    catalog = {}
    for skill in discover_skills():
        skill = dict(skill)
        skill["agents"] = [
            "connected" if skill.get("requires_connection") else "general"
        ]
        catalog[("skill", skill["id"])] = skill

    for subagent in composer_subagents():
        identifier = subagent["id"]
        catalog[("agent", identifier)] = {**subagent, "kind": "agent"}

    # Tools are added only here. Agent and skill entries act as presentation
    # overrides for the automatically discovered records above.
    for configured in _configured_mentions():
        key = (configured["kind"], configured["id"])
        if configured.get("exclude") is True:
            catalog.pop(key, None)
            continue
        current = catalog.get(key, {"kind": key[0], "id": key[1]})
        current.update(
            {field: value for field, value in configured.items() if field != "exclude"}
        )
        catalog[key] = current

    agent_labels = {"general": "General agent"}
    agent_labels.update(
        {
            item["id"]: item.get("label") or _label(item["id"])
            for item in catalog.values()
            if item["kind"] == "agent"
        }
    )

    normalized = []
    for item in catalog.values():
        kind = item["kind"]
        agents = item.pop("agents", [])
        if not isinstance(agents, Sequence) or isinstance(agents, (str, bytes)):
            raise ImproperlyConfigured(
                f"agents for mention {kind}:{item['id']} must be an array"
            )
        if any(not isinstance(owner, str) or not owner for owner in agents):
            raise ImproperlyConfigured(
                f"agents for mention {kind}:{item['id']} must contain ids"
            )
        owners = [
            {"id": owner, "label": agent_labels.get(owner, _label(owner))}
            for owner in dict.fromkeys(agents)
        ]
        if owners:
            item["owners"] = owners

        label = item.get("label")
        description = item.get("description")
        if label is not None and not isinstance(label, str):
            raise ImproperlyConfigured(
                f"label for mention {kind}:{item['id']} must be a string"
            )
        if description is not None and not isinstance(description, str):
            raise ImproperlyConfigured(
                f"description for mention {kind}:{item['id']} must be a string"
            )
        item["label"] = label or _label(item["id"])
        item["description"] = description or ""
        item["prompt"] = _instruction(item)
        normalized.append(item)

    order = {kind: index for index, kind in enumerate(MENTION_KINDS)}
    return tuple(sorted(normalized, key=lambda item: (order[item["kind"]], item["id"])))


def mentions():
    """Return safe composer metadata with owning-agent details."""
    return [
        {
            **item,
            **(
                {"owners": [dict(owner) for owner in item["owners"]]}
                if "owners" in item
                else {}
            ),
        }
        for item in _mention_catalog()
    ]


def mention_prompts(selected_mentions) -> list[str]:
    """Resolve browser mention references to trusted description-based prompts."""
    by_key = {(item["kind"], item["id"]): item for item in _mention_catalog()}
    return [
        item["prompt"]
        for mention in dict.fromkeys(selected_mentions)
        if (item := by_key.get(tuple(mention))) is not None
    ]


def skills():
    """Return validated metadata from the same sources used by Deep Agents."""
    return discover_skills()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ImproperlyConfigured(f"{path} is missing") from None
    except ValueError as exc:
        raise ImproperlyConfigured(f"{path} is not valid JSON: {exc}") from exc
