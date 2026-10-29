# Research: Survey inference servers and endpoint protocols

Ticket: [#5](https://github.com/gdevenyi/live-transcribe-translate/issues/5) (parent map: #1).
Research date: 2026-10-29. Versions and dates come from the GitHub API and from
the pages cited below, on that date.

## Question

Which inference servers can expose ASR, diarization and translation models as
network endpoints, and with which protocols? Include vLLM, speaches
(faster-whisper-server), whisper.cpp server, OpenVINO Model Server, NVIDIA
Riva/NeMo, Wyoming, llama.cpp server, and the OpenAI-compatible transcription
and realtime APIs. Which protocols support streaming audio input and partial or
final results? Which run on the laptop (Intel Arc/NPU) and which on the remote
NVIDIA machines?

## Short answer

1. **There are three protocol classes.** Only class C gives live input.
   - **A. POST a file, get blocking JSON.** `multipart/form-data` to
     `/v1/audio/transcriptions` (or a similar path). Examples: whisper.cpp
     `/inference`, NIM HTTP, OVMS `/v3/...`, and vLLM, speaches and
     NeMo-Speech.cpp without `stream`.
   - **B. POST a file, get an SSE text stream.** `stream=true`. The *output*
     streams, but the *input* is still a complete file. Examples: speaches,
     OVMS, OpenAI (`transcript.text.delta`/`.done`), NeMo-Speech.cpp chat
     completions, and vLLM translations.
   - **C. WebSocket with live PCM16 in and delta/completed events out.** This
     is the OpenAI Realtime "transcription session" shape. Examples: llama.cpp
     `/v1/realtime`, speaches `/v1/realtime?intent=transcription`, NVIDIA Speech
     NIM `:9000/v1/realtime?intent=transcription`, NeMo-Speech.cpp
     `/v1/audio/transcriptions/realtime`, vLLM `/v1/realtime`, and OpenAI. The
     Wyoming protocol (TCP, JSONL + PCM, `transcript-chunk`) is also in this
     class.
2. **Class A with client-side chunking also meets the 2-5 s target.** The
   client cuts the audio at VAD boundaries and POSTs each segment. Class C is
   better for partial results, and it is necessary for cache-aware streaming
   models.
3. **Most servers use the same event names.** The OpenAI Realtime
   transcription schema is the common one: `input_audio_buffer.append` /
   `input_audio_buffer.commit` in, and
   `conversation.item.input_audio_transcription.delta` / `.completed` out.
   llama.cpp, speaches, NIM and NeMo-Speech.cpp use these names. **vLLM is the
   exception.** Its docs list `transcription.delta` / `transcription.done`. NIM
   also needs an extra `input_audio_buffer.done` event. One client adapter with
   small per-server variants will cover all of them.
4. **Recommended primary endpoint: NeMo-Speech.cpp** (NVIDIA, Apache-2.0,
   v0.2.0 of 2026-10-02) serving **Nemotron 3.5 ASR Streaming 0.6B**
   (OpenMDW-1.1).
   - It runs on CUDA, Vulkan and CPU, so the same server can run on all three
     hardware levels. Arc 140V Vulkan performance is not verified.
   - Its realtime WebSocket gives partial and final results, word timestamps,
     and streaming diarization (Sortformer, or Nemotron 3 Diarization for up to
     8 speakers).
   - It also has a text translation endpoint.
   - The model detects the language itself (`auto`) and adds a tag such as
     `<fr-FR>` to each utterance. This is a direct signal for language switch
     detection.
5. **Second option, the same NVIDIA models in a supported container: NVIDIA
   Speech NIM (Riva).** It has gRPC streaming, a realtime WebSocket with
   streaming diarization (1-8 speakers for Nemotron ASR Streaming), and HTTP.
   - It needs **at least 16 GB VRAM** and compute capability 8.0 or higher. It
     does not fit Remote A (11 GB) and is at the limit on Remote B (16 GB).
   - It is free only for research and development (up to 16 GPUs). Production
     use needs an NVIDIA AI Enterprise licence.
6. **Second option for the laptop: OpenVINO Model Server (OVMS) 2026.4.1.**
   - It is the only server in this survey with documented CPU, GPU and NPU
     targets for ASR (Whisper, Qwen3-ASR, others).
   - It is class A/B only: there is no WebSocket. The app must cut the audio
     into segments.
7. **Second option on the NVIDIA machines for an open-source LLM-style
   stack: vLLM 0.32.0 or llama.cpp.** Both have a realtime WebSocket for
   Voxtral Mini 4B Realtime (Apache-2.0, en/fr) and other models. Both also
   serve the text LLM for translation through `/v1/chat/completions`.
8. **The seed model, Nemotron 3.5 Transcribe 30B-A4B, is offline only.** Its
   model card says it is not a real-time streaming ASR service.
   - It has 34B parameters in total and is tuned for one 80 GB H100.
   - Use it only for a possible "re-transcribe the session after it ends"
     step, not for the live path.
   - It is not verified whether it fits on 11 or 16 GB VRAM.

## Comparison table

| Server | Version, date, licence | ASR protocol(s) | Live audio input | Partial + final | Diarization endpoint | Translation endpoint | Laptop (Arc 140V / NPU) | Remote NVIDIA (11 / 16 GB) |
|---|---|---|---|---|---|---|---|---|
| **NeMo-Speech.cpp** | v0.2.0, 2026-10-02 (nightly 2026-10-28); Apache-2.0 | REST `/v1/audio/transcriptions`; WS `/v1/audio/transcriptions/realtime`; Riva-compatible gRPC (`riva_server`) | Yes (WS: binary or base64 PCM16) | Yes (`.delta` / `.completed`) | Live in the WS (`speaker_diarization`); file: `/v1/audio/diarizations` | Text `/v1/translations`; speech `/v1/audio/translations` | Vulkan and CPU builds exist; Arc not verified | CUDA (Turing or newer); 0.6B Q8 model is small |
| **NVIDIA Speech NIM (Riva)** | docs updated 2026-10-07; NIM licence (free dev, ≤16 GPUs; production = AI Enterprise) | gRPC `StreamingRecognize`; WS `:9000/v1/realtime?intent=transcription`; REST `/v1/audio/transcriptions` | Yes (gRPC, WS) | Yes | Live in the WS (1-8 spk Nemotron, 1-4 Parakeet) | REST `/v1/audio/translations` (Canary, Whisper only) | No (NVIDIA only) | Needs ≥16 GB VRAM and CC ≥8.0: A no, B at the limit |
| **vLLM** | v0.32.0, 2026-10-18; Apache-2.0 | REST `/v1/audio/transcriptions`, `/v1/audio/translations`; WS `/v1/realtime` | Yes (WS, realtime models only) | Yes (`transcription.delta` / `.done`) | `diarized_json` only for MOSS-Transcribe-Diarize | Whisper to English; any text LLM via chat completions | XPU wheels list "Intel ARC GPU"; iGPU and audio not verified | Yes (CUDA) |
| **llama.cpp `llama-server`** | b11988, 2026-10-29; MIT | `/v1/chat/completions` with `input_audio`; WS `/v1/realtime` | Yes (WS, streaming-encoder models) | Yes (`.delta` / `.completed`) | No | Any text LLM via chat completions | SYCL, Vulkan, OpenVINO (WIP) backends; audio on Arc not verified | Yes (CUDA) |
| **speaches** | main active 2026-10; last tag v0.9.0-rc.3, 2025-12-27; MIT | REST `/v1/audio/transcriptions` (+SSE); WS `/v1/realtime?intent=transcription`; WebRTC | Yes (WS) | Yes (`.completed`; deltas implied) | File: `/v1/audio/diarization` (pyannote community-1) | Whisper to English | CPU only (CUDA or CPU; no Intel provider in config) | Yes (CUDA image) |
| **OpenVINO Model Server** | 2026.4.1, 2026-10-06; Apache-2.0 | REST `/v3/audio/transcriptions` (+SSE), `/v3/audio/translations` | No | Partial via SSE over a file | No | Whisper to English | Yes: CPU, GPU, NPU | Not the target platform |
| **whisper.cpp `whisper-server`** | v1.9.5, 2026-10-06; MIT | REST `/inference` (path can be changed) | No | No | Stereo-channel or tinydiarize only | Whisper to English (`--translate`) | Vulkan, OpenVINO (encoder only) | Yes (CUDA) |
| **Wyoming** (protocol) | v1.10.2, 2026-08-27; MIT | TCP, JSONL header + PCM payload | Yes (`audio-chunk`) | Yes (`transcript-chunk`, each replaces the last) | No speaker field | No | Depends on the server behind it | Depends on the server behind it |
| **WhisperLive** (extra) | v0.10.0, 2026-09-07; MIT | Custom WS; optional OpenAI REST | Yes | Yes | Has a diarization section (not checked) | Whisper | OpenVINO backend (iGPU) | faster-whisper, TensorRT |
| **SGLang-Omni** (extra) | v0.2.0, 2026-10-27; Apache-2.0 | REST `/v1/audio/transcriptions` | No | No | No (for Nemotron Transcribe) | Via the model prompt | No | Yes |
| **OpenAI API** (cloud, reference) | n/a | REST (+SSE); WS `wss://api.openai.com/v1/realtime?intent=transcription` | Yes (WS) | Yes | File only, deprecated model | Realtime translate model | n/a | n/a |

## Protocol details

### A and B: OpenAI-style `/audio/transcriptions` (file in)

- The OpenAI reference: you POST a file of up to 25 MB, with optional
  `stream=true`. The server then sends `transcript.text.delta` events and a
  final `transcript.text.done` event. `diarized_json` exists only on the
  deprecated `gpt-4o-transcribe-diarize` model.
  `timestamp_granularities` exists only on `whisper-1`. `whisper-1`, the
  `gpt-4o-*` transcribe models and `/v1/audio/translations` shut down on
  2027-02-26.
  Source: <https://developers.openai.com/api/docs/guides/speech-to-text>
- The OpenAI page says: "For live audio, use Realtime transcription instead."
  This applies to every self-hosted server too. A class B stream speeds up
  output only. It does not let you send audio while it is recorded.

### C: OpenAI Realtime transcription session (WebSocket)

- **OpenAI.** You connect to
  `wss://api.openai.com/v1/realtime?intent=transcription` and send
  `session.update` with `session.type = "transcription"`. The audio format is
  `audio/pcm` (the examples use 24 kHz).
  - Client events: `input_audio_buffer.append` (base64 PCM16) and
    `input_audio_buffer.commit`.
  - Server events: `conversation.item.input_audio_transcription.delta` (text in
    `delta`) and `...completed` (text in `transcript`). Match them by
    `item_id`, because completed events can arrive out of order.
  - The recommended model is `gpt-live-transcribe`. It has no server VAD,
    no speaker labels and no word timestamps. `gpt-transcribe` returns
    detected `languages`.
  - Source: <https://developers.openai.com/api/docs/guides/realtime-transcription>
- **Wyoming.** This is a peer-to-peer TCP protocol: a JSON header line, then
  optional extra data, then a PCM payload.
  - Audio events: `audio-start`, `audio-chunk` (rate, width, channels,
    optional `timestamp`) and `audio-stop`.
  - Transcript events: `transcript-start`, then `transcript-chunk` (this is
    "transcript so far … each chunk replaces the previous one"), then
    `transcript` and `transcript-stop`.
  - A server advertises `supports_transcript_streaming`.
  - There is no speaker, timestamp-per-word or translation field. Wyoming was
    made for single-user voice assistants (Home Assistant).
  - Source: <https://github.com/OHF-Voice/wyoming/blob/main/README.md>
- **NVIDIA Riva gRPC.** The `RivaSpeechRecognition` service has batch and
  streaming recognition methods. NeMo-Speech.cpp ships a Riva-compatible
  `riva_server`.
  Sources: <https://docs.nvidia.com/nim/speech/latest/reference/api-references/asr/index.html>,
  <https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/server.md>

## Per-server details

### NeMo-Speech.cpp (NVIDIA, ggml-based C++ runtime)

- The repo was created on 2026-07-15. v0.2.0 was released on 2026-10-02 and
  nightly builds were made up to 2026-10-28. The licence is Apache-2.0.
  Source: GitHub API for `NVIDIA/NeMo-Speech.cpp`, and
  <https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/README.md>
- **Supported models:**
  - ASR: Nemotron 3.5 ASR Streaming 0.6B, Nemotron Speech Streaming 0.6B (en),
    Parakeet TDT 0.6B v3 and Parakeet CTC 1.1B.
  - Speech-LLM: Nemotron 3.5 Transcribe 30B-A4B.
  - Diarization: Streaming Sortformer 4spk v2 and Nemotron 3 Diarization.
  - Translation: Riva Translate 4B Instruct v2.
  - Also TTS, VAD and endpointing.
  - Source: README "Models and applications".
- **Backends:**
  - CPU, CUDA, Metal and Vulkan prebuilt archives.
  - The CUDA archive needs Turing (CC 7.5) or newer.
  - "Vulkan archives use the host's Vulkan loader and vendor driver."
  - Source: <https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/install.md>
- **Performance:** Nemotron Speech Streaming 0.6B Q8_0 with 160 ms chunks
  takes 2.3 ms per chunk on an RTX 4090 and 27 ms per chunk on CPU (6x real
  time). Source: README "Performance".
- **HTTP API** (source:
  <https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/api.md>):
  - `POST /v1/audio/transcriptions`: `language`, `response_format`
    (`json`, `verbose_json`, SRT, VTT) and `diarization` (needs `verbose_json`
    and a diarizer). `verbose_json` gives `words[]` with `start`, `end`,
    `confidence` and `speaker`.
  - `WS /v1/audio/transcriptions/realtime`:
    - The client sends one `session.update`. Its fields are `sample_rate`
      (8000-96000), `language`, `word_timestamps`, `speaker_diarization`,
      `endpointing_ms` and `speech_contexts`.
    - The client then sends PCM16 audio as binary frames or as base64
      `input_audio_buffer.append`, and ends with `input_audio_buffer.commit`.
    - The server sends `conversation.item.input_audio_transcription.delta`
      (partials) and `.completed` (finals, with `words`).
    - The doc calls this "a project-specific event protocol", but the event
      names are the OpenAI ones.
    - `/v1/realtime` serves the same protocol when VoiceChat is not loaded.
    - Offline-only models (SALM, for example Nemotron Transcribe) refuse the
      socket with `streaming_unsupported`.
  - `POST /v1/translations`: text in, with `source_language` and
    `target_language`. The response is `{"translations":[{"text":...}]}`.
  - `POST /v1/audio/translations`: speech translation into any target that the
    SALM model knows.
  - `POST /v1/audio/diarizations`: file in, `{"segments":[{start,end,speaker}]}`
    out.
  - `POST /v1/chat/completions`: for the SALM (Nemotron Transcribe) model. It
    accepts `timestamp_granularities`, gives speaker tags `spk:N`, and can
    stream SSE.
- **Fit:**
  - Remote A and B: good. The 0.6B models are small, and the CUDA build is
    supported.
  - Laptop: the Vulkan or CPU build is possible. Arc 140V performance is
    **not verified**. The published CPU number (27 ms per 160 ms chunk)
    suggests that CPU alone can keep up with one stream. It is not verified
    for 4 or more parallel sources with diarization.

### NVIDIA Speech NIM (Riva ASR)

- **APIs** (source:
  <https://docs.nvidia.com/nim/speech/latest/reference/api-references/asr/index.html>):
  - **gRPC:** batch and streaming.
  - **HTTP:** `POST /v1/audio/transcriptions` and `/v1/audio/translations` on
    port 9000. There are no partial results and no word timestamps in the
    response. Translation works only with Canary and Whisper.
    Source: <https://docs.nvidia.com/nim/speech/latest/reference/api-references/asr/http-asr.html>
  - **Realtime WS:** `ws://<host>:9000/v1/realtime?intent=transcription`.
    - Input is PCM16 at 16 kHz mono, base64-encoded.
    - Client events: `transcription_session.update`,
      `input_audio_buffer.append`, `.commit`, `.clear` and `.done`.
    - Server events: `conversation.item.input_audio_transcription.delta`,
      `.completed` (with `is_last_result` and `words_info.words[].speaker_tag`)
      and `.failed`.
    - Diarization: set `speaker_diarization.enable_speaker_diarization`;
      `max_speaker_count` is 1-8 for Nemotron ASR Streaming and 1-4 for
      Parakeet CTC/RNNT.
    - The page does not claim drop-in OpenAI compatibility.
    - Source: <https://docs.nvidia.com/nim/speech/latest/reference/api-references/asr/realtime-asr.html>
- **Models and memory** (source:
  <https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html>):
  - Nemotron ASR Streaming (fr-FR and fr-CA "transcription-ready"; streaming
    only; 4-23 GB).
  - Parakeet 1.1b RNNT Multilingual (fr; 12.8-50 GB).
  - Parakeet 0.6b CTC en (3-22 GB).
  - Canary 1b (offline; 13.4 GB) and Whisper Large v3 (offline; 12.5 GB).
  - The page states "at least 16 GB of VRAM" and minimum compute capability
    8.0. The listed GPUs include GeForce RTX 40xx, 50xx and 60xx.
- **Licence:** Developer Program members can self-host NIM on up to 16 GPUs
  for research, development and testing. Production use needs an NVIDIA AI
  Enterprise licence.
  Sources: <https://developer.nvidia.com/blog/access-to-nvidia-nim-now-available-free-to-developer-program-members>,
  <https://docs.api.nvidia.com/nim/docs/product>
- **Fit:**
  - Remote A (11 GB): no, by the stated minimum.
  - Remote B (16 GB): at the minimum. Its compute capability is unknown, so
    check it.
  - Laptop: no.

### vLLM

- v0.32.0 was released on 2026-10-18. The licence is Apache-2.0.
- **Endpoints** (source:
  <https://docs.vllm.ai/en/latest/serving/online_serving/speech_to_text/>):
  - `/v1/audio/transcriptions`: `response_format` is `json`, `text`,
    `verbose_json` or `diarized_json`. `diarized_json` works only with
    `OpenMOSS-Team/MOSS-Transcribe-Diarize`.
  - `/v1/audio/translations`: Whisper only, into English, with `stream`.
  - `/v1/realtime`: a WebSocket.
    - Input is PCM16 at 16 kHz mono, base64-encoded.
    - Client events: `input_audio_buffer.append`,
      `input_audio_buffer.commit` (`final: bool`) and `session.update`.
    - Server events: `session.created`, `transcription.delta`,
      `transcription.done` and `error`.
  - The default upload limit is 25 MB.
- **Models** (source:
  <https://docs.vllm.ai/en/latest/models/supported_models/>):
  - Transcription: Whisper, Voxtral, Qwen3-ASR, Granite Speech, Cohere
    Transcribe, Nemotron-3.5-Transcribe (BF16, FP8, NVFP4), MOSS and others.
  - **Realtime:** `mistralai/Voxtral-Mini-4B-Realtime-2602` (4.4B parameters,
    Apache-2.0, en/fr among 13 languages) and `Qwen/Qwen3-ASR-0.6B`
    (Apache-2.0).
- **Nemotron 3.5 Transcribe on vLLM** uses `/v1/chat/completions` with base64
  audio, not the transcription API. The recommended setup is one 80 GB H100.
  Source: <https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B>
- **Intel:** vLLM publishes XPU wheels. The listed hardware is "Intel Data
  Center GPU, Intel ARC GPU", and Python 3.12 is required.
  Source: <https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.xpu.inc.md>
  Lunar Lake iGPU support and audio models on XPU are **not verified**.
- **Fit:**
  - Remotes: yes. Voxtral Realtime in BF16 needs about 9 GB of weights
    (estimate from 4.4B × 2 bytes), so it is tight on 11 GB. Qwen3-ASR-0.6B
    is the safe choice on Remote A.
  - Laptop: unlikely to be practical (not verified).

### llama.cpp `llama-server`

- Build b11988 was released on 2026-10-29. The licence is MIT.
- **Audio input** (source:
  <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>):
  - Audio goes in through `/v1/chat/completions` as an `input_audio` content
    part. The supported audio models include Ultravox, Qwen2-Audio, Voxtral
    Mini 3B, Qwen2.5/3-Omni and Gemma 4 (see `docs/multimodal.md`).
  - There is no `/v1/audio/transcriptions` route.
- **WebSocket `/v1/realtime`**, described as "Compatible with OAI
  `/v1/realtime` schema":
  - It is for models with a streaming audio encoder, for example Voxtral
    Realtime and LFM3-Audio live ASR.
  - Input is PCM16 mono at the model sample rate.
  - Events: `conversation.item.input_audio_transcription.delta` and
    `.completed`, and `input_audio_buffer.committed`.
  - Live ASR models restart their context after a pause once 15 s have passed,
    and always after 30 s.
- **Backends:** CUDA, Vulkan, SYCL and OpenVINO. The OpenVINO backend targets
  Intel CPU, GPU and NPU, and is validated on Core Ultra Series 1 and 2. The
  docs say "performance … and broader operator and model support are work in
  progress".
  Source: <https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/OPENVINO.md>
- **Role:** llama.cpp is the most likely **translation** endpoint on the
  laptop (a text LLM through `/v1/chat/completions` on Vulkan or SYCL). It can
  also be a realtime ASR endpoint.
- **Fit:**
  - Remotes: yes.
  - Laptop: text LLMs on Vulkan or SYCL are a known use. The audio encoder
    (mtmd) path on Arc or OpenVINO is **not verified**.

### speaches (formerly faster-whisper-server)

- The licence is MIT. The main branch was active in 2026-10. The last tag is
  `v0.9.0-rc.3` (2025-12-27); there is no stable 2026 tag.
  Source: GitHub API for `speaches-ai/speaches`.
- **Endpoints:**
  - `/v1/audio/transcriptions`: `stream` (SSE), `timestamp_granularities[]`
    and `verbose_json`.
    Source: <https://github.com/speaches-ai/speaches/blob/master/src/speaches/routers/stt.py>
  - `/v1/audio/diarization`: pyannote `speaker-diarization-community-1`; file
    in; `json` or `rttm` out; `known_speaker_names[]`.
    Source: <https://github.com/speaches-ai/speaches/blob/master/src/speaches/routers/diarization.py>
  - Realtime WebSocket `/v1/realtime?intent=transcription` (plus WebRTC).
    - It has server VAD events (`input_audio_buffer.speech_started` and
      `.speech_stopped`).
    - The final transcript comes in
      `conversation.item.input_audio_transcription.completed`.
    - Source: <https://speaches.ai/usage/realtime-api/>
- **Backends:**
  - ASR engines: faster-whisper (CTranslate2), and Parakeet TDT through
    `onnx-asr` (`src/speaches/executors/parakeet.py`).
  - Device setting: `cpu`, `cuda` or `auto`. The ONNX Runtime provider
    priority favours CUDA.
  - Docker images: `latest-cuda` and `latest-cpu`.
  - Sources: <https://github.com/speaches-ai/speaches/blob/master/src/speaches/config.py>,
    <https://speaches.ai/installation/>
- **Fit:**
  - Remotes: yes (CUDA).
  - Laptop: CPU only. There is no OpenVINO or Intel GPU provider.

### OpenVINO Model Server (OVMS)

- 2026.4.1 was released on 2026-10-06. The licence is Apache-2.0.
- **Endpoints:** `/v3/audio/transcriptions` and `/v3/audio/translations`
  (note the `/v3` prefix). The request is `multipart/form-data`, and only
  `mp3` and `wav` files are accepted.
  - Transcription supports `language`, `stream`, `temperature` and
    `timestamp_granularities` (word timestamps need
    `enable_word_timestamps: true` in `graph.pbtxt`).
  - It does not support `prompt`, `response_format` or `known_speaker_*`.
  - The translations endpoint does not stream.
  - There is no WebSocket and no diarization.
  - Source: <https://github.com/openvinotoolkit/model_server/blob/releases/2026/4/docs/model_server_rest_api_speech_to_text.md>
- **Devices:** the calculator option `device` accepts "CPU, GPU, NPU". The demo
  shows an NPU Docker run with `--device /dev/accel`.
  Sources: <https://github.com/openvinotoolkit/model_server/blob/releases/2026/4/docs/speech_recognition/reference.md>,
  <https://github.com/openvinotoolkit/model_server/blob/releases/2026/4/demos/audio/README.md>
- **Models (OpenVINO GenAI):** Whisper (tiny to large-v3), Distil-Whisper,
  Qwen3-ASR 0.6B/1.7B, Fun-ASR-Nano and SenseVoice-Small. Parakeet is not
  listed.
  Source: <https://openvinotoolkit.github.io/openvino.genai/docs/supported-models/>
- **Fit:**
  - Laptop: the best fit for iGPU or NPU offload. The app must segment the
    audio (VAD) and POST each segment.
  - Remotes: not useful.

### whisper.cpp `whisper-server`

- v1.9.5 was released on 2026-10-06. The licence is MIT.
- **Endpoints:** `POST /inference` (`multipart/form-data`) and `POST /load`.
  The path can be changed with `--inference-path`. `response_format` is
  `json`, `text`, `srt`, `vtt` or `verbose_json`.
- **Other features:** server-side VAD flags, and `--translate` (into English
  only).
- **Diarization:** only `--diarize` (stereo channel) or `--tinydiarize` (needs
  a tdrz model).
- **Streaming:** no streaming endpoint. The `stream` example is a local
  microphone tool, not a server.
- Sources: <https://github.com/ggml-org/whisper.cpp/blob/master/examples/server/README.md>,
  <https://github.com/ggml-org/whisper.cpp/blob/master/examples/server/server.cpp>
- **Backends:** CUDA, Vulkan, OpenVINO (encoder only, on Intel CPU and GPU),
  and others. The repo now also has `parakeet-cli`.
  Source: <https://github.com/ggml-org/whisper.cpp/blob/master/README.md>
- **Fit:** a simple class A fallback on any of the three machines.

### Wyoming

- This is a protocol, not a server: v1.10.2 (2026-08-27), MIT, maintained by
  the Open Home Foundation.
- It supports streaming in and streaming partial transcripts out.
- It has no speakers, no word timings and no translation. It does not fit
  the needs of this project without extensions.
- Source: <https://github.com/OHF-Voice/wyoming/blob/main/README.md>

### Extras found

- **WhisperLive** (Collabora; v0.10.0, 2026-09-07; MIT): a custom WebSocket
  streaming server with `faster_whisper`, `tensorrt` and `openvino` backends.
  The OpenVINO backend runs on Intel iGPU. It also has an optional OpenAI REST
  interface. It is an option for the laptop with a live socket.
  Source: <https://github.com/collabora/WhisperLive/blob/main/README.md>
- **SGLang-Omni** (v0.2.0, 2026-10-27; Apache-2.0): `/v1/audio/transcriptions`
  for Nemotron Transcribe. It does whole-file transcription only, with no word
  timestamps or speakers.
  Source: <https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B>

## Relevant models (for the server choice)

| Model | Params | Licence | Mode | EN/FR | Notes | Source |
|---|---|---|---|---|---|---|
| Nemotron 3.5 ASR Streaming 0.6B | 0.6B | OpenMDW-1.1 | Streaming (80-1120 ms chunks) | Both "transcription-ready" | `target_lang=auto` adds a language tag (e.g. `<fr-FR>`); FLEURS WER en 7.91 and fr 9.03 at 1.12 s; released 2026-06-04 | <https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b> |
| Nemotron 3 Diarization | 99.2M | OpenMDW-1.1 | Streaming and offline, up to 8 speakers | n/a | Released 2026-09-23; 0.32-1.04 s low-latency configs | <https://huggingface.co/nvidia/Nemotron-3-Diarization> |
| Nemotron 3.5 Transcribe 30B-A4B | 34B total, ~4B active | OpenMDW-1.1 | **Offline only** | Both "Leading" | Translation to and from English; speaker attribution up to 8 speakers; released 2026-10-28; H100 80 GB recommended | <https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B> |
| Voxtral Mini 4B Realtime 2602 | 4.4B | Apache-2.0 | Streaming | Both | vLLM and llama.cpp `/v1/realtime` | <https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602> |
| Qwen3-ASR 0.6B | 0.9B | Apache-2.0 | Streaming in vLLM | (not checked) | Also on OpenVINO GenAI | <https://huggingface.co/Qwen/Qwen3-ASR-0.6B> |
| Riva Translate 4B Instruct v2 | 4.2B | **not verified** | Text MT | (not checked) | Served by NeMo-Speech.cpp `/v1/translations` | <https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2> |

## Fit to each hardware level

- **Laptop (Core Ultra 7 258V, Arc 140V, NPU, 32 GB shared).**
  - Documented NPU/GPU ASR: OVMS only (class A/B).
  - Possible live (class C) options: NeMo-Speech.cpp on Vulkan or CPU, and
    WhisperLive with the OpenVINO backend. Arc performance is not verified for
    either.
  - Translation: llama.cpp (Vulkan or SYCL) with a small text LLM, or
    NeMo-Speech.cpp `/v1/translations`.
  - speaches runs here on CPU only.
- **Remote A (11 GB VRAM, 128 GB RAM).**
  - Choices: NeMo-Speech.cpp CUDA (Nemotron 3.5 ASR Streaming plus Nemotron 3
    Diarization), speaches CUDA, vLLM with Qwen3-ASR-0.6B realtime, and
    llama.cpp CUDA for translation.
  - NIM is excluded (it needs ≥16 GB VRAM).
  - Voxtral 4B Realtime in BF16 is tight.
- **Remote B (16 GB VRAM, 128 GB RAM).**
  - Everything in Remote A, and also vLLM with Voxtral Realtime.
  - NIM is at its stated minimum.
  - Nemotron 3.5 Transcribe (offline) may fit only as FP8/NVFP4 or with CPU
    offload. This is not verified.

## Open questions for the decision tickets

1. **Protocol (#9/#10):** Adopt the OpenAI Realtime transcription event schema
   as the app's internal endpoint contract, with adapters for vLLM
   (`transcription.*`), NIM (`transcription_session.update`,
   `input_audio_buffer.done`) and class A servers (client VAD + POST)?
2. Does NeMo-Speech.cpp's realtime socket pass the `<xx-XX>` language tag of
   Nemotron 3.5 ASR through to `.completed` events, or does it strip it?
   (Not verified. It is needed for language switch detection.)
3. How fast are NeMo-Speech.cpp (Vulkan), llama.cpp (Vulkan, SYCL or
   OpenVINO) and vLLM XPU on the Arc 140V iGPU? How many parallel streams can
   the laptop handle? The OpenVINO NPU path in OVMS also needs a benchmark.
4. Streaming diarizers handle 4 speakers (Sortformer 4spk) or 8 speakers
   (Nemotron 3 Diarization). The project needs **at least 8 speakers**. Is 8
   enough, and how does a source with more speakers degrade?
5. What is the exact compute capability of Remote B, and does NIM start on a
   16 GB card at all? (This decides if NIM stays in scope.)
6. What is the Riva Translate 4B Instruct v2 licence, and what is its EN/FR
   quality compared with a general LLM on llama.cpp or vLLM?
7. Should Nemotron 3.5 Transcribe have a place as an optional post-session
   "refine" pass? If yes, which quantization fits on 16 GB, or on 11 GB plus
   128 GB RAM?
8. speaches has no stable tag in 2026. Is its maintenance level acceptable
   for a dependency?
