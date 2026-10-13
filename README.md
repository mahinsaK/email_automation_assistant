# AI Email Automation Assistant

An extensible, human-in-the-loop email automation system with Telegram as its
first interface. Phase 2 creates deterministic email drafts, lets the user edit
or regenerate them, and requires explicit approval before a simulated send.

No real email is delivered in this phase.

## Commands

- `/start` — introduction
- `/help` — command list
- `/send` — create and review a general email draft
- `/cancel` — discard the active workflow

Invalid input stays in the current state, explains the problem, and asks again.
Temporary data is stored under a workflow-specific key in Telegram `user_data`
and removed on completion or cancellation.

## Phase 2 approval workflow

```text
/send
  ↓
WAITING_RECIPIENT
  ↓
WAITING_PURPOSE
  ↓
WAITING_CONTEXT
  ↓
GENERATE
  ↓
WAITING_FOR_ACTION
  │
  ├── CONFIRM
  │      ↓
  │    Mock Send
  │      ↓
  │     END
  │
  ├── REGENERATE
  │      ↓
  │   Generate Again
  │      ↓
  │   WAITING_FOR_ACTION
  │
  ├── EDIT
  │      ↓
  │   EDIT_MENU
  │    ├── EDIT_RECIPIENT
  │    ├── EDIT_SUBJECT
  │    ├── EDIT_BODY
  │    ├── EDIT_CONTEXT → Generate Again
  │    └── Back to Preview
  │
  └── CANCEL
         ↓
        END
```

The preview has four inline actions:

- **Confirm & Send** — explicitly approves the current draft and calls the mock
  sender. The response clearly says that delivery was simulated.
- **Edit** — opens structured choices for recipient, subject, message, and
  original request context.
- **Regenerate** — calls the generator again with the stored request data.
- **Cancel** — discards temporary state without calling the sender.

The Phase 2 generator is deterministic, so regeneration with unchanged input can
produce the same draft. That is intentional: this phase establishes the workflow
contract. A later AI strategy may produce variations.

Recipient edits update both the source request and current draft but preserve the
subject and body. Subject and body edits affect only generated content. Context
edits update source data and intentionally regenerate the whole draft. Manual
subject/body changes are therefore retained until the user explicitly requests a
regeneration or context-based regeneration.

## Architecture

```text
Telegram
   ↓
Handler + explicit conversation states
   ↓
GeneralEmailWorkflow
   ├── EmailGenerator protocol
   │      ↓
   │  DeterministicEmailGenerator
   │
   └── EmailSender protocol
          ↓
      MockEmailSender
```

```text
app/
├── bot/
│   ├── handlers/           # Telegram update/callback translation
│   ├── keyboards.py        # Inline keyboards and callback identifiers
│   ├── router.py           # State-machine and dependency composition
│   └── states.py           # Explicit conversation states
├── models/                 # Provider-independent immutable domain values
├── services/               # Generator/sender ports and concrete Phase 2 strategies
├── workflows/              # Telegram-independent application behavior
├── config.py               # Environment configuration
└── logging_config.py       # Safe logging setup
tests/                      # Unit and focused adapter tests
main.py                     # Executable entry point
```

### Engineering decisions

- **Strategy and dependency inversion:** `GeneralEmailWorkflow` depends on the
  `EmailGenerator` and `EmailSender` protocols. A later AI generator or Gmail
  sender can implement these ports without changing approval logic.
- **Dependency injection:** `build_application` is the composition root. It wires
  `DeterministicEmailGenerator` and `MockEmailSender` into the workflow, then
  injects that workflow into Telegram callbacks.
- **State machine:** input, approval, menu, and field-edit behavior use explicit
  enum states instead of combinations of boolean flags.
- **Immutability:** `EmailDraft`, request, and session snapshots are frozen
  dataclasses. Edits use `dataclasses.replace`, so an earlier value cannot be
  changed unexpectedly through a shared reference.
- **Human-in-the-loop:** generation only reaches `EmailSender` from the Confirm
  callback. Preview, edit, regenerate, and cancel never imply approval.
- **Test double:** `MockEmailSender` is most accurately an in-memory **fake**—a
  working but non-production implementation. It can simulate success or failure
  and records requests for verification. “Mock” remains in its class name because
  its development purpose is immediately recognizable.

### Duplicate-send protection

Each approval session receives a unique confirmation ID. The workflow claims the
ID synchronously before awaiting sender I/O, and later confirmation attempts for
that ID are rejected. The draft transitions through:

```text
PREVIEWED → SENDING → SENT
```

A failed send transitions back to `PREVIEWED`, releases the claim, retains the
draft, and permits retry or cancellation. This protection is intentionally
in-memory for Phase 2. Durable idempotency belongs with persistence and a real
delivery provider in a later phase.

Stale or unknown email callback data is answered safely. If workflow state has
already been cleared, the user is told to start again with `/send`.

## Setup and run

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Create a bot with Telegram's BotFather, place its token in `.env`, and optionally
set `ALLOWED_TELEGRAM_USER_ID`. Then run:

```bash
python main.py
```

Open the bot in Telegram, send `/start`, then `/send`. Even after confirmation,
the configured sender only simulates delivery.

## Test

```bash
pytest
```

Tests cover validation, deterministic generation, confirmation, cancellation,
regeneration, every edit type, invalid edited recipients, sender failure and
retry, duplicate confirmation, stale callbacks, and application composition.
They do not contact Telegram, Gmail, or an AI provider.

## Why Gmail is absent

Phase 2 proves the approval lifecycle before external delivery is introduced.
This isolates state-machine, editing, idempotency, and failure-recovery bugs while
all sends are harmless and deterministic. Gmail API and OAuth belong to Phase 5,
after the AI and job-application workflows are stable.

## Current checkpoint

Phase 2 is implemented. OpenAI, Gemini, Claude, Gmail, OAuth, attachments, job
applications, databases, scheduling, and real delivery remain intentionally
absent.
