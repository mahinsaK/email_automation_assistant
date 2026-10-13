# AI Email Automation Assistant

Phase 1 of an extensible, human-in-the-loop email automation system. Telegram is
the first interface, but the core workflow has no dependency on Telegram. This
version creates a deterministic email draft and previews it; it never sends mail.

## Phase 1 behavior

Commands:

- `/start` — introduction
- `/help` — command list
- `/send` — collect recipient, purpose, and context, then show a preview
- `/cancel` — stop the current workflow and clear temporary data

The `/send` state machine is:

```text
/send
  -> WAITING_RECIPIENT
  -> WAITING_PURPOSE
  -> WAITING_CONTEXT
  -> generate draft
  -> preview
  -> END
```

Invalid input stays in the current state, explains the problem, and asks again.
The Telegram `user_data` dictionary stores temporary conversation input under a
workflow-specific key, which is removed on completion or cancellation. This
avoids erasing future user preferences or another workflow's data.

## Structure

```text
app/
├── bot/                    # Telegram adapter, routing, handlers, and states
├── models/                 # Provider-independent domain objects
├── services/               # Interfaces, validation, and implementations
├── workflows/              # Application use cases (no Telegram imports)
├── config.py               # Environment configuration
└── logging_config.py       # Safe logging setup
tests/                      # Unit tests for core behavior
main.py                     # Composition root / executable entry point
```

`GeneralEmailWorkflow` coordinates the use case. It receives an
`EmailGenerator` protocol through its constructor. Phase 1 injects
`DeterministicEmailGenerator`; Phase 3 can inject an AI-backed implementation
without changing the workflow or Telegram handlers.

## Setup and run

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Create a bot with Telegram's BotFather, put its token in `.env`, and optionally
set `ALLOWED_TELEGRAM_USER_ID`. Then run:

```bash
python main.py
```

Open the bot in Telegram, send `/start`, then `/send`. Stop the process with
Ctrl+C.

## Test

```bash
pytest
```

The tests do not contact Telegram, Gmail, or an AI provider.

## Engineering decisions

- **Separation of concerns:** Telegram code translates chat updates into a
  `GeneralEmailRequest`; the workflow owns the use case; services validate and
  generate; the model represents the result.
- **Dependency inversion:** the workflow depends on the `EmailGenerator`
  protocol, not the deterministic class. This is the smallest useful interface
  for replacing it with an OpenAI, Gemini, Claude, or local implementation.
- **Dependency injection:** `build_application` constructs the generator and
  passes it to the workflow, then injects the workflow into the handlers. This
  makes the core replaceable and easy to test.
- **Single responsibility:** each module has one reason to change: Telegram UI,
  validation rules, generation policy, workflow orchestration, or domain data.
- **Open/closed principle:** new generator implementations can be added without
  modifying `GeneralEmailWorkflow`.
- **Dataclasses:** `EmailDraft` and `GeneralEmailRequest` are simple data-focused
  domain objects, so frozen, slotted dataclasses add clarity and immutability
  without introducing a validation framework. Boundary validation remains in a
  reusable service. Pydantic becomes more valuable later for untrusted structured
  AI responses and API payloads.
- **State machine:** explicit enum states prevent a large handler full of nested
  conditions and make each transition visible in the router.

No repository is added in Phase 1 because there is nothing persistent yet. A
repository abstraction should appear with actual history storage in Phase 6;
adding it now would be unused ceremony.

## Current checkpoint

Implemented only Phase 1. Gmail, OAuth, real sending, AI APIs, attachments,
approval buttons, editing, and persistence are intentionally absent. Phase 2 can
extend the preview with Confirm, Edit, Regenerate, and Cancel while using a mock
sender so the human-in-the-loop rule is developed and tested before Gmail exists.
