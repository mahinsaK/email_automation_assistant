# AI Email Automation Assistant

An extensible, human-in-the-loop email automation system with Telegram as its
first interface. Phase 5 adds per-user Gmail delivery through Google OAuth 2.0.
General and job-application emails still converge on the same immutable
`EmailDraft`, preview, editing, explicit approval, failure recovery, and
duplicate-send protection. Gmail is invoked only after Confirm is pressed.

## Commands

- `/start` — introduction
- `/help` — command list
- `/send` — create and review a general email draft
- `/apply` — prepare and review a job application email with a CV
- `/configure_ai` — configure or safely replace your AI provider credential
- `/ai_status` — show your AI availability without exposing credentials
- `/remove_ai` — remove your saved AI configuration after confirmation
- `/connect_gmail` — connect Gmail securely through Google OAuth
- `/gmail_status` — show the requesting user's Gmail connection status
- `/disconnect_gmail` — remove the requesting user's saved Gmail authorization
- `/cancel` — discard the active workflow

Invalid input stays in the current state, explains the problem, and asks again.
Temporary data is stored under a workflow-specific key in Telegram `user_data`
and removed on completion or cancellation.

## Phase 5: Gmail OAuth and real delivery

Each Telegram user connects a separate Google account. Gmail passwords are
never requested or handled:

```text
/connect_gmail
      ↓
Opaque, one-time state stored in memory with an expiry
      ↓
Google authorization page in the browser
      ↓
GET /oauth/google/callback
      ↓
Verify and consume state → exchange authorization code
      ↓
Encrypt refresh token with CredentialCipher
      ↓
gmail_connections row keyed by Telegram user ID
```

The state value is cryptographically random and contains no user ID or secret.
It is bound to the initiating Telegram user and the OAuth PKCE verifier in
server memory, expires after ten minutes by default, and is consumed once. The
same verifier is used for authorization and token exchange. This is suitable
for one process. A multi-instance production deployment would need shared
temporary state storage.

Authorization and delivery are deliberately separate:

- `GmailOAuthService` obtains user consent, validates state, exchanges the code,
  and saves the encrypted refresh token.
- `GmailEmailSender` receives an already-approved `EmailDraft`, builds MIME, and
  adapts Gmail's `users.messages.send` API to the existing `EmailSender` port.

At Confirm time, the authenticated Telegram user ID is passed to
`UserEmailSenderResolver`. It loads only that user's connection, decrypts the
refresh token briefly, refreshes access, and constructs an isolated sender. The
Telegram ID is not added to `EmailDraft`.

```text
Telegram user presses Confirm
              ↓
GeneralEmailWorkflow approval claim (PREVIEWED → SENDING)
              ↓
UserEmailSenderResolver
   ├── UserGmailConnectionService
   ├── encrypted SQLite connection
   └── GmailClientFactory (refresh access token)
              ↓
GmailEmailSender → MIME builder → Gmail API
              ↓
      success: SENT / failure: PREVIEWED
```

The only Gmail permission requested is `gmail.send`. The OAuth request also
uses the standard `openid` and `userinfo.email` identity scopes so the bot can
show which account is connected. It does not request mailbox read, modify,
delete, label, or settings permissions.

General messages are plain-text MIME emails. Job applications use the same
builder, which creates a multipart message and includes the configured CV with
its filename and detected MIME type. Missing or unreadable attachments fail
safely before the Gmail send call.

If Gmail is missing, expired, revoked, rate-limited, unavailable, or returns an
invalid response, the draft remains available. The UI offers connection or
reconnection and lets the user return to preview. A failed reconnection does not
replace an existing connection. `MockEmailSender` remains available for unit
tests, smoke tests, and controlled failure simulation.

## Phase 4: Job applications and CV preparation

`/apply` starts a separate explicit state machine while reusing the existing
approval workflow:

```text
/apply
  ↓
Validate configured candidate profile + CV
  ↓
Company email → Company name → Role → Job description
  ↓
Choose draft method
  ├── Manual → Subject → Body ───────────────────────┐
  └── AI → Availability → Tone → Grounded generate ─┤
                                                     ↓
                                            PreparedEmail
                                       EmailDraft + CV metadata
                                                     ↓
                                      Preview / Edit / Regenerate
                                                     ↓
                                           Confirm → Gmail or test fake
```

Manual mode never invokes a generator. AI mode uses the same per-user provider
resolution as general email generation, but a specialized job-application
generator receives the candidate profile, extracted requirements, and explicit
match result. Regenerate is shown only for AI drafts.

The deterministic requirement extractor recognizes a deliberately small,
explicit technology catalogue. The matcher compares those requirements only
with skills stated in the profile, project technologies, or experience skills.
It produces separate matched and unmatched collections; unsupported job
requirements are never converted into candidate qualifications.

