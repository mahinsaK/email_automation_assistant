# AI Email Automation Assistant

An extensible, human-in-the-loop email automation system with Telegram as its
first interface. Phase 3B adds encrypted, per-Telegram-user bring-your-own-key
AI configuration. Users can still enter an email manually without any AI
credential. Both creation paths produce the same immutable `EmailDraft`, then
reuse the same preview, editing, approval, cancellation, and simulated-send
lifecycle.

No real email is delivered in this phase.

## Commands

- `/start` — introduction
- `/help` — command list
- `/send` — create and review a general email draft
- `/configure_ai` — configure or safely replace your AI provider credential
- `/ai_status` — show your AI availability without exposing credentials
- `/remove_ai` — remove your saved AI configuration after confirmation
- `/cancel` — discard the active workflow

Invalid input stays in the current state, explains the problem, and asks again.
Temporary data is stored under a workflow-specific key in Telegram `user_data`
and removed on completion or cancellation.

## Phase 3B: Bring Your Own AI Key

Each Telegram user can configure an isolated OpenAI credential. The application
validates the credential with a lightweight authenticated provider request,
encrypts it with Fernet, and stores only the ciphertext in SQLite. Repository
queries, replacement, resolution, and deletion are always scoped by the
authenticated Telegram user ID.

```text
Telegram User
     ↓
UserAIConfigurationService
     ├── Credential Validator
     ├── CredentialCipher (Fernet)
     └── AIConfigurationRepository
                ↓
              SQLite
```

At generation time, provider construction is dynamic and user-specific:

```text
Telegram User ID
     ↓
ConfiguredUserEmailGeneratorResolver
     ↓
Encrypted user configuration
     ↓
Decrypt briefly
     ↓
AIProviderFactory
     ↓
OpenAIProvider for that request/user
     ↓
AIEmailGenerator → EmailDraft
```

The factory keeps provider construction outside Telegram handlers and provides a
small extension point for future Gemini, Claude, OpenRouter, or local adapters.
The email domain remains independent: `EmailDraft` does not contain a Telegram
user ID or credential metadata.

The secret lifecycle is deliberately short:

```text
receive → attempt Telegram message deletion → validate → encrypt → persist
        → discard plaintext reference
```

Raw credentials are never logged, displayed in status messages, or stored in
Telegram `user_data`. Telegram may retain message history or metadata according
to its own behavior, so the bot attempts to delete the credential message after
reading it. A deletion failure does not prevent validation or configuration.

Reconfiguration is transactional from the product's perspective: an existing
encrypted credential is replaced only after the new credential validates and
the encrypted record is saved. An invalid key, provider outage, or failed write
leaves the old configuration untouched.

The runtime SQLite database is initialized automatically and ignored by Git.
The repository uses parameterized SQL and short-lived connections inside
`asyncio.to_thread`, keeping blocking SQLite work off the Telegram event loop
without adding a database framework.

## Draft creation modes

After a valid recipient is entered, the user explicitly chooses a creation
strategy:

- **Manual mode** asks for a subject and body, validates both, and proceeds
  directly to preview. It never invokes an AI or deterministic generator and
  works without an API key.
- **AI mode** is available when that Telegram user has a usable encrypted
  configuration, or when the optional application development fallback is
  configured. It collects purpose, context, and tone before using the existing
  AI generation pipeline. If AI is unavailable, the bot offers real in-chat
  configuration, manual drafting, or cancellation.

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
        ├── unavailable → Configure AI / Manual / Cancel
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

Phase 3B adds these application services alongside the email workflow:

```text
Telegram configuration handlers
             ↓
UserAIConfigurationService
   ├── AIProviderCredentialValidator
   ├── CredentialCipher
   └── AIConfigurationRepository

Telegram email handlers
             ↓
UserEmailGeneratorResolver
   ├── UserAIConfigurationService
   └── AIProviderFactory
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
├── repositories/           # Persistence ports and SQLite adapter
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
  the repository, cipher, validators, provider factory, per-user resolver, and
  `MockEmailSender`, then injects application services into Telegram callbacks.
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
- **Accurate capability signaling:** the AI button checks capability for the
  current Telegram user (then the optional development fallback). A
  deterministic fallback is never described as available AI.
- **State machine:** manual and AI branches use explicit enum states, then
  converge at the existing preview/action state.
- **Immutability:** `EmailDraft`, request, and session snapshots are frozen
  dataclasses. Edits use `dataclasses.replace`, so an earlier value cannot be
  changed unexpectedly through a shared reference.
- **Human-in-the-loop:** generation only reaches `EmailSender` from the Confirm
  callback. Preview, edit, regenerate, and cancel never imply approval.
- **Progressive enhancement:** manual drafting provides the complete approval
  experience without AI; a configured provider adds generation and regeneration.
- **Repository pattern:** persistence became necessary when configuration had to
  survive restarts. Application services depend on `AIConfigurationRepository`,
  while SQLite remains an adapter that can be replaced later.
- **Encryption at rest:** Fernet provides authenticated encryption so a copied
  database does not directly reveal API keys. The independent application key
  must be protected and backed up.
- **Factory pattern:** `AIProviderFactory` owns SDK-adapter construction. Telegram
  code works with provider-neutral abstractions and never branches on SDK types.
- **Multi-tenant isolation:** every configuration operation accepts the current
  Telegram user ID and SQL lookups use that ID as the primary key. One user
  cannot read, resolve, replace, or remove another user's configuration.
- **Secret lifecycle:** plaintext exists only while validating, encrypting, or
  constructing a provider. Stored domain records contain ciphertext only.
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
CREDENTIAL_ENCRYPTION_KEY=
DATABASE_PATH=data/email_assistant.db
```

- A user's encrypted configuration has first priority.
- `OPENAI_API_KEY` is an optional application-level development fallback and has
  second priority. It is not stored in the per-user database.
- Without either credential source, manual mode remains fully functional and
  choosing AI offers `/configure_ai` or manual entry.
- Set `AI_PROVIDER=deterministic` to disable the user-facing AI path even when a
  global key exists. Personal configuration still uses the chosen real provider.
  The deterministic implementation remains internal to tests and AI failure
  fallback; it is never presented as AI.

Generate the required Fernet application encryption key locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Place the output in `CREDENTIAL_ENCRYPTION_KEY`; never commit it. Do not generate
a new value on every startup because previously stored credentials would become
unreadable. If the key is absent or invalid, startup and manual drafting still
work, while `/configure_ai` explains that secure credential storage is
unavailable.

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

Tests cover encrypted round trips, plaintext exclusion from SQLite, valid and
invalid replacement, temporary provider failure, missing encryption setup,
status secrecy, removal confirmation/cancellation, multi-user isolation,
user-specific provider resolution, manual/AI selection, both complete Phase 3B
smoke flows, deterministic fallback, approval, editing, stale callbacks, and AI
output validation. They do not contact Telegram, Gmail, or a real AI provider.

## Why Gmail is absent

Phase 3B adds credential configuration without changing the proven approval lifecycle.
Keeping delivery simulated isolates state-machine, editing, idempotency, and
failure-recovery behavior while all sends remain harmless. Gmail API and OAuth
belong to a later phase.

## Current checkpoint

Phase 3B is implemented with encrypted per-user OpenAI configuration, optional
application-level development fallback, and manual drafting. SQLite is used only
for encrypted AI configuration. Gemini and Claude may be used externally and
pasted through manual mode, but are not integrated. Gmail, OAuth, attachments,
job applications, subscriptions, billing, scheduling, and real delivery remain
intentionally absent. `MockEmailSender` is still the only sender.
