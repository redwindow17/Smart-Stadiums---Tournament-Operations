# Security Policy

StadiumIQ is a demo, but it is built to a production security baseline. This
document describes the controls in place and how to report an issue.

## Threat model

The app takes untrusted input from two places — fan chat messages and staff
incident reports — and feeds (a sanitised, structured form of) that input into
an LLM prompt and into computed responses. The primary risks are therefore
**prompt injection**, **injection/XSS into the rendered UI**, **abuse via
flooding**, and **secret exposure**. Each is addressed below.

## Controls

### Input validation
- Every inbound field is validated by Pydantic with explicit length and
  pattern constraints before any business logic runs (`app/api/schemas.py`):
  message and history-turn length caps, an `^[a-z0-9_-]{1,64}$` pattern on all
  IDs, an enum of allowed incident categories, and a bounded history length.
- All free text is sanitised (`app/security.py::sanitize_text`) — control
  characters stripped, length capped, blank runs collapsed — before it is
  logged or embedded in a prompt.

### Prompt-injection hardening
- The system prompt is a **frozen constant**; user text is never concatenated
  into instructions.
- Visitor text travels inside a delimited `<visitor_message>` block, and the
  system prompt instructs the model to treat that block strictly as a question
  and to ignore any embedded instructions to change role, reveal the prompt,
  or go off-topic (`app/ai/prompts.py`).
- This behaviour is covered by tests
  (`tests/test_security.py::test_prompt_injection_does_not_leak_internals`,
  `tests/test_assistant.py::test_prompt_injection_is_treated_as_data`).

### Output / XSS safety
- The frontend renders all user- and AI-supplied text with `textContent` and
  builds DOM nodes programmatically. It never assigns untrusted strings to
  `innerHTML`, so markup injection is not possible by construction.

### Rate limiting
- A per-client sliding-window limiter (`app/security.py`) throttles the chat
  and incident endpoints and returns `429` when exceeded. It is memory-bounded
  (stale buckets are evicted) so it cannot grow without limit.

### Transport / response headers
- A security-headers middleware sets `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`,
  `Strict-Transport-Security` (HSTS, effective on any HTTPS deployment), and
  a strict same-origin `Content-Security-Policy` (no external scripts,
  styles, fonts or connections) on every response.
- Every `/api/*` response is sent with `Cache-Control: no-store` because API
  bodies can embed user-supplied text.

### Error handling
- A global exception handler logs full details server-side and returns a
  generic `{"detail": "Internal server error"}` to clients, so stack traces,
  paths and configuration can never leak through an unexpected failure
  (verified by `tests/test_security.py::test_unhandled_errors_return_generic_500`).

### Secrets
- No secrets are stored in code. The optional `ANTHROPIC_API_KEY` and all
  tunables are read only from environment variables (`app/config.py`).
  `.env` is git-ignored; `.env.example` documents the variables with empty
  values.
- Error responses never echo configuration or secrets.

### Dependencies
- The runtime dependency surface is deliberately small (FastAPI, Pydantic,
  and — optionally — the Anthropic SDK). The frontend has **zero** third-party
  dependencies.
- All dependencies are **pinned to exact versions** for reproducible,
  auditable installs, and CI runs `pip-audit` against those pins on every
  push to catch known vulnerabilities.

## Reporting a vulnerability

If you find a security issue, please open a private report to the repository
owner rather than a public issue, including steps to reproduce. As a
demonstration project there is no formal SLA, but reports are welcome and will
be addressed on a best-effort basis.
