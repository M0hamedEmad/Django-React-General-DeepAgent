# Django Deep Agent

This is my full-stack conversational agent built with Django, React,
LangGraph, and Deep Agents. My main focus is the agent implementation and the
Django backend that runs it safely for multiple authenticated users.

## Demo

### Chat and generative UI

[![Chat and generative UI preview](media/chat-preview.webp)](media/chat-generative-ui.mp4)

### Research report workspace

![Research report workspace demo](media/report-workspace-demo.gif)

## Agent implementation

- `deep_agent_app/agent/prompts.py` contains the main and subagent instructions.
- `deep_agent_app/agent/subagent.py` defines delegated agents.
- `agent_skills/` contains reusable skills loaded with progressive disclosure.
- `deep_agent_app/agent/tools/` contains search, reports, UI, and human-input tools.
- `deep_agent_app/agent/integrations/` manages persistent MCP connections.

`present_ui` and `present_report` render typed tables, KPIs, charts, status
blocks, and reports. `ask_user` pauses LangGraph to collect several answers.

Filesystem permissions protect skill files from agent writes, while tool
approval interrupts can stop sensitive actions for human confirmation.

## Architecture

```text
React UI
   ↓ HTTP + SSE
Django views.py
   ↓ validation, authentication, thread ownership
chat/chat.py
   ↓ stream orchestration
agent/agent.py
   ↓ prompts, models, subagents, skills, tools and MCP
LangGraph
```

## Quick start

Requirements:

- Python 3.12+

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp deep_agent_app/config/secrets.example.json \
   deep_agent_app/config/secrets.json
```

Edit the private secrets file and replace at least the selected provider API
key. Remove provider entries you do not intend to offer.

Create the database, then create the username and password used to sign in:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/chat/.

The custom `runserver` command launches Uvicorn because the shared async
runtime requires ASGI. The compiled React frontend is included in the
repository, so Node.js is not required to run the application.

## Configuration

Models and optional MCP integrations are configured in the private
`deep_agent_app/config/secrets.json` file. It is ignored by Git; only the
example file is committed.

Skills live under `agent_skills/general/`. Slash commands and mentions are
configured in `deep_agent_app/config/commands.json` and `mentions.json`.
Production environment variables are documented in [`.env.example`](.env.example).

When changing the React frontend, use Node.js 22+ and rebuild the committed
static files:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

## Tests

```bash
python manage.py check
python manage.py test
```

GitHub Actions also checks Python formatting, migrations, TypeScript, and the
frontend production build.

## Production and scaling

Before deploying on Ubuntu, configure and verify the command sandbox using
[the Bubblewrap deployment guide](docs/ubuntu-bubblewrap-sandbox.md).

```bash
DJANGO_SETTINGS_MODULE=config.settings.production \
python -m uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 1
```

The included SQLite checkpointer and process-local thread reservations use one
ASGI worker. PostgreSQL checkpoints and shared leases are required before
running multiple workers.
