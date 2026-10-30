# The app is endpoint-only and built new

The app never runs models in-process. It sends audio and text to model servers only through configurable endpoints, so the same app works with small models on the laptop and with large models on a remote GPU machine. Because of this, we build the app new and fork no existing project. The nearest candidates either embed the models (WhisperLiveKit, WhisperLive) or diarize only after the recording ends and need heavy server infrastructure (Reflector). None of them captures several sources onto one timeline with one column per speaker.

## Considered Options

- **Fork WhisperLiveKit**: it streams ASR, diarization and translation, but the models run inside its process and its UI is one text stream. We use it as an endpoint instead.
- **Fork Reflector**: it has the same stack and per-service model URLs, but its live pipeline has no diarization, its input is browser WebRTC (not PipeWire), and it needs Postgres, Redis, Celery and S3. We study its design and do not fork it.

## Consequences

- If no existing server can serve a model that we need, this project can include its own small endpoint server in `endpoints/`. The app still talks to it only through the endpoint contract.
- "Models" here means the audio and translation models (ASR, diarization, translation). A small CPU-only text language identifier (for example statistical n-grams) may run inside the app, because no tested endpoint returns the language of a segment. Decided in [Choose the ASR and diarization combination for each hardware level](https://github.com/gdevenyi/live-transcribe-translate/issues/10).
- One ASR stack serves every endpoint: NeMo-Speech.cpp with Nemotron 3.5 ASR Streaming and Nemotron 3 Diarization, over its realtime WebSocket. It is the only tested model that streams with speaker labels in one session, and it runs in real time on every GPU we measured. By default it runs locally next to the app; the user can configure an alternative endpoint URL. The app has no machine-specific profiles, and does not split text and speakers across endpoints (Voxtral and Kyutai had better French, but would need that split). Decided in [Choose the remote ASR model](https://github.com/gdevenyi/live-transcribe-translate/issues/19).
- We copy code only from projects that use a licence compatible with Apache-2.0 (for example MIT or Apache-2.0), with attribution. We never copy code from GPL or AGPL projects.
