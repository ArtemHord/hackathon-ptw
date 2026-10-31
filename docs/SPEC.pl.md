# Call Crew — specyfikacja MVP

31.10.2026 · Artem · hackathon START Warsaw × Bending Spoons, code freeze o 11:00

## Decyzje

| Warstwa | Wybór |
| --- | --- |
| Backend | Python 3.12, uv, FastAPI + uvicorn, pydantic v2 + pydantic-settings, httpx (async), ruff |
| Baza | Supabase (Postgres + pgvector), region EU (Frankfurt); dostęp przez asyncpg + pakiet `pgvector`; migracje `backend/migrations/*.sql` + `scripts/migrate.py` |
| Bot w rozmowie | Recall.ai, region eu-central-1 (zapasowo us-west-2, pay-as-you-go); Output Media + transkrypcja `prioritize_low_latency` |
| LLM | OpenAI; model czatu z env `OPENAI_CHAT_MODEL` (do weryfikacji: aktualny szybki model ze structured outputs), embeddingi `text-embedding-3-small` (1536) |
| Głos | ElevenLabs TTS przez REST, mp3; model z env `ELEVENLABS_MODEL_ID` (do weryfikacji) |
| Eskalacja | Slack jako główny kanał, Telegram jako zapasowy; wspólny interfejs `Notifier` |
| Strona agenta | jeden statyczny `agent-page/index.html` + vanilla JS, serwowany przez FastAPI pod `/agent`, bez kroku build |
| Realtime | WebSockety FastAPI, hub w pamięci (jedna instancja) |
| Zadania w tle | `asyncio.create_task`; webhooki odpowiadają 200 od razu |
| Deploy | Dockerfile + Railway (region EU); lokalnie ngrok |
| Testy | pytest + pytest-asyncio + respx; `scripts/simulate_meeting.py` odtwarza transkrypt jako webhooki Recall |
| Mobile | Flutter (Misza), po makiecie |
| Kolejność | najpierw cały backend + testy bez aplikacji, potem mobile według makiety |

## Ocena pomysłu

Robimy, ale bohaterem demo jest agent-zastępca, który doprowadza pytanie do końca. Notatki i czat z historią rozmów to tylko fundament: to już jest na rynku.

