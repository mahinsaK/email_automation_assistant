# AI Email Automation Assistant

An extensible, human-in-the-loop email automation system with Telegram as its
first interface. Phase 3 optionally creates validated AI-backed email drafts,
lets the user edit or regenerate them, and requires explicit approval before a
simulated send. Without an AI key it remains fully usable offline with the
deterministic generator.

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
WAITING_TONE
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

With AI enabled, regeneration calls the provider again with the stored recipient,
purpose, context, and tone, so the result may differ. Offline regeneration uses
the deterministic fallback and may produce the same draft. Approval semantics are
identical in both modes.

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
   ├── EmailGenerator protocol (strategy)
   │      ├── DeterministicEmailGenerator
   │      └── AIEmailGenerator
   │              ↓
   │          LLMProvider protocol
   │              ↓
   │          OpenAIProvider
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
├── prompts/                # Provider-independent prompt construction
├── services/
│   ├── ai/                 # LLM port, Pydantic boundary, OpenAI adapter
│   └── ...                 # Generator/sender ports and concrete strategies
├── workflows/              # Telegram-independent application behavior
├── config.py               # Environment configuration
└── logging_config.py       # Safe logging setup
tests/                      # Unit and focused adapter tests
main.py                     # Executable entry point
```

### Engineering decisions

- **Strategy and dependency inversion:** `GeneralEmailWorkflow` still depends on
  `EmailGenerator` and `EmailSender`, never OpenAI. AI and deterministic
  generators are interchangeable strategies.
- **Dependency injection:** `build_application` is the composition root. It wires
  the configured generator and `MockEmailSender` into the workflow, then injects
  that workflow into Telegram callbacks.
- **Adapter pattern:** `OpenAIProvider` translates the external asynchronous
  Responses API into the internal `LLMProvider` interface.
- **Boundary validation:** untrusted provider output must pass the strict
  `AIEmailOutput` Pydantic model before it can become an `EmailDraft`.
- **Structured output:** subject and body arrive as a schema-constrained object,
  avoiding fragile attempts to split arbitrary prose. The application validates
  the result again because other provider adapters may not enforce schemas.
- **Fallback strategy:** expected provider and response-validation failures use
  deterministic generation. Unexpected programming errors propagate instead of
  being silently hidden.
- **Prompt separation:** stable system rules prohibit invented facts and treat a
  JSON-encoded request as untrusted data. User context cannot become application
  or system instructions merely by appearing in the prompt.
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

## Phase 3 AI generation

The provider boundary accepts separate system and user prompts plus a Pydantic
response model. `OpenAIProvider` uses the asynchronous Responses API and
Structured Outputs. This follows the official OpenAI guidance to use schema-based
Structured Outputs rather than plain JSON mode when the model supports it:

- [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [OpenAI Python SDK](https://developers.openai.com/api/reference/python)

`AIEmailGenerator` builds the prompt, calls `LLMProvider`, validates the returned
JSON, and creates the provider-independent `EmailDraft`. It falls back only for:

- provider authentication, rate-limit, timeout, connection, or API failures
- missing, empty, malformed, oversized, or otherwise invalid structured output

No prompt, API key, access token, or complete email context is written to logs.
The provider timeout defaults to 30 seconds and the SDK performs at most one
automatic retry.

## Setup and run

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Create a bot with Telegram's BotFather, place its token in `.env`, and optionally
set `ALLOWED_TELEGRAM_USER_ID`.

AI configuration is optional:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=
AI_MODEL=gpt-4o-mini
AI_TIMEOUT_SECONDS=30
```

- With an OpenAI key, the composition root injects `AIEmailGenerator`.
- Without a key, it injects `DeterministicEmailGenerator`.
- Set `AI_PROVIDER=deterministic` to force offline mode even when a key exists.

Then run:

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
retry, duplicate confirmation, stale callbacks, tone selection, valid and invalid
AI output, provider failure, fallback, optional configuration, prompt contents,
and complete fake-provider composition. They do not contact Telegram, Gmail, or
an AI provider.

## Why Gmail is absent

Phase 3 preserves the proven approval lifecycle while adding generation only.
This isolates state-machine, editing, idempotency, and failure-recovery bugs while
all sends are harmless and deterministic. Gmail API and OAuth belong to Phase 5,
after the AI and job-application workflows are stable.

## Current checkpoint

Phase 3 is implemented with an optional OpenAI generation adapter. Gemini, Claude,
Gmail, OAuth, attachments, job applications, databases, scheduling, and real
delivery remain intentionally absent. `MockEmailSender` is still the only sender.
