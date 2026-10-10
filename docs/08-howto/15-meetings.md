# How to send a bot to a meeting

> A meeting is an agent execution surface. The bot joins a LiveKit room as your representative, answers only on the topics you allow, hands the rest back to you and declines everything else. Rehearse it first with typed turns, then run it live.

Pages: **Meetings** in the sidebar (`/meetings`, needs the `use_meetings` feature), a meeting at `/meetings/{id}`, its rehearsal at `/meetings/{id}/rehearse` and the browser join page at `/meetings/{id}/join`. The API is [`apps/api/app/routers/meetings.py`](../../apps/api/app/routers/meetings.py). LiveKit is the only working room provider. The Teams and Zoom adapters are stubs.

---

## What needs which keys

| You want to | You need |
|---|---|
| Create a meeting, set its scope, rehearse | Nothing beyond a model key for the agent. Rehearsal also needs Redis, which every install has |
| Run the bot live and join the room yourself | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` under Admin, Tool configuration |
| The bot hears speech | `OPENAI_API_KEY` for speech to text. Without it the bot still reads the room chat and the decision log says why it cannot hear |
| The bot speaks aloud | `OPENAI_API_KEY` or `ELEVENLABS_API_KEY`. Without them it posts its replies in the room chat |

The meetings pages show a banner for anything missing. `GET /api/meetings/readiness` returns the same as booleans.

---

## 1. Create and scope

1. Open **Meetings**, press **New meeting**, give it a title.
2. Under **Bot scope** press **Edit**.
   - **Answers on** lists the topics the bot may speak to. At least one is needed before it can start.
   - **Always hands back** lists topics it must hand to you. Commitments, deadlines, pricing and approvals are always handed back, even on an allowed topic.
   - **Persona knowledge it may use** lists the persona scopes `persona_rag` may search. `self` is always allowed.
3. Anything outside both lists is declined politely.

The scope check runs in code. `meeting_listen` tags every question aimed at the bot with `scope` (answer, defer or decline) and logs the decision, so the ring-fence holds even when the model skips calling `scope_gate`.

---

## 2. Rehearse

Press **Rehearse** on the meeting. It needs at least one topic under **Answers on**, and it is refused while the bot is in the live meeting. The rehearsal page runs the meeting's own agent with the same tools, prompt and scope as live. Only the room is swapped for a rehearsal adapter.

- Type what a participant says, or dictate it with the mic. Dictation uses the browser's own speech recognition, so it costs nothing.
- Each turn shows the scope decision, the persona notes cited, any question handed back to you and how long the reply took.
- A question handed back waits 30 seconds for your answer, as it does live. Answer it in place or let it time out and see the fallback.
- No room is joined and no voice is synthesised. The agent's model calls are spent as usual.
- The real meeting is untouched. Its status stays as it was and its transcript stays empty.

How it works. `POST /api/meetings/{id}/rehearsal` writes the meeting's scope under a `rehearsal-<id>` key with provider `rehearsal` and starts the same `_run_meeting_agent` the live start uses. `meeting_join` picks the `RehearsalAdapter`, which reads typed turns from the Redis list `meeting:<rehearsal-id>:rehearsal:turns` and feeds them to `meeting_listen` as chat. `meeting_speak` sees a simulated adapter and skips TTS. Everything else is the live code path.

---

## 3. Run it live

1. Press **Join the room** to join from this browser. Your mic stays off until you turn it on. **Join from another LiveKit app instead** gives a server URL and token for any other client. Both come from `GET /api/meetings/livekit-token`, which mints a one hour token for you. Set `LIVEKIT_PUBLIC_URL` when the browser reaches LiveKit at a different address than the API pod does.
2. On the meeting page press **Start bot**. It shows up in the participant list on both pages within a few seconds and posts a consent notice in the room chat.
3. Ask it something by voice or in the room chat. The meeting page polls every 2 seconds and shows the transcript with the bot's replies and their latency, plus what the bot did step by step.
4. Questions it hands back show under **The bot is waiting on you**.
5. The bot runs inside the API process. If that process restarts mid-meeting, the meeting page notices the bot is gone from the room and offers **Restart bot**.
6. **End meeting** asks the bot to say goodbye, write a summary and leave. The transcript, decision log and summary are copied onto the meeting row, so they outlive Redis. **Remove bot now** kicks it out without a summary.

---

## 4. The end to end test

`e2e/uat_meetings_ui.spec.ts` runs the whole thing through the screens.

- It adds a persona note, creates and scopes a meeting, then rehearses an in-scope question with a citation, an off-topic question that is declined and a pricing question that is handed back and answered.
- For the live part it launches a second Chromium with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>%noloop`, joins the room from the product's join page, starts the bot from the meeting page and waits for it in the participant list. The fake mic asks about the roadmap, then 25 seconds later asks about football.
- When a live piece cannot work, the test asserts the product's own explanation and records what was not verified as a test annotation. No LiveKit keys, no speech to text key and LiveKit not reachable from the test machine are all handled.

The wav is `e2e/fixtures/meetings/question.wav`. Rebuild it offline on Windows with

```
powershell -ExecutionPolicy Bypass -File e2e/fixtures/meetings/make-question-wav.ps1
```

On Linux or macOS any 16 kHz mono wav with the same two questions works, for example from `espeak-ng -w` or `say -o`.

```
BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_meetings_ui.spec.ts --workers=1
```
