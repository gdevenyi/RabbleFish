# Research: Survey of existing live transcription software

Ticket: [#2](https://github.com/gdevenyi/live-transcribe-translate/issues/2) (parent map: #1)
Date of research: 2026-10-29

## Question

Which existing projects are near to the destination (live capture on Linux,
streaming ASR, diarization, translation, web UI with speakers)? For each:
features compared to the destination, licence, activity, stack, endpoint or
model flexibility, and whether a fork or extension is practical.

Destination, in short: a Linux/PipeWire app that captures one or more Sources
(mic and sink monitors), sends audio to configurable inference Endpoints (the
app never runs models in-process), and shows a web Timeline with one Column
per Speaker (at least 8), language switch detection, optional Translation into
one Target language, continuous save, and Markdown/JSON export. Latency target
2-5 s for finalized Segments. Stack: Python (uv) backend, TypeScript (pnpm)
frontend, WebSocket.

## Short answer

1. **No existing project is the destination.** No project captures several
   PipeWire Sources, keeps them on one Timeline, and shows one Column per
   Speaker. Every candidate shows a single text stream with speaker labels
   inline, or is a batch (file) tool. Build our own app.
2. **Split the problem in two.** Each candidate is either an *app candidate*
   (session logic, UI, storage) or an *endpoint candidate* (a server that runs
   models behind a network API). Our destination is an app that talks to
   endpoints. So we reuse endpoint servers and copy ideas from apps.
3. **Best endpoint server to adopt first: WhisperLiveKit (WLK)**
   (Apache-2.0, v0.2.26, 2026-08-29, very active). It already does streaming
   ASR + streaming diarization + streaming translation over one WebSocket, per
   session. Its output (`lines[]` with `speaker`, `start`, `end`, `text`,
   `translation`, `detected_language`, plus a `buffer_*` for partial text) maps
   almost 1:1 onto our Segment model. Run one WLK WebSocket per Source.
   Limits: models run inside the WLK process (so WLK *is* the endpoint, not our
   app); default diarizer is 4 speakers; no Intel GPU path.
4. **Best app to study: Reflector (GreyhavenHQ)** (MIT, v0.47.1, 2026-10-27).
   Its stack is the same as ours (FastAPI + uv backend, Next.js + pnpm
   frontend, WebSocket to the browser) and its models live in a separate,
   stateless HTTP container with per-service URL overrides. But its *live*
   pipeline does only transcription + translation; diarization runs after the
   recording ends. It is a server product (Postgres, Redis, Celery, S3,
   WebRTC), heavier than we need. Study it; do not fork it.
5. **8 speakers needs a new diarization model.** The default streaming
   diarizers in the ecosystem are 4-speaker (`diar_streaming_sortformer_4spk`).
   NVIDIA `Nemotron-3-Diarization` (2026-09-23, OpenMDW-1.1) does streaming
   diarization of up to 8 speakers at 0.32-1.04 s buffer latency. WLK reads the
   speaker count from the loaded checkpoint, so loading this model in WLK is
   plausible but **untested**.
6. **The seed model is not a streaming model.** The
   `NVIDIA-Nemotron-3.5-Transcribe-30B-A4B` model card says: "This is an
   offline model. Internal audio chunking does not make it a real-time
   streaming ASR service." Its reference deployment is 1x H100 80 GB. It does
   not fit the 11 GB or 16 GB remotes in BF16 or FP8. Its streaming sibling,
   `nvidia/nemotron-3.5-asr-streaming-0.6b`, has ports to sherpa-onnx, GGUF,
   ONNX and OpenVINO, and is a better fit for the 2-5 s target. (Model choice
   belongs to a separate ticket.)
7. **Laptop (Intel Lunar Lake, no NVIDIA):** local endpoints that use the Arc
   iGPU or CPU are WhisperLive (`-b openvino`), whisper.cpp / vibe-server
   (Vulkan), and sherpa-onnx (CPU int8 streaming Nemotron). WLK has no
   documented Intel GPU path.

## Comparison table

GitHub data from the GitHub API on 2026-10-29. "Last push" is the
`pushedAt` field. Stars are rounded.

| Project | Role | Licence | Stars | Last push | Latest release | Stack | Live? | Live diarization | Max speakers (live) | Translation | Web UI | Remote endpoint / model choice | Fork practical? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) | Endpoint (+ demo UI) | Apache-2.0 | 11.2k | 2026-10-23 | v0.2.26 (2026-08-29) | Python, FastAPI, HTML/JS | Yes | Yes (Sortformer; Diart) | 4 default; 8 untested | Yes (NLLB/NLLW 200 langs; LLM via AlignAtt4LLM) | Basic HTML, single stream | Many in-process backends; `openai-api` backend for remote ASR | Use as endpoint; do not fork the UI |
| [WhisperLive](https://github.com/collabora/WhisperLive) | Endpoint | MIT | 4.3k | 2026-10-29 | v0.10.0 (2026-09-07) | Python | Yes | Yes (pyannote embeddings, online clustering) | `max_speakers` param (example 4) | Yes (server thread, any to any) | Browser extensions only | faster-whisper, TensorRT, OpenVINO, ROCm | Use as endpoint, esp. OpenVINO on laptop |
| [SimulStreaming](https://github.com/ufal/SimulStreaming) | Endpoint (research) | MIT | 0.7k | 2026-07-12 | "nc" (2025-10-22) | Python, torch | Yes | No | n/a | Yes (Whisper + EuroLLM cascade) | No (TCP server) | Whisper only (torch) | Already integrated in WLK; use via WLK |
| [whisper_streaming](https://github.com/ufal/whisper_streaming) | Endpoint (research) | MIT | 3.7k | 2025-11-12 | none | Python | Yes | No | n/a | Whisper "translate" to EN only | No | faster-whisper, OpenAI API, mlx | No: author says "outdated", replaced by SimulStreaming |
| [diart](https://github.com/juanmc2005/diart) | Diarization lib | MIT | 2.0k | 2026-06-19 | v0.9.2 (2025-02-12) | Python, pyannote | Yes | Yes | configurable | No | No (WebSocket server) | pyannote models | No: NumPy<2, Py<=3.12; WLK marks "not recommended" |
| [Reflector](https://github.com/GreyhavenHQ/reflector) | App + model server | MIT | 37 | 2026-10-27 | v0.47.1 (2026-10-27) | FastAPI/uv, Next.js/pnpm, Celery, Postgres | Yes (WebRTC) | **No** (post-recording) | n/a live | Yes, live (Seamless-M4T) | Yes (Next.js) | Separate HTTP model container; per-service URLs | Study; too heavy to fork |
| [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) | Library + server | MIT | 10.2k | 2026-10-28 | v1.1.2 (2026-08-30) | Python | Yes | No | n/a | No | Demo server | faster-whisper, sherpa-onnx, Kroko | Use ideas (2-pass: stream + final) |
| [speaches](https://github.com/speaches-ai/speaches) | Endpoint | MIT | 3.7k | 2026-10-29 | v0.9.0-rc.3 (2025-12-27) | Python | Yes (SSE, Realtime API) | No | n/a | Whisper to EN | No | OpenAI-compatible; faster-whisper | Use as generic OpenAI-compatible endpoint |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Inference toolkit | Apache-2.0 | 15.6k | 2026-10-29 | v2.0.1 (2026-10-26) | C++ + Python/other bindings | Yes | Offline diarization | n/a | No | No | ONNX models; CPU-friendly | Use as laptop endpoint engine |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Inference engine | MIT | 54.8k | 2026-10-29 | v1.9.5 (2026-10-06) | C/C++ | Yes (stream example, server) | No | n/a | Whisper to EN | No | Vulkan, CUDA, OpenVINO encoder | Use as laptop endpoint engine |
| [Speech Note (dsnote)](https://github.com/mkiol/dsnote) | Desktop app | MPL-2.0 | 1.7k | 2026-10-26 | v4.9.0 (2026-06-28) | C++/Qt, Flatpak | Yes (dictation) | No | n/a | Yes (Bergamot, offline) | No (Qt) | Many local engines, no remote | No: desktop note app, not a timeline |
| [LiveCaptions](https://github.com/abb128/LiveCaptions) | Desktop app | GPL-3.0 | 1.8k | 2025-02-27 | v0.4.2 (2024-06-08) | C, GTK, april-asr | Yes | No | n/a | No | No | English only, CPU only | No: inactive, English only |
| [Meetily](https://github.com/Zackriya-Solutions/meetily) | Desktop app | MIT | 32.3k | 2026-10-29 | v0.4.1 (2026-09-12) | Rust/Tauri, Next.js | Yes | No (PRO only, "planned") | n/a | No | Tauri UI | Whisper/Parakeet local; LLM endpoint for summary | No: no diarization in open edition |
| [anarlog (ex-Hyprnote)](https://github.com/fastrepl/anarlog) | Desktop app | MIT (community) | 9.6k | 2026-10-29 | desktop_v1.4.34 (2026-10-29) | Rust/Tauri, TS | Yes | unverified | unverified | No | Tauri UI | Selected provider; on-device on "supported Macs" | No: meeting notes focus |
| [Vibe](https://github.com/thewh1teagle/vibe) | Desktop app + local server | MIT | 8.0k | 2026-10-29 | v3.3.0 (2026-10-29) | Rust/Tauri, React; `vibe-server` (ggml) | Mic/system capture; streaming unverified | Yes (diarize-rs, Sortformer-based) | unverified | To English only | Tauri UI | `vibe-server` has OpenAI-compatible HTTP API; Whisper, Parakeet, Nemotron 3.5; Vulkan | Use `vibe-server` as laptop endpoint candidate; PRs limited |
| [Buzz](https://github.com/chidiwilliams/buzz) | Desktop app | MIT | 22.3k | 2026-10-27 | v1.4.5 (2026-08-23) | Python/Qt | Yes (mic) | No (files only) | n/a | Whisper to EN | No (Qt) | Whisper backends incl. Vulkan whisper.cpp | No |
| [Scriberr](https://github.com/rishikanthc/Scriberr) | Self-hosted web app | MIT | 3.1k | 2026-09-20 | v1.2.0 (2025-12-17) | Go, web | No (files) | Batch | n/a | No | Yes | Parakeet, Canary, Whisper | No: batch, dev paused |
| [WhisperX](https://github.com/m-bain/whisperX) | Batch library | BSD-2-Clause | 24.9k | 2026-10-22 | v3.8.6 (2026-05-25) | Python | No | Batch (pyannote) | n/a | No | No | faster-whisper | No (batch). Useful for offline re-pass |
| [OpenTranscribe](https://github.com/attevon-llc/OpenTranscribe) | Self-hosted web app | AGPL-3.0 | 0.1k | 2026-10-29 | v0.5.1 (2026-09-20) | FastAPI, Svelte | No (upload / browser record) | Batch | per-file setting | Whisper to EN | Yes | Local models; cloud providers | No: batch, AGPL |
| [Whishper](https://github.com/pluja/whishper) | Self-hosted web app | AGPL-3.0 | 3.1k | 2026-07-31 | v3.1.4 (2024-09-17) | Svelte | No | No | n/a | Yes (LibreTranslate) | Yes | faster-whisper | No |

## Per-option details

### WhisperLiveKit (QuentinFuxa/WhisperLiveKit)

Source: [README](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/README.md),
[docs/API.md](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/docs/API.md),
[sortformer_backend.py](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/diarization/sortformer_backend.py).

- Apache-2.0. v0.2.26 released 2026-08-29. Last push 2026-10-23. Python 3.11-3.13. `uv sync --extra ...` install profiles.
- Streaming policies: SimulStreaming (AlignAtt, default) and LocalAgreement (from whisper_streaming).
- ASR backends: faster-whisper, whisper, mlx-whisper, `openai-api` (LocalAgreement only), FunASR SenseVoiceSmall, Voxtral Mini 4B (HF or MLX), Qwen3-ASR (vLLM CUDA, HF streaming, causal 0.6B tower), NVIDIA Canary-1b-v2 (NeMo).
- Diarization: `--diarization-backend sortformer` (default) or `diart`. Default model in source is `nvidia/diar_streaming_sortformer_4spk-v2`. `--sortformer-max-speakers` accepts 1-4 "for the default model". `--sortformer-model-path` loads another `.nemo` or HF ID. The code reads the channel count from the loaded model (`sortformer_modules.n_spk`), so an 8-channel checkpoint such as `nvidia/Nemotron-3-Diarization` may work. **Not tested.**
- WLK resolves each frame and token to one speaker; it does not output overlapped speech (README, "Sortformer produces independent activity probabilities ... WhisperLiveKit currently resolves each diarization frame and ASR token to one speaker").
- Translation: `--target-language` with NLLW (distilled NLLB 600M or 1.3B, 200 languages; NLLB weights are CC-BY-NC-4.0), or `--translation-backend alignatt` (LLM sidecar). Per-session `?target_language=` query parameter.
- Language: per-session `?language=`; "one shared engine serves mixed-language sessions". Each committed line can carry `detected_language`. With Whisper `--language auto` the README warns it "tends to bias towards English". Canary uses AmberNet LID and *locks* the language once detected, which is wrong for language-switch detection.
- Wire format (docs/API.md): each update sends the full list of committed `lines` (speaker int, start, end, text, optional translation, optional detected_language) plus `buffer_transcription`, `buffer_diarization`, `buffer_translation`. An experimental `?mode=diff` sends only changes. Also an OpenAI-compatible REST endpoint and a Deepgram-compatible WebSocket.
- Concurrency: "The backend supports multiple concurrent users." For Qwen3 streaming, "Plan one realtime session per GPU."
- Web UI: one HTML/JS page (`live_transcription.html`). Single stream, speakers inline. Not a column timeline.
- Hardware: CUDA 12.9 profile, CPU profile, Apple MLX. No OpenVINO or Vulkan path documented.
- Fit: best single *endpoint* for Remote A/B. One WLK WebSocket per Source gives us Segments with Speaker, language and translation. Our app owns the merge onto one Timeline.

### WhisperLive (collabora/WhisperLive)

Source: [README](https://github.com/collabora/WhisperLive/blob/main/README.md).

- MIT. v0.10.0 released 2026-09-07. Last push 2026-10-29.
- WebSocket server; backends `faster_whisper`, `tensorrt`, `openvino`; ROCm via CTranslate2 wheel. "OpenVINO backend for efficient inference on Intel CPUs, iGPU and dGPUs."
- Diarization: optional `pyannote.audio`; "online cosine-similarity clustering of speaker embeddings"; client sets `enable_diarization=True, max_speakers=4`. Completed segments carry `speaker: "SPEAKER_00"`.
- Translation: server-side translation thread, `enable_translation=True`, `target_language=...` (any to any).
- Segment model: partial vs committed callbacks (`on_partial_transcript`, `on_committed_transcript`, `on_translation`). Word timestamps optional. Hotwords.
- Batch inference over clients (`--batch_inference --batch_max_size 8`) and `--max_clients` (default 4). Each client = one Source in our design.
- Fit: best *laptop* endpoint candidate because of OpenVINO on the Arc 140V iGPU (needs a test). Also a valid remote endpoint.
- Related: [Aavaaz](https://github.com/collabora/aavaaz) (MPL-2.0, 3 stars, built on WhisperLive with diarization and REST); too new to judge.

### SimulStreaming and whisper_streaming (ufal)

Source: [SimulStreaming README](https://github.com/ufal/SimulStreaming/blob/main/README.md),
[whisper_streaming README](https://github.com/ufal/whisper_streaming/blob/main/README.md).

- Both MIT ("SimulStreaming changed the licence and is now under MIT").
- SimulStreaming: Whisper large-v3 with AlignAtt policy + optional EuroLLM 9B cascade translation (35 target languages). "Recommended HW is GPU with at least 10G VRAM". Best in IWSLT 2025 simultaneous speech translation task. Torch-only backend. No diarization. Simple TCP server.
- whisper_streaming: "becoming outdated in 2025. It is being replaced by ... SimulStreaming". Last push 2025-11-12.
- Fit: research engines. WLK already embeds both policies, so use them through WLK.

### diart (juanmc2005/diart)

Source: [README](https://github.com/juanmc2005/diart/blob/main/README.md),
WLK README ("Not recommended", "Diart 0.9.2 requires NumPy below 2").

- MIT. v0.9.2 (2025-02-12). Last push 2026-06-19. Real-time incremental clustering diarization with pyannote models (gated on HF). WebSocket server.
- Transcription integration is "coming soon" in the README.
- Fit: not recommended. Old deps, slow release cadence, superseded by Sortformer-family models.

### Reflector (GreyhavenHQ/reflector, formerly Monadical-SAS/reflector)

Source: [README](https://github.com/GreyhavenHQ/reflector/blob/main/README.md),
[docsv2/selfhosted-architecture.md](https://github.com/GreyhavenHQ/reflector/blob/main/docsv2/selfhosted-architecture.md),
[server/reflector/pipelines/main_live_pipeline.py](https://github.com/GreyhavenHQ/reflector/blob/main/server/reflector/pipelines/main_live_pipeline.py).

- MIT. v0.47.1 released 2026-10-27. Small community (37 stars) but very frequent releases.
- Stack: FastAPI backend run with `uv`, Next.js 14 frontend run with `pnpm`, Celery + Redis workers, Postgres, S3-compatible storage, WebRTC audio input from the browser ("Screenshare capture"), optional LiveKit.
- Models: separate `transcription` container (GPU or CPU image) with a "Stateless HTTP API". Per-service backend overrides for transcript, diarization and translation (`EFF_TRANSCRIPT`, `EFF_DIARIZATION`, `EFF_TRANSLATION`) with URLs, or Modal.com serverless GPUs. This is the same "endpoint" idea as ours.
- Models used: Whisper or Parakeet (ASR), pyannote 3.1 (diarization), Seamless-M4T (translation), an LLM (Ollama or external) for topics and summaries.
- Live pipeline (`main_live_pipeline.py`): chunker -> transcript -> liner -> translator -> topic detector. Diarization is a separate `PipelineMainDiarization` run after the recording; it is skipped if audio is local ("Audio is local, skipping diarization").
- Fit: best reference for app architecture and endpoint wiring. Not a base: no live diarization, no multi-Source capture, heavy server infra, input is browser WebRTC not PipeWire.

### RealtimeSTT (KoljaB/RealtimeSTT)

Source: [README](https://github.com/KoljaB/RealtimeSTT/blob/master/README.md).

- MIT. v1.1.2 (2026-08-30). Python 3.11-3.12.
- Recommended CPU profile: streaming `sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8` for fast partial text, then `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` for "the single authoritative final transcript". This two-pass pattern (fast streaming partials, then a final re-decode per utterance) fits our "finalized Segment within 2-5 s" target.
- No diarization, no translation. Fit: a pattern to copy, and a possible CPU endpoint for the laptop.

### speaches (speaches-ai/speaches)

Source: [README](https://github.com/speaches-ai/speaches/blob/master/README.md).

- MIT. v0.9.0-rc.3 (2025-12-27); pushes continue (2026-10-29).
- "OpenAI API-compatible server" for STT/TTS; streaming transcription via SSE; Realtime API; dynamic model load/unload. faster-whisper only for STT.
- No diarization. Fit: a generic OpenAI-compatible endpoint. Useful as a model of the endpoint contract, not as the diarization path.

### sherpa-onnx and whisper.cpp (engines)

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx): Apache-2.0, v2.0.1 (2026-10-26). Streaming ONNX ASR on CPU. Converted Nemotron 3.5 streaming models exist at 80/160/320/560/1120 ms chunk sizes, e.g. [csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11](https://huggingface.co/csukuangfj2/sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11).
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp): MIT, v1.9.5 (2026-10-06). Vulkan and OpenVINO paths for Intel. Used by Speech Note, Buzz, Meetily.
- Fit: engines inside a laptop endpoint, not apps.

### Speech Note (mkiol/dsnote)

Source: [README](https://github.com/mkiol/dsnote/blob/main/README.md).

- MPL-2.0. v4.9.0 (2026-06-28). Qt/C++ desktop app, Flatpak on Flathub.
- STT engines: Coqui STT, Vosk, whisper.cpp (+ Parakeet), Faster Whisper, april-asr, Qwen3-ASR. Machine translation: Bergamot (offline). whisper.cpp Vulkan in the base Flatpak; CUDA and ROCm add-ons.
- No diarization. No remote endpoint. Note-taking UI. Fit: not a base. Good evidence that Vulkan whisper.cpp works on Linux desktops.

### LiveCaptions (abb128/LiveCaptions)

Source: [README](https://github.com/abb128/LiveCaptions/blob/main/README.md).

- GPL-3.0. Last release v0.4.2 (2024-06-08); last push 2025-02-27.
- "Only the English language is supported currently." CPU only ("GPU is not required or used"). Captions desktop or mic audio. No diarization, no translation.
- Fit: no. Inactive and English only.

### Meetily (Zackriya-Solutions/meetily, formerly meeting-minutes)

Source: [README](https://github.com/Zackriya-Solutions/meetily/blob/main/README.md).

- MIT (Community Edition). v0.4.1 (2026-09-12). 32k stars.
- Tauri app: Rust backend, Next.js frontend. Captures mic and system audio "simultaneously" and mixes them. Whisper or Parakeet local transcription. LLM summary via Ollama or any OpenAI-compatible endpoint.
- Diarization: only in PRO, "planned"; PRO is "Built on a different codebase". Linux: build from source.
- Fit: no. No diarization, no translation, mixes Sources into one stream (we need them apart).

### anarlog (fastrepl/anarlog, formerly Hyprnote)

Source: [README](https://github.com/fastrepl/anarlog/blob/main/README.md).

- MIT for the community app; "Source-visible enterprise components are commercially licensed." desktop_v1.4.34 (2026-10-29).
- Captures device audio; transcription via on-device model "On supported Macs" or a selected provider; managed cloud prefers Soniox. Local SQLite, Markdown export.
- Linux local transcription and diarization: **unverified**. Fit: no; meeting notepad, not a speaker timeline.

### Vibe (thewh1teagle/vibe)

Source: [README](https://github.com/thewh1teagle/vibe/blob/main/README.md),
[docs/ARCHITECTURE.md](https://github.com/thewh1teagle/vibe/blob/main/docs/ARCHITECTURE.md).

- MIT. v3.3.0 (2026-10-29). Tauri desktop app.
- `vibe-server` (Rust on ggml: whisper-rs, parakeet-rs, nemotron-rs, vad-rs, diarize-rs) is a "single local process for audio transcription, model loading, streaming, and diarization, behind an OpenAI-compatible HTTP API". Vulkan for NVIDIA/AMD/Intel GPUs. The diarize-rs crate contains Sortformer AOSC code (`sf_gguf.rs`, `host/aosc.rs`).
- Features list: mic and system audio, speaker diarization, "Realtime preview", translate to English only, HTTP API with Swagger.
- Whether `vibe-server` does *live* streaming diarization over the network: **unverified**.
- "Pull requests are limited to a few collaborators." Fit: `vibe-server` is a candidate laptop endpoint (Vulkan on Arc 140V); the app is not a base.

### Buzz (chidiwilliams/buzz)

Source: [README](https://github.com/chidiwilliams/buzz/blob/main/README.md).

- MIT. v1.4.5 (2026-08-23). Python/Qt desktop. Live mic transcription with presentation window. Speaker identification for files. Vulkan whisper.cpp. Whisper translate to English.
- Fit: no. Desktop, single stream, no live diarization.

### Scriberr (rishikanthc/Scriberr)

Source: [README](https://github.com/rishikanthc/Scriberr/blob/main/README.md).

- MIT. v1.2.0 (2025-12-17). Go backend, web UI (PWA). File transcription with Parakeet, Canary, Whisper; diarization; LLM chat.
- README: development was paused and the author says it will restart.
- Fit: no. Batch only.

### WhisperX, OpenTranscribe, Whishper (batch tools)

- [WhisperX](https://github.com/m-bain/whisperX): BSD-2-Clause, v3.8.6. "70x realtime" batched Whisper + alignment + pyannote diarization (`speaker-diarization-community-1`, CC-BY-4.0). Batch only. Could serve a later "re-process session" feature.
- [OpenTranscribe](https://github.com/attevon-llc/OpenTranscribe): AGPL-3.0. Rich speaker profiles and renaming, but upload/batch. AGPL is a risk if we copy code.
- [Whishper](https://github.com/pluja/whishper): AGPL-3.0, last release 2024-09. Batch.

## Models seen in these projects (context for the model ticket)

- [nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B): released 2026-10-28. OpenMDW-1.1. 34B total, 4.3B active. 40 languages incl. English and French (both "Leading", with multispeaker ASR and code-switching). Speaker tags `<spk:0>..`, translation, LID. Deployment "1x H100 80 GB". "This is an offline model." BF16/FP8/NVFP4 variants. By arithmetic (34B parameters x 2 / 1 / ~0.5 bytes) the weights alone are about 68 / 34 / 17 GB, so none fits 11 GB or 16 GB VRAM without CPU offload (estimate, not measured).
- [nvidia/nemotron-3.5-asr-streaming-0.6b](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b): streaming 0.6B ASR; ports to sherpa-onnx, GGUF (used by Vibe and Handy), ONNX, MLX, OpenVINO (`FluidInference/Nemotron-3.5-ASR-Streaming-Multilingual-0.6b-ov`).
- [nvidia/Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization): released 2026-09-23. OpenMDW-1.1. ~100M params. Streaming and offline, "handles up to eight speakers". Input buffer latency 0.32 / 0.64 / 1.04 s configs. NeMo, Transformers, and NeMo-Speech.cpp runtimes.
- [nvidia/diar_streaming_sortformer_4spk-v2.1](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1): 4 speakers. WLK default is `-v2`.

## Fit to hardware levels

| Level | Hardware | Endpoint candidates | Notes |
|---|---|---|---|
| Laptop | Core Ultra 7 258V, Arc 140V iGPU, NPU, 32 GB shared | WhisperLive `-b openvino`; whisper.cpp (Vulkan or OpenVINO encoder); `vibe-server` (Vulkan); sherpa-onnx streaming Nemotron int8 (CPU) | No project documents NPU use for streaming ASR. WLK has no Intel GPU path. Live diarization on the laptop: no tested option found; Nemotron-3-Diarization via NeMo-Speech.cpp is a candidate (unverified on Intel). |
| Remote A | NVIDIA 11 GB + 128 GB RAM | WLK (CUDA) with Whisper large-v3 or Canary/Qwen3-ASR + Sortformer + NLLB 600M; WhisperLive faster-whisper | SimulStreaming README: >= 10 GB VRAM for large-v3. ASR + diarizer + NLLB together on 11 GB is tight; needs measurement. |
| Remote B | NVIDIA 16 GB + 128 GB RAM | Same as A, more headroom; possibly LLM translation sidecar | Nemotron 3.5 Transcribe 30B does not fit in VRAM (see above) and is offline only. |

## Gaps that no project fills (our app must build these)

- Several Sources at once (mic + sink monitors via PipeWire), kept separate, each with its own mode ("single speaker" or "diarize").
- One Timeline with one Column per Speaker, aligned on time across Sources.
- Renamable Columns (Display name) that persist across the Session.
- Language switch detection per Segment as a first-class event. (WLK gives `detected_language` per line; Canary locks the language; Whisper "auto" biases to English.)
- Endpoint abstraction: the app calls endpoints only. WLK and WhisperLive are endpoints that run models; Reflector shows how to make the URLs configurable per service.
- Continuous save and Markdown/JSON export of Segments with Speaker, language and Translation.

## Open questions for downstream decision tickets

1. **Diarization, 8 speakers:** Does WLK work with `--sortformer-model-path nvidia/Nemotron-3-Diarization` and give 8 speakers? (Code reads `n_spk` from the model; untested.) If not, do we run Nemotron-3-Diarization in our own small endpoint?
2. **Endpoint contract:** Do we adopt WLK's WebSocket JSON (`lines` + `buffer_*`) as our internal endpoint protocol, or define our own and write adapters for WLK, WhisperLive and OpenAI-compatible servers?
3. **One endpoint session per Source:** Is one WLK/WhisperLive WebSocket per Source acceptable for GPU memory and latency on Remote A (11 GB)? Needs a benchmark with 2-3 Sources.
4. **Laptop path:** Does WhisperLive OpenVINO on the Arc 140V reach real time with a medium/large-v3-turbo model? Does sherpa-onnx streaming Nemotron 0.6B handle French on CPU? Can anything use the NPU?
5. **Language switch detection:** Which ASR gives reliable per-Segment language ID for English/French switching in a stream? Whisper "auto" is biased; Canary locks; Nemotron 3.5 Transcribe supports code-switching but is offline.
6. **Translation:** NLLB (NLLW) in WLK vs an LLM via an OpenAI-compatible endpoint. The NLLW repo has no licence file on GitHub (licenseInfo null). The NLLB weights are CC-BY-NC-4.0 (non-commercial) per the [facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M) model card. This is acceptable for personal use, but it needs a decision before we depend on it.
7. **Two-pass finalization:** Do we adopt RealtimeSTT's pattern (streaming partials, then a final re-decode per utterance) to get accurate finalized Segments within 2-5 s?
8. **Reuse of Reflector parts:** Is any Reflector code (endpoint client classes, WebSocket event model) worth copying under MIT, or do we only borrow the design?

## Method and limits

- Repo facts (licence, stars, last push, latest release) come from the GitHub GraphQL API on 2026-10-29.
- Feature claims come from each project's README or docs at the default branch on 2026-10-29, and for Reflector and WLK from the source files linked above.
- I did not run any of the software. All latency and VRAM fit statements are from the projects' own docs or are marked as estimates.
- Items marked "unverified" need a test or a deeper source read.
