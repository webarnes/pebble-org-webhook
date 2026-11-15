# Index Org Webhook

Accepts Pebble Index 01 voice-memo transcripts and appends them to Org files:

- Task-like memos go under `* Inbox` in `todo.org` (newest first).
- Everything else goes under `* Log` in today’s org-roam daily file.

The Index app POSTs `multipart/form-data` to an HTTPS URL. This service is meant to run on your home server, bind to localhost, and be published only on the Tailscale tailnet.

## How a memo is classified

Transcripts are classified by an LLM via an OpenAI-compatible `/chat/completions` endpoint (defaulting to Google Gemini; switchable to local models such as Ollama via `LLM_BASE_URL` and `LLM_MODEL`):

- **Clear reminders** become `** TODO` items under `* Inbox` in `todo.org` (newest first), with a `SCHEDULED:` line when a clear date or time is present and the timestamped raw transcript recorded in `:LOGBOOK:`.
- **Notes** go under `* Log` in today’s org-roam daily file with a succinct summary heading, the exact transcript text, and any implied action items appended as `- [ ]` checkboxes for evening review.
- **Fallback**: If the LLM is not configured, times out, or fails, the memo is saved as a daily note with a heuristic heading so no recording is lost.

### LLM configuration

Set these environment variables in `.env` (or `/etc/index-org-webhook.env`):

- `LLM_BASE_URL`: OpenAI-compatible base URL (default: `https://generativelanguage.googleapis.com/v1beta/openai`)
- `LLM_API_KEY`: API key for the provider (optional for unauthenticated local endpoints)
- `LLM_MODEL`: Model name (default: `gemini-flash-latest`)
- `LLM_TIMEOUT_SECONDS`: HTTP request timeout in seconds (default: `15.0`)

### Testing LLM classification locally

To interactively test classification and preview the Org output without modifying any files:

```bash
.venv/bin/python -m index_org_webhook.cli
```

Or pass a transcript directly:

```bash
.venv/bin/python -m index_org_webhook.cli "Remind me to call the dentist Monday at 9am"
```

(If installed in an active virtualenv, `index-org-classify` is also available.)

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# set INDEX_WEBHOOK_SECRET and ORG_DIRECTORY
pytest
uvicorn index_org_webhook.app:app --host 127.0.0.1 --port 8787
```

Signed test POST (replace the signature with a real HMAC if `INDEX_REQUIRE_SIGNATURE=true`; easier to run `pytest` or temporarily set `INDEX_REQUIRE_SIGNATURE=false` for curl):

```bash
curl -sS -X POST http://127.0.0.1:8787/webhook \
  -H 'X-Index-Webhook-Version: 1' \
  -H 'X-Index-Delivery: local-test-1' \
  -H 'X-Index-Trigger: single-click-hold' \
  -F 'transcription=call the dentist' \
  -F 'recordedAt=1763169660000' \
  -F 'client=ring'
```

## Home server

1. Clone this repo on the Ubuntu host that already Syncthing-syncs `Documents`.
2. Create a venv and `pip install -e .`.
3. Copy `.env.example` to `/etc/index-org-webhook.env`. Generate a secret:

   ```bash
   python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

   Set `ORG_DIRECTORY` to the synced Org path (for example `/home/USER/DIR/Org`).
4. Install and start the unit:

   ```bash
   sudo cp systemd/index-org-webhook.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now index-org-webhook
   ```

   Adjust `User`, `WorkingDirectory`, and `ExecStart` in the unit if the checkout path differs.
5. Publish HTTPS on the tailnet (not the public internet):

   ```bash
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8787
   ```

   The phone URL is `https://<server>.<tailnet>.ts.net/webhook`. Confirm with `tailscale serve status`.
6. Install Tailscale on the phone so it is on the same tailnet.

## Updating the home server

To update the code, dependencies, and restart the service in one step:

```bash
cd /path/to/index-org-webhook
./update.sh
```

This runs `git pull`, ensures dependencies are up-to-date in editable mode via `.venv/bin/pip install -e .`, and restarts `index-org-webhook.service`.

## Index 01 settings

In Index 01 Settings → Webhook, for each gesture you want (Hold & talk and/or Double click & hold):

1. URL: `https://<server>.<tailnet>.ts.net/webhook`
2. Enable **Sign requests** and paste the same value as `INDEX_WEBHOOK_SECRET`
3. Payload: **Transcription only**
4. Optionally add `Authorization: Bearer <INDEX_AUTH_TOKEN>` if that env var is set
5. **Send test event** — the server should return 200 and write nothing
6. Save

A real Hold & talk should then appear in `todo.org` or `Org/roam/daily/YYYY-MM-DD.org` on this Mac after Syncthing syncs.

## Security notes

- HMAC authenticates the request; it does not encrypt the transcript. HTTPS (Tailscale Serve) is still required.
- `X-Index-Delivery` is stored in SQLite so Index retries do not duplicate headings.
- The process binds to `127.0.0.1` by default.