AI prompt construction treats the job description and profile as untrusted
data and instructs the provider to use only grounded candidate facts. Provider
output is schema-validated. A conservative semantic guard rejects a generated
subject or body that mentions an unmatched skill and uses the truthful
deterministic fallback instead. This is an additional safety boundary, not a
claim that automated verification can replace human review.

Job-specific editing keeps these distinctions clear:

- Recipient, subject, and body edits update only the corresponding draft value.
- Company, role, and job-description edits update application metadata and
  recompute requirement matching without silently overwriting edited email text.
- An AI user can explicitly choose Regenerate after changing metadata.
- CV attachment metadata is preserved through editing and regeneration.

`EmailAttachment` stores validated path, filename, MIME type, and size without
loading file content into the session. `PreparedEmail` bundles that metadata
with the shared `EmailDraft`. Phase 5's MIME adapter consumes the same validated
attachment path when an approved application is sent.

The Phase 4 dependency direction is:

```text
Telegram /apply handler
          ↓
JobApplicationWorkflow
  ├── CandidateProfileService → local JSON
  ├── CVAttachmentService → local PDF/DOC/DOCX metadata
  ├── RequirementExtractor + CandidateRequirementMatcher
  ├── JobApplicationEmailGenerator
  │      ├── optional LLMProvider
  │      └── truthful deterministic fallback
  └── GeneralEmailWorkflow
             ↓
       EmailSender protocol
          ├── GmailEmailSender
          └── MockEmailSender (tests)
```

The candidate profile and job application session are immutable domain values.
Edits create replacement snapshots with `dataclasses.replace`; no mutable draft
subtype is needed. `JobApplicationWorkflow` owns job-specific preparation while
`GeneralEmailWorkflow` remains the single owner of approval, sender failure
recovery, and in-memory duplicate-confirmation claims.

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
  │   Resolve user's Gmail sender
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
                         UserEmailSenderResolver
                                         ↓
                  per-user Gmail connection + client
                                         ↓
                                EmailSender protocol
                              ├── GmailEmailSender
                              └── MockEmailSender (tests)
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

Telegram general/job handlers
             ↓
UserAIProviderResolver
   ├── per-user encrypted configuration
   └── optional application development configuration
             ↓
   General or job-specific AI generator

Telegram Gmail handlers / HTTP callback
             ↓
GmailOAuthService
   ├── one-time expiring OAuth state
   ├── Google OAuth library adapter
   ├── CredentialCipher
   └── GmailConnectionRepository → SQLite

Approved workflow
             ↓
UserEmailSenderResolver
   ├── UserGmailConnectionService
   ├── GmailClientFactory
   └── GmailEmailSender → Gmail API
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
  Gmail OAuth, per-user sender resolution, and `MockEmailSender` test doubles,
  then injects application services into Telegram callbacks.
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
- **Shared domain model:** manual general email, AI general email, manual job
  application, and AI job application paths all converge on `EmailDraft`.
- **Grounded generation:** `CandidateProfile` is the source of candidate facts;
  explicit requirement matching and output checks prevent unmatched job skills
  from being presented as qualifications.
- **Prepared attachment boundary:** `PreparedEmail` adds typed attachment
  metadata without coupling the email domain or application workflow to Gmail.
- **Workflow composition:** job preparation delegates approval to the existing
  `GeneralEmailWorkflow`, avoiding a second send/idempotency implementation.
- **OAuth 2.0:** Google obtains consent and returns a scoped authorization code;
  the application never sees or stores a Gmail password.
- **Least privilege:** delivery requests `gmail.send`, plus identity-only scopes
  needed to display the connected address. No mailbox read access is requested.
- **Gmail repository:** `GmailConnectionRepository` isolates persistence from
  OAuth and delivery. Every query, replacement, and deletion is keyed by the
  authenticated Telegram user ID.
- **Credential encryption:** only Fernet ciphertext is persisted for refresh
  tokens. Client ID and secret remain deployment configuration; access tokens
  are refreshed in memory and are not saved.
- **Resolver pattern:** `UserEmailSenderResolver` selects the correct Gmail
  sender at Confirm time without coupling Telegram identity to `EmailDraft`.
- **Gmail adapter:** `GmailEmailSender` implements the existing `EmailSender`
  protocol while translating MIME and Gmail API responses into `SendResult`.
- **Authorization versus delivery:** OAuth establishes revocable permission;
  the sender uses that permission only after the workflow records explicit
  human approval.

### Duplicate-send protection

Each approval session receives a unique confirmation ID. The workflow claims the
ID synchronously before awaiting sender I/O, and later confirmation attempts for
that ID are rejected. The draft transitions through:

```text
PREVIEWED → SENDING → SENT
```

A failed send transitions back to `PREVIEWED`, releases the claim, retains the
draft, and permits retry or cancellation. This protection is intentionally
in-memory. It prevents rapid duplicate confirmations in one process. Durable
cross-process idempotency belongs in a later production persistence phase.

