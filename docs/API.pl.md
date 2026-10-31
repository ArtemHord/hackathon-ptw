# Call Crew: kontrakt API dla aplikacji

Zamrożony po M0. Zmiany tylko przez issue z etykietą `contract` + aktualizacja `mocks/*.json` w tym samym PR. Aplikacja budowana na mockach przechodzi na prawdziwy backend zmianą `BASE_URL`. Treści w mockach i odpowiedziach agenta są po angielsku.

## Podstawy

- `BASE_URL`: lokalnie `http://localhost:8000`, produkcja `https://<railway-host>` (PUBLIC_BASE_URL). WS: ten sam host, `ws://` / `wss://`.
- Auth REST: nagłówek `Authorization: Bearer <DEMO_TOKEN>` (jeden użytkownik demo). Brak/zły token: `401`.
- Auth WS: query `?token=<DEMO_TOKEN>` (przeglądarkowe/mobilne WS nie ustawiają nagłówków). Zły token: zamknięcie z kodem 4401.
- Content-Type: `application/json`, UTF-8. Czasy: ISO 8601 UTC (`2026-10-31T09:00:00Z`). Pole `ts` wewnątrz danych rozmowy (utterance, fact-check, eskalacja) = sekundy od początku rozmowy (integer).
- Błędy (każdy status >= 400, poza `/tts` też JSON):

```json
{"error": {"code": "not_found", "message": "Meeting m_99 not found"}}
```

Kody: `400 bad_request`, `401 unauthorized`, `404 not_found`, `409 conflict` (np. propozycja już rozpatrzona), `422 validation_error`, `502 upstream_error` (Recall/OpenAI/ElevenLabs), `500 internal`.

- Enumy: `platform`: `google_meet | zoom | teams`; `mode`: `notetaker | delegate`; meeting `status`: `joining | in_call | done | failed`; escalation `status`: `waiting | answered | timeout`; fact-check `verdict`: `confirmed | contradicted | unverified`; proposal `status`: `pending | approved | rejected`.

## Endpointy aplikacji

### POST /meetings
Request: `{"meeting_url": "https://meet.google.com/abc-defg-hij", "mode": "delegate", "brief": "Done: SDK v2. Blocked: rate limit. Do not agree to deadlines.", "title": "Q4 API sync"}` (`brief`, `title` opcjonalne; brief ma sens w trybie `delegate`).
Response `201`: `{id, status: "joining", title, platform, mode, started_at}`. Mock: `mocks/meeting_create.json`.

### GET /meetings
Lista rozmów właściciela, najnowsze pierwsze. Response `200`: `{items: [{id, title, platform, mode, status, live, started_at, duration_min}]}`; `live` = true gdy bot jest w rozmowie (znaczek LIVE); `duration_min` = null dopóki trwa. Mock: `mocks/meetings_list.json`.

### GET /meetings/{id}?since=<ts>
Szczegóły rozmowy. Bez `since`: pełny obiekt. Z `since` (sekundy od początku rozmowy, integer): tablice `utterances`, `fact_checks`, `escalations`, `agent_said` zawierają tylko elementy z `ts > since`, z wyjątkiem eskalacji, które zmieniły status od tego czasu (zwracane w całości, klucz `id`); pola skalarne (`status`, `summary`...) zawsze aktualne. Służy do odpytywania co 2 s, gdy WS nie działa. Pola `summary`, `decisions`, `action_items` są puste (`""`, `[]`) do końca podsumowania. Mock: `mocks/meeting_detail.json`.

Element `action_items`: `{id, owner, text, due, jira_key, jira_url}`; `jira_key`/`jira_url` = null, dopóki nie ma zgłoszenia w Jirze. `id` jest stabilne (zapisane albo `ai_NN` wg pozycji). (Dodane M7, zmiana kontraktu.)

### POST /meetings/{id}/action-items/{item_id}/jira
Tworzy zgłoszenie w Jirze (projekt `JIRA_PROJECT_KEY`, typ Task, opis ADF) dla jednego action itemu i zapisuje klucz na itemie. Idempotentne: jeśli item ma już `jira_key`, zwraca istniejący. Request: puste ciało. Response `200`: `{jira_key: "PTW-42", url: "https://<site>.atlassian.net/browse/PTW-42"}`. Błędy: `404` nieznana rozmowa / item, `409` `not_configured` (Jira nieustawiona), `502` `upstream_error` (komunikat z Jiry). (Dodane M7, zmiana kontraktu.)

### POST /meetings/{id}/leave
Bot wychodzi z rozmowy, backend uruchamia podsumowanie (asynchronicznie). Request: puste ciało. Response `200`: `{id, status: "done", summary_status: "processing"}`. Mock: `mocks/meeting_leave.json`.