| Funkcja | Czy jest na rynku | Rola u nas |
| --- | --- | --- |
| Notatki i podsumowanie rozmowy | Jest: [Otter](https://www.castmagic.io/software-review/otter-ai) nagrywa, transkrybuje i ma czat po treści spotkania | Fundament, nie sprzedajemy jako nowości |
| Odpowiedzi w rozmowie z danych firmy | Jest: [Otter Meeting Agent](https://www.uctoday.com/collaboration/otter-revolutionises-meetings-with-ai-agent-that-speaks-up-during-calls/) odpowiada głosem na żywo z bazy spotkań; Zoom, Teams i Meet mają [własnych asystentów AI](https://www.itpro.com/technology/artificial-intelligence/otterai-thinks-its-new-generative-ai-tools-will-give-microsoft-google-and-zoom-a-run-for-their-money) | Robimy przez tryb delegata |
| Agent-zastępca: „nie wiem → pytam Dimę na Slacku → odczytuję jego odpowiedź w tej samej rozmowie” | Nie znaleźliśmy (szukaliśmy pobieżnie) | **Bohater demo** |
| Fact-check względem dokumentacji + propozycja aktualizacji dokumentu | Nie sprawdzaliśmy | Druga funkcja, jeśli zdążymy |
| Mobilny czat z historią rozmów | Czat po spotkaniach jest w Otterze | Wsparcie: 15 sekund na końcu demo |

Dlaczego tak: Bending Spoons chce jednej funkcji, która rozwiązuje problem do końca. U innych „agent nie zna odpowiedzi” to ślepy zaułek. U nas pytanie trafia do właściwej osoby i wraca z odpowiedzią do tej samej rozmowy.

Otwarte pytanie: przed pitchem 10 minut szukania, czy ktoś już robi eskalację do komunikatora z powrotem odpowiedzi do rozmowy.

## Produkt i demo w 90 sekund

Użytkownik robi jedną rzecz: wkleja link do rozmowy. Agent siedzi w rozmowie zamiast niego albo obok niego i zamyka pytania, na które sam nie zna odpowiedzi.

Dwa tryby:

- **Notatnik** (domyślny): agent milczy, pisze transkrypt, wrzuca fact-check na czat rozmowy, po rozmowie daje podsumowanie, decyzje i zadania.
- **Delegat**: agent odpowiada za właściciela na podstawie jego briefu („co zrobiłem”) i bazy wiedzy, tylko gdy ktoś zwraca się do niego po imieniu „Crew”. Gdy nie zna odpowiedzi, pyta eksperta na Slacku i odczytuje jego odpowiedź.

Co robi użytkownik w MVP:

1. Wkleja w aplikacji link do Meet, Zoom albo Teams, wybiera tryb, pisze brief.
2. Po rozmowie otwiera ją w aplikacji: podsumowanie, decyzje, zadania, flagi fact-checku, eskalacje.
3. Pyta na czacie: „Co tech lead powiedział o nowej funkcji?” i dostaje odpowiedź z cytatem i czasem w rozmowie.
4. Zatwierdza albo odrzuca proponowane zmiany bazy wiedzy.

| Sekundy | Kto | Co się dzieje |
| --- | --- | --- |
| 0–10 | Artem | „Na stand-up zamiast mnie pójdzie Crew”. Wkleja link Google Meet w aplikacji, tryb „Delegat”. |
| 10–20 | Bot | Wchodzi do Meet jako „Atlas (AI) for Artem”. |
| 20–35 | Misza | „Atlas, what did Artem finish this week?” — agent odpowiada z briefu głosem ElevenLabs. |
| 35–60 | Misza | „Atlas, when do we migrate to Postgres 17?” — „I don’t know, asking Dima now”. Na scenie „Dima” dostaje wiadomość na Slacku, odpisuje „Thursday”, agent w rozmowie: „Dima says: Thursday”. **Wow-moment.** |
| 60–75 | Misza | „Our API limit is 100 requests per second” — na czacie Meet: „Docs say 50 rps (api.md). Update?” |
| 75–90 | Artem | W aplikacji: podsumowanie rozmowy, pytanie „What did Dima say about the migration?” z odpowiedzią i cytatem, w skrzynce — propozycja aktualizacji dokumentu. |

Demo robimy po angielsku: w trybie niskiej latencji [transkrypcja Recall](https://docs.recall.ai/reference-link/recallai-transcription) obsługuje tylko angielski. „Dimę” z telefonem przez 30 sekund może zagrać Julian albo Rem z drugiej drużyny.

## Architektura

```
Rozmowa (Meet/Zoom/Teams) --dźwięk--> Bot Recall.ai --transkrypt (webhook)--> Backend FastAPI
Backend --audio przez WS--> Strona agenta /agent (kamera bota) --głos--> Rozmowa
Backend <--prompt/JSON--> OpenAI (LLM + embeddingi)
Backend <--tekst/audio--> ElevenLabs (TTS)
Backend <--zapis/wyszukiwanie--> Supabase (Postgres + pgvector)
Backend <--pytanie/odpowiedź--> Ekspert „Dima” (Slack, zapasowo Telegram)
Backend <--REST + WebSocket--> Aplikacja mobilna
```

Bot Recall siedzi w rozmowie i wysyła transkrypt do backendu. Backend myśli z OpenAI i Supabase, a mówi przez ElevenLabs i stronę agenta. Trudne pytania wysyła „Dimie” na Slacku i zwraca odpowiedź do tej samej rozmowy. Aplikacja mobilna bierze wszystko z tego samego backendu.

## Jak agent wchodzi do Google Meet, Zoom i Teams

Bierzemy Recall.ai: jedno zapytanie API z linkiem i bot wchodzi do Meet, Zoom albo Teams, oddaje transkrypt i umie mówić. Własnych botów pod każdą platformę nie napiszemy w jedną noc.

- **Wejście do rozmowy:** `POST /api/v1/bot/` z `meeting_url`. Bot wchodzi jako zwykły uczestnik.
- **Głos:** `output_media.camera` = nasza strona agenta. Recall otwiera ją w przeglądarce bota, podaje dźwięk rozmowy do strony jako mikrofon, a dźwięk strony oddaje do rozmowy ([blog Recall](https://www.recall.ai/blog/how-to-build-an-ai-voice-agent)). Czyli głos agenta to dowolne audio, które gra nasza strona.
- **Transkrypt na żywo:** `recallai_streaming` w trybie `prioritize_low_latency` + webhook na event `transcript.data` dają tekst w 1–3 sekundy. Bez tego trybu webhooki spóźniają się o 3–10 minut ([dokumentacja](https://docs.recall.ai/reference-link/recallai-transcription)).
- **Stabilny dźwięk:** `variant: web_4_core` ([Output Media](https://docs.recall.ai/v1.10/docs/stream-media)).
- **Czat rozmowy:** Recall umie wysyłać i odbierać wiadomości na czacie rozmowy; tam idzie fact-check. Dokładna ścieżka i pola endpointu: **do weryfikacji**.

```json
POST https://eu-central-1.recall.ai/api/v1/bot/
Authorization: <RECALL_API_KEY>
{
  "meeting_url": "https://meet.google.com/xxx-xxxx-xxx",
  "bot_name": "Call Crew (AI) for Artem",
  "output_media": {
    "camera": { "kind": "webpage",
                "config": { "url": "https://<host>/agent?meeting_id=<id>&token=<t>" } }
  },
  "variant": { "google_meet": "web_4_core", "zoom": "web_4_core", "microsoft_teams": "web_4_core" },
  "recording_config": {
    "transcript": { "provider": { "recallai_streaming": {
        "mode": "prioritize_low_latency", "language_code": "en" } } },
    "realtime_endpoints": [ { "type": "webhook",
        "url": "https://<host>/webhooks/recall/transcript?meeting_id=<id>&token=<t>",
        "events": ["transcript.data"] } ]
  }
}
```

Pierwszym testem sprawdzić, czy Recall przyjmuje `output_media` i `recording_config` w jednym zapytaniu. Jeśli nie, włączamy głos osobnym wywołaniem `POST /api/v1/bot/{id}/output_media/`. Region w URL = region, w którym utworzono klucz API (każdy region to osobne konto i osobny klucz).

- **Google Meet:** bot-gość czeka, aż host go wpuści. Na demo host klika „Wpuść”.
- **Zoom i Teams:** to samo zapytanie, inny link. Na demo wystarczy Meet, a w pitchu mówimy „działa we wszystkich trzech”.
- **Cena:** $0.70 za godzinę bota + $0.15 za godzinę transkrypcji, pierwsze 5 godzin za darmo po rejestracji ([cennik Recall](https://www.recall.ai/pricing)). Noc testów to kilka dolarów.

| Wariant | Plusy | Minusy | Decyzja |
| --- | --- | --- | --- |
| Recall.ai | Meet, Zoom, Teams jednym API; transkrypt; głos przez Output Media; jest [przykład agenta głosowego](https://docs.recall.ai/v1.10/page/tutorials) | Płatny po darmowych godzinach | **Bierzemy** |
| [Attendee](https://attendee-website-2.pages.dev/changelog.html) (open source) | Dwukierunkowe audio w czasie rzeczywistym przez WebSocket, self-hosting dużo tańszy | Własna infrastruktura botów, ryzyko o 4 rano | Po hackathonie, dla marży |
| [joinly](https://llmbase.ai/mcp-servers/joinly/) (open source) | Darmowy, mówi przez ElevenLabs i pisze na czacie | Własny hosting przeglądarek | Plan B |
| Meeting BaaS / MeetStream / Skribby | $0.35–0.69/h | Nie sprawdzaliśmy, czy ich boty mówią w rozmowie | Nie |
| Własny bot na Selenium + PulseAudio ([tutorial](https://noqta.tn/en/tutorials/elevenlabs-voice-agent-google-meet-python-2026)) | Pełna kontrola | Godziny konfiguracji audio, tylko Meet | Nie |

## Głos: ElevenLabs w rozmowie i w aplikacji

W rozmowie agent mówi tylko wtedy, gdy ktoś zwraca się do niego po imieniu „Crew”: backend łapie zwrot w transkrypcie, przygotowuje odpowiedź i oddaje ją głosem ElevenLabs TTS. Pełnego agenta głosowego ElevenLabs używamy w aplikacji mobilnej, gdzie rozmowa jest jeden na jeden (opcjonalnie).

Dlaczego nie pełny agent w rozmowie: dźwięk wszystkich uczestników przychodzi na stronę jako jeden mikrofon. Pełny agent odpowiadałby na każdą wypowiedź i przerywał ludziom. Pipeline oparty na zwrocie po imieniu jest przewidywalny: agent milczy, dopóki ktoś go nie zawoła.

Co się dzieje, gdy ktoś woła agenta:

1. Recall wysyła `transcript.data` (kto mówił, tekst, czas) na `/webhooks/recall/transcript`.
2. Orkiestrator szuka imienia „Atlas” (aliasy: atlas, hey/okay atlas, atlass, atlis; „at last” tylko na początku) w pierwszych 6 słowach wypowiedzi; pytanie = tekst po imieniu. (Zmiana z „Crew” po teście na żywo, decyzja 27.)
3. Zbiera kontekst: ostatnie 2 minuty transkryptu, brief właściciela, 6 najbliższych fragmentów bazy wiedzy (pgvector; do M4 dokumenty idą wprost do promptu).
4. LLM OpenAI zwraca JSON: `{answer, confidence, needs_expert, topic}`.
5. Jeśli `needs_expert = true` albo `confidence < 0.6`, startuje eskalacja, a agent mówi „I don’t know, asking Dima now”.
6. Tekst idzie do ElevenLabs TTS, audio przez WebSocket na stronę agenta. Strona je odtwarza i dźwięk trafia do rozmowy.
7. Gdy agent mówi, strona wysyła `speaking=true`, żeby orkiestrator nie reagował na słowa samego agenta w transkrypcie.

Cel: 3–5 sekund od końca pytania do głosu. Transkrypt Recall to 1–3 sekundy; LLM i TTS to nasza ocena, zmierzyć przy pierwszym przebiegu. Jeśli wychodzi dłużej, od razu gramy nagrane wcześniej „One sec…”.

**Strona agenta (`/agent`)** to „kamera” bota w rozmowie:

- Jeden statyczny plik HTML + vanilla JS, serwowany przez FastAPI, bez kroku build. Otwiera go bot Recall.
- Łączy się z `wss://<host>/agent-page/ws?meeting_id=…&token=…`.
- Dostaje `{type: "say", audio_b64, text}`, odtwarza mp3 i pokazuje logo Call Crew z napisem.
- Mikrofon strony w MVP nie jest potrzebny: słuchamy przez transkrypt Recall.

**Jeśli zostanie czas:** pełny ElevenLabs Agent na stronie przez `Conversation.startSession` z `@elevenlabs/client`. Odpowiedź eksperta przekazujemy przez `sendUserMessage` (agent od razu mówi) albo `sendContextualUpdate` (uwzględnia bez wypowiedzi) ([JS SDK](https://elevenlabs.io/docs/agents-platform/libraries/javascript)). Ryzyko przerywania zostaje, więc dopiero po stabilnym MVP.

**Głos w aplikacji mobilnej:**

- MVP: czat tekstowy + przycisk „Odsłuchaj” (ElevenLabs TTS odpowiedzi).
- Jeśli zostanie czas: tryb głosowy przez ElevenLabs Agent z server tool `search_meetings`, który wywołuje nasz backend ([jak działają server tools](https://surrealdb.com/docs/agent-memory/integrations/voice/elevenlabs)). We Flutterze przez WebView z JS SDK; natywnego SDK dla Fluttera nie sprawdzaliśmy.

Głos agenta: neutralny głos z biblioteki ElevenLabs. Klon głosu Artema dla delegata (jego własny, za zgodą) dałby mocny efekt wow, ale jury może to odebrać jako deepfake. Decyzja przed próbą generalną.

## Dane: gdzie żyją rozmowy, fakty i baza wiedzy

Jedna baza: Supabase (Postgres + pgvector). Bez osobnej bazy wektorowej: na hackathonie mniej serwisów = mniej punktów awarii. Dostęp z backendu przez asyncpg (`DATABASE_URL`), migracje to zwykłe pliki SQL. Embeddingi: OpenAI `text-embedding-3-small`, 1536 wymiarów.

| Tabela | Co przechowuje | Kluczowe pola |
| --- | --- | --- |
| `users` | właściciel agenta | id, name, email, slack\_user\_id, telegram\_chat\_id |
| `experts` | do kogo eskalujemy | id, name, role, topics\[\], channel (slack / telegram), email, slack\_user\_id, telegram\_chat\_id |
| `meetings` | jedna rozmowa | id, owner\_id, title, platform, meeting\_url, recall\_bot\_id, mode (notes / delegate), status, started\_at, ended\_at, summary, decisions jsonb, action\_items jsonb |
| `utterances` | wypowiedź z transkryptu | id, meeting\_id, speaker, text, ts\_start, ts\_end, embedding |
| `kb_docs` | dokument bazy wiedzy | id, title, source, version, updated\_at |
| `kb_chunks` | fragment dokumentu | id, doc\_id, text, embedding, version |
| `facts` | fakt wyciągnięty z rozmowy | id, meeting\_id, speaker, text, kind (decision / number / date / owner), embedding |
| `fact_checks` | sprawdzenie twierdzenia | id, meeting\_id, utterance\_id, claim, verdict, kb\_chunk\_id, confidence, posted bool |
| `kb_update_proposals` | propozycja zmiany bazy | id, meeting\_id, doc\_id, chunk\_id, old\_text, new\_text, speaker, ts, status (pending / approved / rejected) |
| `briefs` | brief dla delegata | id, meeting\_id, text, open\_questions\[\] |
| `escalations` | pytanie do eksperta | id, meeting\_id, expert\_id, channel, question, external\_msg\_id (Slack `ts` / Telegram `message_id`), external\_channel\_id, answer, status, asked\_at, answered\_at |
| `chat_messages` | czat w aplikacji | id, user\_id, role, text, citations jsonb |

**Podział bazy wiedzy:** fragmenty po 500–800 tokenów z nakładaniem \~80, top-k = 6 po podobieństwie cosinusowym. Wyszukiwanie w rozmowach idzie i po `utterances`, i po `facts`. Fakty są krótsze i dokładniejsze, więc przy pytaniach „co X powiedział o Y” dają lepszy wynik.

**W trakcie rozmowy** (każdy `transcript.data`):

- Zapisujemy wypowiedź w `utterances` od razu; embedding liczymy partiami co 10 sekund.
- Zwrot po imieniu agenta → orkiestrator (sekcja „Głos”).
- Kandydat na twierdzenie → fact-check (następna sekcja).

**Po rozmowie** (webhook Recall o zakończeniu bota; dokładna nazwa eventu: **do weryfikacji**):

1. Zbieramy pełny transkrypt z `utterances`.
2. Jedno wywołanie LLM zwraca JSON: summary, decisions, action\_items (kto / co / do kiedy), facts.
3. Fakty zapisujemy w `facts` z embeddingami; decyzje sprzeczne z bazą stają się `kb_update_proposals`.
4. Zdarzenie `meeting_ended` do aplikacji: „Podsumowanie rozmowy gotowe”.

**Dane demo dla firmy „Acme”** (`backend/seed/`, ładuje `scripts/seed_kb.py`):

- `api.md` — limit API 50 rps, autoryzacja, endpointy. Na tym fakcie opiera się demo fact-checku.
- `roadmap.md` — funkcje Q4, kto odpowiada, deadline'y.
- `team.md` — kto za co odpowiada (Dima: backend i infra, jego email do Slacka). Z tej tabeli agent wybiera, do kogo eskalować.
- 2 zapisy przeszłych rozmów, żeby historia w aplikacji nie była pusta.

## Fact-check i aktualizacja bazy na żywo

Agent sprawdza tylko twierdzenia, które da się porównać z bazą: liczby, daty, limity, kto za co odpowiada. Na czacie rozmowy pisze tylko wtedy, gdy jest pewny. Na demo fałszywa poprawka jest gorsza niż pominięta.

**Pipeline dla każdej wypowiedzi:**

1. **Filtr (za darmo):** regex na liczby, daty, jednostki (rps, %, ms, $) i imiona z `team.md`. Brak trafienia → pomijamy.
2. **Ekstrakcja twierdzenia:** tani model zwraca `{claim, entity, value}` albo `null`.
3. **Wyszukiwanie:** top-6 fragmentów z `kb_chunks` plus świeże `facts` z przeszłych rozmów.
4. **Sędzia:** LLM zwraca `{verdict: supported / contradicted / change / unknown, confidence, source_chunk_id, correction}`.
5. **Wiadomość na czacie rozmowy** tylko przy `contradicted` i `confidence ≥ 0.8`, nie częściej niż raz na 60 sekund. Tekst: „Heads-up: api.md says the rate limit is 50 rps, not 100 (updated 12 Oct)”. Wysyłka przez endpoint czatu Recall (ścieżka: **do weryfikacji**).
6. Wszystkie sprawdzenia, nawet ciche, zapisujemy w `fact_checks`. Po rozmowie w aplikacji widać, co agent sprawdził i co znalazł.

Głosem agent poprawia tylko w trybie delegata i tylko gdy ktoś go zapyta. Nie wolno przerywać ludziom głosem.

**Aktualizacja bazy na żywo.** Gdy w rozmowie zapada decyzja sprzeczna z bazą („od poniedziałku podnosimy limit do 100 rps”), to nie błąd, tylko zmiana:

- Sędzia zwraca `verdict = change` (osobna klasa: mówca mówi o przyszłości albo o decyzji).
- Powstaje `kb_update_proposals`: stary tekst, nowy tekst, kto powiedział, timecode.
- Na czacie rozmowy: „Noted: rate limit → 100 rps from Monday. I’ll propose an update to api.md”.
- W aplikacji właściciel widzi kartę „Zaktualizować api.md?” z przyciskami Approve / Reject.
- Approve zmienia tekst fragmentu, przelicza jego embedding i podnosi `version`. Następne sprawdzenie porównuje już z nową wartością.

Bazy nie zmieniamy automatycznie bez potwierdzenia człowieka: jeden błąd rozpoznawania zamieniłby 50 na 15 w dokumentacji.

Koszt: filtr odrzuca większość wypowiedzi, więc LLM jest wywoływany na małej części. Na demo nie podajemy liczb, dopóki ich nie zmierzymy.

## Eskalacja na Slacku — główna funkcja

W trybie delegata agent nie wymyśla odpowiedzi. Jeśli nie wie, pyta człowieka na Slacku i przynosi odpowiedź z powrotem do tej samej rozmowy. Tego nie ma w Otterze ani we wbudowanych asystentach, więc ten przepływ musi działać bezbłędnie.

Dlaczego Slack, a nie Telegram czy WhatsApp: pracownicy firm i tak siedzą cały dzień w Slacku albo Teamsie, a firmy nie chcą, żeby dane służbowe szły przez prywatne komunikatory. WhatsApp Business API (konto biznesowe Meta, numer testowy, szablony wiadomości) to za dużo na jedną noc.

**Przepływ:**

1. Ktoś w rozmowie pyta agenta. Orkiestrator dostaje od LLM `needs_expert = true` i `topic` (np. infra).
2. Wybór eksperta: dopasowanie `topic` do `experts.topics[]`. Brak dopasowania → eskalacja do właściciela agenta.
3. Agent mówi: „Good question — I don’t have that. I’m asking Dima on Slack right now, give me a minute.”
4. Backend przez `Notifier` (adapter Slack): `users.lookupByEmail` → `conversations.open` → `chat.postMessage` w DM. W wiadomości: nazwa rozmowy, kto pytał, samo pytanie, 3 ostatnie wypowiedzi jako kontekst, prośba „odpowiedz w wątku”. `ts` i kanał zapisujemy w `escalations.external_msg_id` / `external_channel_id`.
5. Ekspert odpowiada w wątku. Slack wysyła event `message` z `thread_ts` na `/webhooks/slack`; po `thread_ts` znajdujemy eskalację.
6. Jeśli rozmowa trwa: TTS „Dima says: …” → WebSocket → strona agenta, i ten sam tekst na czacie rozmowy. Odpowiedź zapisujemy jako `fact` z autorem „Dima”. Zdarzenia WS: `escalation_created`, `escalation_answered`.
7. Po 2 minutach bez odpowiedzi agent mówi: „Dima hasn’t answered yet — I’ve added it to follow-ups.” Pytanie staje się action item. Późna odpowiedź trafia do podsumowania rozmowy.

**Konfiguracja Slack app (~30–45 minut):**

- api.slack.com → Create App → bot token scopes: `chat:write`, `im:write`, `im:history`, `users:read.email`; instalacja w workspace → `SLACK_BOT_TOKEN`; `SLACK_SIGNING_SECRET`.
- Event Subscriptions: Request URL `https://<host>/webhooks/slack` (musi odpowiedzieć na `url_verification` challenge), event `message.im`.
- Backend weryfikuje podpis (`X-Slack-Signature`, `X-Slack-Request-Timestamp`) i odpowiada 200 od razu.
- Ignorujemy wiadomości samego bota (`bot_id`), żeby nie złapać własnej wiadomości jako odpowiedzi.
- Bot pisze pierwszy bez dodatkowych kroków po stronie eksperta: wystarczy, że ekspert jest w workspace. Na demo „Dima” (Julian albo Rem) ma Slacka na telefonie.

**Telegram jako zapasowy adapter** (jeśli Slack nie zadziała): `sendMessage` z `reply_markup: {force_reply: true}`, odpowiedź przez `/webhooks/telegram` (dopasowanie po `reply_to_message.message_id`), `setWebhook` z `secret_token` i weryfikacją nagłówka `X-Telegram-Bot-Api-Secret-Token`. Bot Telegrama nie może pisać pierwszy: ekspert raz otwiera deep link `t.me/<bot>?start=<expert_id>`, a my zapisujemy jego `chat_id`.

**Brief delegata.** Przed rozmową właściciel w aplikacji pisze 2–3 zdania: co zrobione, co blokuje, na co się nie zgadzać. Brief zawsze siedzi w promptcie systemowym orkiestratora. Reguła w promptcie: nigdy nie składać zobowiązań ani deadline'ów w imieniu właściciela, tylko wysyłać takie pytania jemu.

**W pitchu:** „agent pyta tam, gdzie pracuje Twój zespół”. Teams i WhatsApp to kolejne adaptery `Notifier` bez zmian w rdzeniu.

**Jeśli zostanie czas:** przycisk „Odpowiedz” w Block Kit otwierający modal; odpowiedź głosowa eksperta (rozpoznawanie przez OpenAI); przyciski „Nie wiem / Zapytaj X”.

## Aplikacja mobilna: ekrany i skąd biorą dane

Kolejność: Misza robi teraz makietę, Artem najpierw kończy i testuje backend, potem razem budujemy aplikację według makiety. Kontrakt API (`docs/API.pl.md` + `mocks/*.json`) powstaje na samym początku, więc aplikację można zacząć od razu po makiecie, a przejście z mocków na prawdziwy backend to zmiana `BASE_URL`.

| # | Ekran | Co na nim jest | API |
| --- | --- | --- | --- |
| 1 | Rozmowy | lista: nazwa, data, platforma, tryb, znaczek LIVE; przycisk „+” | `GET /meetings` |
| 2 | Nowa rozmowa | pole na link, przełącznik Notatnik / Delegat, pole briefu (dla delegata) | `POST /meetings` |
| 3 | Live | transkrypt na żywo, karty zdarzeń: fact-check, eskalacja (czekamy / odpowiedział), przycisk „Wyjdź” | `WS /app/ws?meeting_id=`, `POST /meetings/{id}/leave` |
| 4 | Szczegóły rozmowy | podsumowanie, decyzje, action items, fact-checki, pełny transkrypt | `GET /meetings/{id}` |
| 5 | Czat z agentem | pytania o wszystkie rozmowy i bazę; odpowiedź z cytatami (rozmowa + timecode albo dokument); przycisk „Odsłuchaj” | `POST /chat`, `POST /tts` |
| 6 | Baza wiedzy | dokumenty z wersjami; karty propozycji zmian z Approve / Reject | `GET /kb/docs`, `GET /kb/proposals`, `POST /kb/proposals/{id}/approve` |

Aplikacja dostaje dane dwiema drogami:

- **REST** — listy i szczegóły.
- **Jeden WebSocket** — ekran Live. Zdarzenia: `utterance`, `fact_check`, `escalation_created`, `escalation_answered`, `agent_said`, `meeting_ended`. Jeśli WS nie zdążymy, odpytywanie `GET /meetings/{id}?since=<ts>` co 2 sekundy.

Autoryzacja w MVP: jeden użytkownik demo i statyczny token w nagłówku `Authorization: Bearer <DEMO_TOKEN>`. Logowanie przez Supabase Auth po hackathonie.

**Mock dla ekranu 4** (`GET /meetings/{id}`):

```json
{
  "id": "m_01",
  "title": "Q4 API sync",
  "platform": "google_meet",
  "mode": "delegate",
  "status": "done",
  "started_at": "2026-10-31T09:00:00Z",
  "duration_min": 23,
  "summary": "Team agreed to raise the API limit to 100 rps from Monday.",
  "decisions": ["Rate limit -> 100 rps from Monday (owner: Dima)"],
  "action_items": [{"owner": "Artem", "text": "Update SDK docs", "due": "2026-11-03"}],
  "fact_checks": [{"claim": "limit is 100 rps", "verdict": "contradicted", "source": "api.md", "correction": "50 rps", "ts": 312}],
  "escalations": [{"expert": "Dima", "channel": "slack", "question": "Can we cache auth tokens?", "answer": "Yes, 15 min TTL", "status": "answered"}],
  "utterances": [{"speaker": "Julian", "text": "Crew, what is our API limit?", "ts": 305}]
}
```

**Czat (ekran 5)** działa jako RAG po `facts`, `utterances` i `kb_chunks` właściciela. W odpowiedzi zawsze są `citations: [{meeting_id, ts, speaker}]` (albo dokument); tapnięcie w cytat otwiera rozmowę na właściwej wypowiedzi. To odróżnia nas od zwykłego czatu z LLM: każda odpowiedź ma sprawdzalne źródło.

## Backend: API, infrastruktura, zmienne

Jeden serwis FastAPI w jednym procesie. Hub WebSocketów trzymamy w pamięci, to wystarcza dla jednej instancji. Długie zadania (podsumowanie, embeddingi) odpalamy przez `asyncio.create_task`, bez kolejki. Wszystkie webhooki odpowiadają 200 od razu, a przetwarzają asynchronicznie.

| Metoda i ścieżka | Kto wywołuje | Co robi |
| --- | --- | --- |
| `POST /meetings` | aplikacja | `{meeting_url, mode, brief?, title?}` → tworzy rekord, wywołuje Recall `POST /bot/`, zwraca `{id, status: joining}` |
| `GET /meetings` | aplikacja | lista rozmów właściciela |
| `GET /meetings/{id}` | aplikacja | szczegóły (format jak mock wyżej), `?since=` do odpytywania |
| `POST /meetings/{id}/leave` | aplikacja | Recall `leave_call`, uruchamia podsumowanie |
| `POST /chat` | aplikacja | `{question}` → RAG → `{answer, citations}` |
| `POST /tts` | aplikacja | `{text}` → `audio/mpeg` z ElevenLabs |
| `GET /kb/docs`, `POST /kb/docs` | aplikacja, seed | lista dokumentów; upload .md → podział i embeddingi |
| `GET /kb/proposals`, `POST /kb/proposals/{id}/approve` albo `/reject` | aplikacja | propozycje zmian bazy |
| `WS /app/ws?meeting_id=` | aplikacja | zdarzenia rozmowy na żywo |
| `POST /webhooks/recall/transcript?meeting_id=&token=` | Recall | `transcript.data` → utterances, zwrot po imieniu, fact-check |
| `POST /webhooks/recall/status` | Recall | status bota (joining, in\_call, done; nazwy do weryfikacji) |
| `POST /webhooks/slack` | Slack | `url_verification`, odpowiedzi ekspertów w wątkach |
| `POST /webhooks/telegram` | Telegram | zapasowo: odpowiedzi ekspertów, `/start` |
| `GET /agent` | bot Recall | statyczna strona agenta |
| `WS /agent-page/ws?meeting_id=&token=` | strona agenta | audio do odtworzenia, flaga `speaking` |
| `GET /health` | Railway | healthcheck |

**Gdzie to działa:**

- **Backend** — Railway (region EU) z publicznym HTTPS od pierwszej godziny. Recall potrzebuje publicznego adresu i dla webhooków, i dla strony agenta. Lokalnie ngrok.
- **Baza** — Supabase (free tier, region EU), włączyć rozszerzenie `vector`.
- **Strona agenta** — statyczny plik serwowany przez ten sam FastAPI.
- **Aplikacja** — Flutter na telefonie Miszy, na demo mirroring ekranu.

**Struktura repo:**

```
backend/app/main.py           # FastAPI, routery, hub WS
backend/app/config.py         # pydantic-settings
backend/app/db.py             # pula asyncpg, zapytania
backend/app/recall.py         # tworzenie bota, wyjście, czat rozmowy
backend/app/orchestrator.py   # zwrot po imieniu, kontekst, LLM, decyzja o eskalacji
backend/app/factcheck.py      # filtr, sędzia, propozycje zmian
backend/app/rag.py            # embeddingi, wyszukiwanie w pgvector
backend/app/notifier/         # base.py (interfejs), slack.py, telegram.py
backend/app/escalation.py     # pętla eskalacji, timeout
backend/app/tts.py            # ElevenLabs
backend/app/postcall.py       # podsumowanie, fakty, action items
backend/migrations/           # *.sql
backend/seed/                 # api.md, roadmap.md, team.md, przeszłe rozmowy
backend/tests/                # pytest + fixtures webhooków
agent-page/index.html         # odtwarzacz audio + logo
scripts/                      # migrate.py, seed_kb.py, simulate_meeting.py
docs/                         # SPEC.pl.md, API.pl.md
mocks/                        # JSON dla aplikacji
mobile/                       # Flutter (później)
```

**Zmienne środowiskowe:** `RECALL_API_KEY`, `RECALL_BASE_URL` (`https://eu-central-1.recall.ai`, zapasowo `https://us-west-2.recall.ai`), `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`, `OPENAI_EMBED_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `DATABASE_URL`, `PUBLIC_BASE_URL`, `DEMO_TOKEN`, `WEBHOOK_TOKEN`.

Wszystkie webhooki i WS sprawdzają token (Slack: podpis). Bez tego każdy, kto zna URL, może kazać agentowi mówić w rozmowie.

**Testowanie backendu bez aplikacji:**

- `pytest` — jednostkowo: zwrot po imieniu i aliasy, filtr fact-checku, dopasowanie eksperta, dopasowanie odpowiedzi Slacka do eskalacji (respx mockuje HTTP).
- `scripts/simulate_meeting.py` — odtwarza transkrypt scenariusza demo z fixture jako webhooki Recall na lokalny backend; widać odpowiedzi orkiestratora, eskalację i fact-check bez prawdziwej rozmowy.
- curl na endpointy aplikacji + `websocat` na `/app/ws`.
- Na końcu prawdziwa rozmowa w Google Meet.

## Plan do freeze o 11:00

Najpierw cały backend, testowany bez aplikacji; równolegle Misza robi makietę. Kolejność wyznacza główna funkcja: agent w rozmowie → głos → eskalacja. Fact-check idzie po nich i jest cięty jako pierwszy. Do M4 baza wiedzy idzie wprost do promptu (3 małe pliki), pgvector podłączamy później.

**M0 · 01:45–02:30 · Fundament**

- [ ] Szkielet repo backendu: uv, FastAPI, `/health`, config, ruff, pytest, `.env.example`, README.
- [ ] Kontrakt API: `docs/API.pl.md` + `mocks/*.json` (dla makiety Miszy).
- [ ] Migracje Supabase (wszystkie tabele + `vector`).
- [ ] Deploy na Railway (EU), `PUBLIC_BASE_URL`.

**M1 · 02:30–03:30 · Agent w rozmowie**

- [ ] Klient Recall, `POST /meetings`, `POST /meetings/{id}/leave`; bot wchodzi do Google Meet.
- [ ] Webhook transkryptu → `utterances`, deduplikacja, zdarzenie WS.
- [ ] Webhook statusu bota.
- [ ] `scripts/simulate_meeting.py` + fixture scenariusza demo.

**M2 · 03:30–05:00 · Agent mówi**

- [ ] Strona agenta + WS; testowa fraza słychać w rozmowie.
- [ ] TTS ElevenLabs + `POST /tts` + „One sec…” w cache.
- [ ] Orkiestrator: „Crew” → LLM (brief + dokumenty w promptcie) → głos. Zmierzyć latencję.
- [ ] Brief delegata.

**M3 · 05:00–06:30 · Eskalacja na Slacku (główna funkcja)**

- [ ] Interfejs `Notifier` + wybór eksperta.
- [ ] Adapter Slack + `/webhooks/slack`.
- [ ] Pętla eskalacji end-to-end, timeout 2 min → action item.
- [ ] Adapter Telegram (zapasowy, P2).
- [ ] 06:15: pierwszy przebieg demo end-to-end. To minimalny produkt, z którym można iść na pitch.

**M4 · 06:30–07:30 · Pamięć i czat**

- [ ] RAG: `POST /kb/docs`, seed Acme, orkiestrator na pgvector.
- [ ] Pipeline po rozmowie.
- [ ] `GET /meetings`, `GET /meetings/{id}`, `POST /chat` z cytatami.

**M5 · 07:30–08:00 · Fact-check (cięty jako pierwszy)**

- [ ] Fact-check na żywo + wiadomość na czacie rozmowy.
- [ ] Propozycje zmian bazy + approve / reject.

**M6 · 08:00–08:30 · Stabilizacja i demo**

- [ ] `/app/ws` komplet zdarzeń, tokeny, CORS.
- [ ] 3 przebiegi scenariusza 90 s na prawdziwym Meet, pomiar latencji, nagranie zapasowego wideo do 09:30.

**Mobile · od makiety do ~10:30**

- [ ] Ekrany według makiety Miszy na mockach, potem przełączenie na prawdziwy `BASE_URL`. Szczegółowe zadania po makiecie.
- [ ] Slajdy: problem, demo, dlaczego nie Otter, pieniądze. 11:00 freeze.

**Reguła cięcia:** jeśli o 06:30 eskalacja nie działa end-to-end, M5 wypada z planu. Po 08:30 tylko poprawki błędów. Ryzyko: jeśli backend potrwa do ~08:30, na aplikację zostają ~2 godziny, dlatego kontrakt API i mocki są w M0, a aplikację można zacząć równolegle zaraz po makiecie.

## Ryzyka i źródła

| Ryzyko | Co robimy |
| --- | --- |
| Bot utknął w poczekalni Meet | Host demo to nasze konto, wpuszczamy ręcznie; ustawić timeout oczekiwania; sprawdzić już w M1 |
| Zoom i Teams zachowują się inaczej | Demo tylko w Google Meet; o Zoomie i Teamsie mówimy „to samo API”, na scenie nie pokazujemy |
| Odpowiedź dłuższa niż 5 sekund | Od razu gramy nagrane wcześniej „One sec…”, gdy generuje się odpowiedź; zmierzyć w M2 |
| Rozpoznawanie nie usłyszało „Crew” | Aliasy imienia + przycisk „Ask agent” na ekranie Live jako zapasowy wyzwalacz dla ostatniego pytania |
| Agent reaguje na własny głos | Flaga `speaking` + ignorujemy wypowiedzi uczestnika o nazwie bota |
| Webhooki Recall padają przez timeout | Odpowiadać 200 od razu, przetwarzać asynchronicznie: inaczej Recall powtarza zapytanie i dostajemy duplikaty ([dokumentacja](https://docs.recall.ai/reference-link/real-time-transcription)) |
| LLM wymyśla odpowiedź zamiast eskalacji | Prompt „odpowiadaj tylko z kontekstu”, próg 0.6, 5 testowych pytań ze scenariusza przed demo |
| „Dima” nie zdąży odpowiedzieć na scenie | Przećwiczona odpowiedź w schowku jego telefonu |
| Slack nie zadziała (scopes, eventy) | Zapasowy adapter Telegram za tym samym `Notifier` |
| Wi-Fi na miejscu | Hotspot z telefonu + zapasowe wideo do 09:30 |
| Skończyły się kredyty Recall albo ElevenLabs | Sprawdzić saldo o 08:30. Limit znaków darmowego planu ElevenLabs — nie sprawdzaliśmy |
| Szybki transkrypt tylko po angielsku | Demo po angielsku ([dokumentacja](https://docs.recall.ai/reference-link/recallai-transcription)) |
| Ścieżka wysyłki na czat rozmowy | Funkcja w Recall jest; dokładną ścieżkę i pola sprawdzić w API reference przed M5 |
| Zgoda na nagrywanie | Nazwa bota zawiera „(AI)”, na starcie agent pisze na czacie, że robi notatki |

**Do weryfikacji (zebrane):** ścieżka endpointu czatu rozmowy w Recall; nazwy eventów statusu bota w Recall; aktualny model OpenAI do `OPENAI_CHAT_MODEL`; aktualny model ElevenLabs do `ELEVENLABS_MODEL_ID`; czy Recall przyjmuje `output_media` i `recording_config` w jednym zapytaniu.

**Źródła**

- [Recall.ai — Send AI Agents to Meetings (Output Media)](https://docs.recall.ai/docs/stream-media)
- [Recall.ai — Output Media endpoint](https://docs.recall.ai/reference-link/bot_output_media_create)
- [Recall.ai — Real-time transcription](https://docs.recall.ai/reference-link/real-time-transcription)
- [Recall.ai — Recall.ai Transcription (tryby, cena, języki)](https://docs.recall.ai/reference-link/recallai-transcription)
- [Recall.ai — Regiony](https://docs.recall.ai/docs/regions)
- [Recall.ai — Cennik](https://www.recall.ai/pricing)
- [ElevenLabs — Agents JavaScript SDK](https://elevenlabs.io/docs/agents-platform/libraries/javascript)
- [Slack API](https://api.slack.com/apis)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Supabase — pgvector](https://supabase.com/docs/guides/database/extensions/pgvector)