Stale or unknown email callback data is answered safely. If workflow state has
already been cleared, the user is told to start again with `/send` or `/apply`,
depending on the callback family.

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
CANDIDATE_PROFILE_PATH=data/candidate_profile.json
CV_FILE_PATH=attachments/CV.pdf
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/oauth/google/callback
GMAIL_OAUTH_SCOPES=openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.send
OAUTH_CALLBACK_HOST=127.0.0.1
OAUTH_CALLBACK_PORT=8000
OAUTH_STATE_TTL_SECONDS=600
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

### Google Cloud OAuth setup

1. Create or select a project in the
   [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the Gmail API for that project.
3. Configure the Google Auth Platform consent screen. During development it may
   remain in **Testing**; add each Gmail account that will connect as a test user.
4. Add only the Gmail send scope
   `https://www.googleapis.com/auth/gmail.send`. The application also requests
   `openid` and `userinfo.email` to identify the connected address.
5. Create an OAuth client with application type **Web application**.
6. Add the exact authorized redirect URI used in `.env`, for example
   `http://localhost:8000/oauth/google/callback`.
7. Copy the client ID and client secret into `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET`. Never commit either value.
8. Start the application and use `/connect_gmail`, open the one-time link, grant
   access, return to Telegram, and verify with `/gmail_status`.

The built-in callback server listens on `OAUTH_CALLBACK_HOST` and
`OAUTH_CALLBACK_PORT`; its public browser address comes from
`GOOGLE_OAUTH_REDIRECT_URI`. This keeps localhost out of the OAuth service and
allows a later deployment to use an HTTPS domain. For local HTTP only, OAuthlib
may require this development environment setting:

```env
OAUTHLIB_INSECURE_TRANSPORT=1
```

Never enable insecure transport for a deployed HTTPS callback. Google requires
the redirect URI to match the OAuth client configuration exactly. The callback
page intentionally shows only success/failure and directs the user back to
Telegram; it never displays codes or tokens.

Official references:

- [Google web-server OAuth flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Create and send Gmail messages](https://developers.google.com/workspace/gmail/api/guides/sending)

Job applications require local profile and CV files even when drafting is
manual. Copy and edit the committed placeholder profile:

```bash
cp data/candidate_profile.example.json data/candidate_profile.json
mkdir -p attachments
cp /path/to/your/CV.pdf attachments/CV.pdf
```

`candidate_profile.json` and files under `attachments/` are ignored by Git.
Supported CV extensions are `.pdf`, `.doc`, and `.docx`; the configured file
must exist, be readable, and be non-empty. The example profile contains only
placeholders—replace every value with accurate candidate facts before using
`/apply`. The current local-file design represents one deployment profile; it
does not yet provide per-user candidate-profile persistence.

Then run:

```bash
python main.py
```

Open the bot in Telegram, connect Gmail, and use `/send` or `/apply`. Generation
still never sends automatically: only Confirm can invoke Gmail.

### Optional manual real-account smoke test

Automated tests never send real mail. After configuring a test Google account,
an operator can verify manually:

```text
/connect_gmail → browser consent → /gmail_status
/send → manual draft → preview → Confirm → verify receiver inbox
/apply → company details → manual/AI draft → preview → Confirm
       → verify the configured CV arrived
```

## Test

```bash
pytest
```

Tests cover encrypted round trips, plaintext exclusion from SQLite, valid and
invalid replacement, temporary provider failure, missing encryption setup,
status secrecy, removal confirmation/cancellation, multi-user isolation,
user-specific provider resolution, manual/AI selection, both complete Phase 3B
smoke flows, deterministic fallback, approval, editing, stale callbacks, and AI
output validation. Phase 4 tests additionally cover profile and CV validation,
requirement extraction/matching, unsupported-skill rejection, immutable job
edits, attachment preservation, retry/duplicate behavior, AI-unavailable manual
fallback, and complete manual and fake-AI `/apply` smoke flows. They do not
contact Telegram, Gmail, or a real AI provider. Phase 5 adds network-free tests
for authorization URL construction, state forgery/replay/expiry, encrypted
refresh-token persistence, failed reconnect preservation, multi-user isolation,
status secrecy, disconnect, access refresh, MIME headers and PDF attachment,
sender resolution, revoked authorization, retryable failures, and duplicate
confirmation.

## Production limitations

Phase 5 uses SQLite for encrypted AI and Gmail connection records and in-memory
OAuth state and duplicate-send claims. That is appropriate for one process or a
demonstration. A production multi-instance deployment should later move durable
state and idempotency to managed shared infrastructure such as PostgreSQL. This
phase intentionally does not add deployment automation, PostgreSQL, Redis,
background workers, inbox access, subscriptions, or billing.

## Current checkpoint

Phase 5 is implemented with per-user Google OAuth, encrypted refresh-token
storage, sender resolution, access-token refresh, real Gmail delivery, and MIME
CV attachments. Human confirmation remains mandatory. Candidate profiles and
job history are not persisted in SQLite. `MockEmailSender` remains available for
tests and offline development; production composition selects Gmail per user.