### POST /meetings/{id}/ask
Zapasowy wyzwalacz (przycisk „Ask agent” na ekranie Live), gdy rozpoznawanie mowy nie usłyszało „Crew”. Request: `{"text": "..."}` (opcjonalne; bez `text` agent bierze ostatnią wypowiedź z rozmowy). Działa tylko w trybie `delegate` i gdy bot jest w rozmowie. Response `202`: `{id, accepted: true, question}`; odpowiedź agenta przychodzi zdarzeniem WS `agent_said` (albo `escalation_created`). Błędy: `404` nieznana rozmowa, `409` `not_delegate` / `not_in_call` / `busy`. Mock: `mocks/meeting_ask.json`. (Dodane po M0 za zgodą Artema, 05:10.)

### POST /chat
Request: `{"question": "What is our API limit?"}`. Response `200`: `{answer, citations: [...]}`. Cytat to `{type: "meeting", meeting_id, ts, speaker, text}` (tap otwiera rozmowę na wypowiedzi `ts`) albo `{type: "document", doc_id, title, version}`. Mock: `mocks/chat.json`.

### POST /tts
Request: `{"text": "The limit is 50 rps."}`. Response `200`: ciało binarne `audio/mpeg` (nie JSON). Błąd: JSON jak wyżej. Brak mocka: aplikacja używa dowolnego krótkiego mp3 lokalnie.

### GET /kb/docs
Response `200`: `{items: [{id, title, version, updated_at, chunks, versions: [{version, updated_at}]}]}`. Mock: `mocks/kb_docs.json`.

### POST /kb/docs
Upload pliku .md: `multipart/form-data`, pole `file` (opcjonalnie `title`). Response `201`: `{id, title, version, updated_at, chunks}`. Mock: `mocks/kb_doc_create.json`.

### GET /kb/proposals
Propozycje zmian bazy wiedzy z fact-checku. Response `200`: `{items: [{id, doc_id, doc_title, status, created_at, meeting_id, ts, speaker, reason, old_text, new_text}]}`; domyślnie tylko `pending`, `?status=all` dla wszystkich. Mock: `mocks/kb_proposals.json`.

### POST /kb/proposals/{id}/approve
Puste ciało. Response `200`: `{id, status: "approved", doc_id, doc_version}` (powstaje nowa wersja dokumentu). Mock: `mocks/kb_proposal_approve.json`.

### POST /kb/proposals/{id}/reject
Puste ciało. Response `200`: `{id, status: "rejected", doc_id, doc_version: null}`. Kształt jak w `mocks/kb_proposal_approve.json` z `status: "rejected"`; osobnego mocka nie ma.

## WebSocket: /app/ws?meeting_id=&token=

Jeden WS na ekran Live. Każda wiadomość to envelope:

```json
{"type": "utterance", "meeting_id": "m_01", "ts": "2026-10-31T09:05:05Z", "data": {}}
```

`ts` envelope = czas zdarzenia (ISO UTC); `data.ts` = sekundy od początku rozmowy. Elementy `data` mają to samo `id` co w `GET /meetings/{id}`.

| type | data | Mock |
| --- | --- | --- |
| `utterance` | `{id, speaker, text, ts}` | `mocks/ws_utterance.json` |
| `fact_check` | `{id, claim, verdict, source, correction, proposal_id (nullable), ts}` | `mocks/ws_fact_check.json` |
| `escalation_created` | pełny obiekt eskalacji (niżej), `status: "waiting"` | `mocks/ws_escalation_created.json` |
| `escalation_answered` | pełny obiekt eskalacji, `status: "answered"` (`answer`, `answered_ts` ustawione) lub `"timeout"` (`answer: null`, `answered_ts: null`); osobnego typu `escalation_timeout` nie ma | `mocks/ws_escalation_answered.json`, `mocks/ws_escalation_timeout.json` |
| `agent_said` | `{id, text, ts, in_reply_to?}` (`in_reply_to` = id eskalacji) | `mocks/ws_agent_said.json` |
| `meeting_status` | `{status: "joining" lub "in_call" lub "done" lub "failed"}` | `mocks/ws_meeting_status.json` |
| `meeting_ended` | `{status: "done" lub "failed", duration_min}` | `mocks/ws_meeting_ended.json` |

**Obiekt eskalacji** (identyczny w WS i w `escalations[]` z `GET /meetings/{id}`): `{id, expert, channel, question, asked_by, ts, status, answer, answered_ts}`; `ts` = czas pytania (sekundy od początku rozmowy), `status` = `waiting | answered | timeout`, `answer` i `answered_ts` = null do odpowiedzi. Aplikacja podmienia kartę po `id` (każde zdarzenie niesie pełny obiekt).

