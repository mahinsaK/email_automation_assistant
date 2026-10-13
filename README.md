# AI Email Automation Assistant

An extensible, human-in-the-loop email automation system with Telegram as its
first interface. Phase 3.5 lets the user either enter an email manually or use a
configured AI provider. Both paths create the same immutable `EmailDraft`, then
reuse the same preview, editing, approval, cancellation, and simulated-send
lifecycle.

No real email is delivered in this phase.

## Commands

- `/start` — introduction
- `/help` — command list
- `/send` — create and review a general email draft
- `/cancel` — discard the active workflow

Invalid input stays in the current state, explains the problem, and asks again.
Temporary data is stored under a workflow-specific key in Telegram `user_data`
and removed on completion or cancellation.

## Draft creation modes

After a valid recipient is entered, the user explicitly chooses a creation
strategy:

- **Manual mode** asks for a subject and body, validates both, and proceeds
  directly to preview. It never invokes an AI or deterministic generator and
  works without an API key.
- **AI mode** is offered as a real capability only when an AI provider is
  configured. It collects purpose, context, and tone before using the existing
  AI generation pipeline. If AI is unavailable, the bot explains why and offers
  manual drafting, a configuration placeholder, or cancellation.

Text created elsewhere can also be pasted into manual mode. The bot does not
need to know whether it was written by a person or another tool:

```text
ChatGPT / Gemini / Claude
          ↓
Copy subject and body
          ↓
Telegram manual mode
          ↓
Preview → Approve
```

The deterministic generator remains available for tests, offline development,
and as the internal fallback after a configured AI provider attempt fails. It is
not presented to users as AI.

## Phase 3.5 workflow

```text
/send
  ↓
WAITING_RECIPIENT
  ↓
WAITING_DRAFT_METHOD
  │
  ├── MANUAL
  │     ↓
  │   MANUAL_WAITING_SUBJECT
  │     ↓
  │   MANUAL_WAITING_BODY
  │     ↓
  │   EmailDraft
  │
  └── AI
        ↓
      Availability check
        │
        ├── unavailable → Explain → Manual / Configure placeholder / Cancel
        │
        └── available
              ↓
            WAITING_PURPOSE
              ↓
            WAITING_CONTEXT
              ↓
            WAITING_TONE
              ↓
            Generate → EmailDraft
  ↓
WAITING_FOR_ACTION
  │
  ├── CONFIRM
  │      ↓
  │    Mock Send
  │      ↓
  │     END
  │
  ├── REGENERATE (AI drafts only)
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
  │    ├── EDIT_CONTEXT → Generate Again (AI drafts only)
  │    └── Back to Preview
  │
  └── CANCEL
         ↓
        END
```

AI previews have Confirm, Edit, Regenerate, and Cancel actions. Manual previews
omit Regenerate because there is no generator input to replay. The manual edit
menu similarly omits Original Context; recipient, subject, and message editing
remain available.

The shared approval actions are:

- **Confirm & Send** — explicitly approves the current draft and calls the mock
  sender. The response clearly says that delivery was simulated.
- **Edit** — opens structured choices for recipient, subject, message, and
  original request context.
- **Regenerate** — calls the generator again with the stored request data.
- **Cancel** — discards temporary state without calling the sender.

With AI enabled, regeneration calls the AI generator again with the stored
recipient, purpose, context, and tone, so the result may differ. If the provider
attempt fails, the AI generator may return its deterministic fallback. That
resilience behavior is separate from the UI-level availability check.

Recipient edits preserve subject and body. For AI drafts they also update the
stored source request. Subject and body edits affect only the current draft.
Context edits exist only for AI drafts, update source data, and intentionally
regenerate the whole draft.

## Architecture

```text
Telegram
   ↓
Handler + explicit conversation states
   ↓
Draft creation strategy
   ├── Manual input ─────────────────────┐
   └── Optional AIEmailGenerator         │
              ├── LLMProvider            │
              │      ↓                   │
              │   OpenAIProvider         │
              └── Deterministic fallback │
                                         ↓
                                shared EmailDraft
                                         ↓
                              GeneralEmailWorkflow
                                         ↓
                                 EmailSender protocol
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
  the `EmailGenerator` and `EmailSender` interfaces, never OpenAI. Manual input
  and AI generation are two strategies for constructing the same domain value.
- **Dependency injection:** `build_application` is the composition root. It wires
  an `AIEmailGenerator` only when a real provider is configured, plus the
  `MockEmailSender`, then injects the workflow into Telegram callbacks.
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
- **Accurate capability signaling:** the AI button checks the centrally composed
  capability. A deterministic fallback is never described as available AI.
- **State machine:** manual and AI branches use explicit enum states, then
  converge at the existing preview/action state.
- **Immutability:** `EmailDraft`, request, and session snapshots are frozen
  dataclasses. Edits use `dataclasses.replace`, so an earlier value cannot be
  changed unexpectedly through a shared reference.
- **Human-in-the-loop:** generation only reaches `EmailSender` from the Confirm
  callback. Preview, edit, regenerate, and cancel never imply approval.
- **Progressive enhancement:** manual drafting provides the complete approval
  experience without AI; a configured provider adds generation and regeneration.
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

- With an OpenAI key, the composition root injects `AIEmailGenerator` and the AI
  path is available.
- Without a key, manual mode remains fully functional and choosing AI displays an
  honest unavailable message with a manual fallback action.
- Set `AI_PROVIDER=deterministic` to disable the user-facing AI path even when a
  key exists. The deterministic implementation remains available internally for
  development, tests, and AI-provider fallback.

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

Tests cover manual/AI selection, manual validation and construction, dynamic
preview/edit actions, both complete smoke flows, deterministic fallback,
confirmation, cancellation, regeneration, every edit type, sender failure and
retry, duplicate confirmation, stale callbacks, AI output validation, optional
configuration, and prompt contents. They do not contact Telegram, Gmail, or a
real AI provider.

## Why Gmail is absent

Phase 3.5 improves draft creation without changing the proven approval lifecycle.
Keeping delivery simulated isolates state-machine, editing, idempotency, and
failure-recovery behavior while all sends remain harmless. Gmail API and OAuth
belong to a later phase.

## Current checkpoint

Phase 3.5 is implemented with manual drafting and an optional OpenAI generation
adapter. Gemini and Claude may be used externally and pasted through manual mode,
but are not integrated. Gmail, OAuth, attachments, job applications, databases,
scheduling, and real delivery remain intentionally absent. `MockEmailSender` is
still the only sender.