Karta eskalacji: `escalation_created` dodaje kartę o `id` (waiting), `escalation_answered` z tym samym `id` aktualizuje ją (answered, albo timeout z `answer: null`).  Zmiany statusu rozmowy przychodzą zdarzeniem `meeting_status` (i polem `status` w `GET /meetings/{id}`).

## Konfiguracja agenta i narzędzia testowe (dodane M7, web app `/ui`)

Addytywne, poza ekranami mobilnymi. Auth jak wyżej (Bearer `DEMO_TOKEN`). Wartości z bazy (`app_settings`) mają pierwszeństwo przed env.

- `GET /settings` → `{values: {<KEY>: {secret, value, set, hint, source}}, public_base_url}`; klucze: `AGENT_NAME, OWNER_NAME, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY, JIRA_AUTO_CREATE`. Sekrety nigdy nie wracają (`value: null`, `hint: "…ab12"`); `source`: `db | env | unset`.
- `PUT /settings` — częściowy `{<KEY>: "value"}`; `""` usuwa nadpisanie (powrót do env); nieznany klucz → `422`. Odpowiedź jak `GET`.
- `GET /integrations` → `{slack: {configured, webhook_url}, telegram: {configured, webhook_url, bot_username}, jira: {configured, base_url, project_key}}`.
- `POST /integrations/{slack|telegram|jira}/test` → `{ok, detail}` (+ `bot_username` dla telegram; test Telegrama rejestruje też webhook, gdy ustawione `PUBLIC_BASE_URL` i sekret).
- `GET /experts` → `{items: [{id, name, role, topics, channel: "slack"|"telegram", email, slack_user_id, telegram_chat_id, is_owner}]}`; `POST /experts` → `201`; `PUT /experts/{id}` (częściowy); `DELETE /experts/{id}` → `{id, deleted: true}`; `POST /experts/{id}/test` → `{ok, detail}`. Bez bazy zapis → `409`.
- `POST /debug/simulate` `{speed?: 20, expert_reply?: "Thursday" | null}` → `202 {meeting_id}`; odtwarza `seed/demo_transcript.json` jako webhooki Recall; bez bazy → `409`. `/debug/*` przyjmuje Bearer `DEMO_TOKEN` albo `?token=WEBHOOK_TOKEN`.

## Poza kontraktem aplikacji (webhooki i strona agenta)

`POST /webhooks/recall/transcript`, `POST /webhooks/recall/status`, `POST /webhooks/slack`, `POST /webhooks/telegram`, `GET /agent`, `WS /agent-page/ws`, `GET /health`.

## Ekrany -> endpointy -> mocki

| Ekran # | Ekran | Endpoint / zdarzenie | Mock |
| --- | --- | --- | --- |
| 1 | Rozmowy | `GET /meetings` | `meetings_list.json` |
| 2 | Nowa rozmowa | `POST /meetings` | `meeting_create.json` |
| 3 | Live | `WS /app/ws`: `utterance`, `fact_check`, `escalation_created`, `escalation_answered` (też timeout), `agent_said`, `meeting_status`, `meeting_ended` | `ws_meeting_status.json`, `ws_escalation_timeout.json`, `ws_utterance.json`, `ws_fact_check.json`, `ws_escalation_created.json`, `ws_escalation_answered.json`, `ws_agent_said.json`, `ws_meeting_ended.json` |
| 3 | Live (Wyjdź) | `POST /meetings/{id}/leave` | `meeting_leave.json` |
| 3 | Live (Ask agent) | `POST /meetings/{id}/ask` | `meeting_ask.json` |
| 3 | Live (fallback bez WS) | `GET /meetings/{id}?since=` | `meeting_detail.json` |
| 4 | Szczegóły rozmowy | `GET /meetings/{id}` | `meeting_detail.json` |
| 4 | Szczegóły rozmowy (Create in Jira) | `POST /meetings/{id}/action-items/{item_id}/jira` | brak (`{jira_key, url}`) |
| 5 | Czat z agentem | `POST /chat` | `chat.json` |
| 5 | Czat (Odsłuchaj) | `POST /tts` | brak (audio/mpeg) |
| 6 | Baza wiedzy | `GET /kb/docs`, `POST /kb/docs` | `kb_docs.json`, `kb_doc_create.json` |
| 6 | Baza wiedzy (propozycje) | `GET /kb/proposals` | `kb_proposals.json` |
| 6 | Baza wiedzy (Approve / Reject) | `POST /kb/proposals/{id}/approve` i `/reject` | `kb_proposal_approve.json` |
