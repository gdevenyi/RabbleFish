# Research: streaming multilingual ASR models

Ticket: [#3 Survey streaming multilingual ASR models](https://github.com/gdevenyi/live-transcribe-translate/issues/3)
Date of research: 2026-10-29. Sources are model cards, official repositories and official docs, read on that date.

## Question

Which ASR models can do near-live (2–5 s) transcription of English and French, with language switch detection and word or segment timestamps?

Include NVIDIA Nemotron 3.5 Transcribe 30B-A4B, Parakeet, Canary, Whisper large-v3-turbo, Voxtral, Qwen ASR and others. For each model, give:

- streaming support
- languages
- code-switching
- accuracy
- licence
- whether it runs on each hardware level: laptop (Arc iGPU, NPU, CPU), remote A (11 GB VRAM, 128 GB RAM), remote B (16 GB VRAM, 128 GB RAM), including quantization and MoE expert offload

Also: does any model give speaker labels itself?

## Short answer

1. **Primary live model: NVIDIA Nemotron 3.5 ASR Streaming 0.6B** (`nvidia/nemotron-3.5-asr-streaming-0.6b`, released 2026-06-04, OpenMDW-1.1).
   - It is a native cache-aware streaming model. Chunk size goes from 80 ms to 1.12 s.
   - It has 40 language-locales. English and French (fr-FR, fr-CA) are in the top "transcription-ready" tier.
   - With `language=auto` it detects the language and adds a tag such as `<fr-FR>` to each utterance.
   - It has punctuation and capitalization, and word timestamps on an 80 ms grid.
   - The Q8_0 GGUF file is 742 MB. It runs on CPU, Vulkan or CUDA through NVIDIA's NeMo-Speech.cpp runtime (Apache-2.0).
   - That runtime has a realtime WebSocket endpoint. The endpoint can also add speaker labels from Nemotron 3 Diarization (up to 8 speakers, streaming).
   - It fits all three hardware levels.
2. **Accuracy-first live alternative: Mistral Voxtral Mini 4B Realtime 2602** (Apache-2.0).
   - It is a native streaming model with a configurable delay of 80 ms to 2.4 s.
   - On FLEURS at 480 ms delay, the WER is 4.90 % for English and 6.42 % for French.
   - It needs a GPU with 16 GB or more for the BF16 weights in vLLM. Thus it fits remote B. It does not fit remote A without quantization, and quantization is not documented.
   - The card does not document language identification, a language tag or word timestamps.
3. **NVIDIA Nemotron 3.5 Transcribe 30B-A4B is offline only.** It is not a live model.
   - The model card says: "This is an offline model. Internal audio chunking does not make it a real-time streaming ASR service."
   - It has the best accuracy, code-switching for EN/FR, word timestamps and built-in speaker labels (up to 8).
   - The smallest documented configuration needs a GPU with 24 GB. Thus it does not fit the 11 GB or 16 GB GPUs.
   - It can run CPU-only in NeMo-Speech.cpp. NeMo-Speech.cpp does not expose partial or MoE expert offload.
   - Use it only for a later "refine" pass on finished segments or a full Session, if at all.
4. **Speaker labels from the model itself:**
   - Nemotron 3.5 Transcribe gives speaker labels (offline, up to 8).
   - Multitalker Parakeet Streaming 0.6B gives speaker labels, but it is English only, needs a separate diarizer and needs one model instance per speaker.
   - For live EN/FR, use ASR plus a separate streaming diarizer (Nemotron 3 Diarization). NeMo-Speech.cpp joins the two in one endpoint.
5. **Language switch detection:**
   - Nemotron 3.5 ASR Streaming detects the language per utterance (between finalized segments). It does not detect a switch inside one utterance.
   - True in-utterance code-switching for EN/FR is documented only for the offline Nemotron 3.5 Transcribe.
6. **Laptop NPU:** no candidate streaming model has a documented NPU path. The NPU path is Whisper through OpenVINO GenAI (`STATIC_PIPELINE`). Whisper is not natively streaming. Use the CPU (or Vulkan on the Arc iGPU) for the laptop.

## Comparison table

WER values come from each vendor's model card. Text normalization is different between cards, so compare numbers only roughly. "FLEURS" means the FLEURS test set.

| Model (version, date) | Params | Streaming | EN/FR | Language ID / code-switching | Timestamps | Speaker labels | WER EN / FR (FLEURS) | Licence | Laptop (CPU / Arc / NPU) | Remote A 11 GB | Remote B 16 GB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Nemotron 3.5 ASR Streaming 0.6B** (2026-06-04) | 0.6B | Native, cache-aware RNNT, 80 ms–1.12 s chunks | Yes / Yes (fr-FR, fr-CA) | `auto` mode: one language tag per utterance. In-utterance switch: not documented | Word, 80 ms grid (RNNT emission) | No (add a diarizer) | 7.91 / 9.03 at 1.12 s chunk, LangID given. 8.84 / 9.02 auto | OpenMDW-1.1 | Yes: CPU, Vulkan (q8_0 GGUF 742 MB). NPU: no path | Yes | Yes |
| **Voxtral Mini 4B Realtime 2602** (created 2026-01-21) | ~4B (3.4B LM + encoder) | Native, 80 ms–2.4 s delay | Yes / Yes (13 languages) | Not documented | Not documented | No | 4.90 / 6.42 at 480 ms. 4.05 / 5.23 at 2.4 s | Apache-2.0 | Unclear: Transformers ≥5.2, ONNX community port, C port. No documented Intel GPU path | No documented path (BF16 needs ≥16 GB) | Yes (vLLM, BF16, ≥16 GB) |
| **Nemotron 3.5 Transcribe 30B-A4B** (2026-10-28) | 34B total, 4.3B active | **No (offline)** | Yes / Yes, "Leading" tier | LID; code-switching marked for EN and FR | Word (CTC head) | **Yes, built in, up to 8** | 3.35 / 3.16 (offline) | OpenMDW-1.1 | CPU/Vulkan IQ4_NL only, offline, untested at this size | No (min. documented 24 GB) | No (min. documented 24 GB) |
| **Parakeet TDT 0.6B v3** (2025-08-14) | 0.6B | Buffered chunks only (NeMo script, e.g. `chunk_secs=2`) | Yes / Yes (25 EU languages) | Auto language detection | Word, segment, char | No | — / 5.15 | CC-BY-4.0 | CPU via NeMo-Speech.cpp offline only (streaming rejected) | Yes (NeMo) | Yes (NeMo) |
| **Canary 1B v2** (2025-08-14) | 0.98B | No (offline, chunked long-form) | Yes / Yes (25 EU languages) | Source language must be given | Word, segment | No | MLS FR 3.36 | CC-BY-4.0 | CPU possible (≥6 GB RAM), not live | Yes | Yes |
| **Qwen3-ASR 1.7B / 0.6B** (2026-01-28) | 1.7B / 0.6B | Yes, vLLM backend only. No batch, no timestamps in streaming | Yes / Yes (30 languages + 22 dialects) | Built-in LID | Only with separate Qwen3-ForcedAligner-0.6B, offline | No | Not on card for FR. Streaming costs ~0.6–1.1 WER points on EN | Apache-2.0 | OpenVINO 2026.4 runs Qwen3-ASR on CPU/GPU | Yes | Yes |
| **Whisper large-v3-turbo** | 809M | No. Needs a wrapper (whisper_streaming ~3.3 s, SimulStreaming) | Yes / Yes (99 languages) | LID per 30 s window | Segment, word | No | Not checked | MIT | Yes: whisper.cpp Vulkan / OpenVINO encoder. NPU via OpenVINO GenAI | Yes | Yes |
| **Kyutai STT 1B en_fr** | ~1B | Native, 0.5 s delay, semantic VAD | Yes / Yes (EN and FR only) | Not documented | Word | No | Not checked | CC-BY-4.0 | No documented Intel path (Rust CUDA, PyTorch, MLX) | Probably (Rust server, CUDA) | Probably |
| **Multitalker Parakeet Streaming 0.6B v1** | 0.6B | Native | English only (training data) | — | — | **Yes, with external Sortformer; one instance per speaker** | — | NVIDIA Open Model Licence | Not documented | Possibly (NeMo, CUDA) | Possibly |
| **Granite Speech 5.0 470M TurboCTC** (2026-10-21) | 470M | Not documented | Yes / Yes (7 languages) | Not documented | Not documented | No | Not checked | Apache-2.0 | Card says suited for laptops | Yes | Yes |
| **Granite Speech 5.0 2B** (2026-10-20) | 2B | No (speech LLM) | Yes / Yes | Language given by prompt | Not on card for this model | No | Not checked | Apache-2.0 | GGUF exists (llama.cpp) | Yes | Yes |

## Per-option details

### NVIDIA Nemotron 3.5 ASR Streaming 0.6B (recommended live model)

Source: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b

- Release: Hugging Face, 06/04/2026 (card, "Release Date").
- Architecture: cache-aware FastConformer encoder (24 layers) with an RNNT decoder and language-ID prompt conditioning. It has 600M parameters (card, "Model Architecture").
- The card says it is "the multilingual extension of nvidia/nemotron-speech-streaming-en-0.6b". It supports "40 language-locales".
- English (en-US, en-GB) and French (fr-FR, fr-CA) are in the "Transcription-ready (19 locales)" tier.
- Latency is set at run time with `att_context_size`. The chunk sizes are 80 ms, 160 ms, 320 ms, 560 ms and 1.12 s. You do not need to retrain the model to change it.
- Language switch: "When run with `target_lang=auto`, the model detects the spoken language and emits the corresponding language code/tag in the output following the terminal punctuation." The card adds that this lets one deployment "automatically label each utterance with its detected language".
  - Thus the granularity is per utterance. The card does not describe a switch inside one utterance. This is unverified.
- Accuracy, FLEURS WER (%), from the card table:

  | Chunk | EN (LangID) | FR (LangID) | EN (auto) | FR (auto) |
  |---|---|---|---|---|
  | 80 ms | 9.43 | 10.97 | 9.72 | 11.03 |
  | 320 ms | 8.27 | 9.79 | 8.84 | 9.84 |
  | 1.12 s | 7.91 | 9.03 | 8.84 | 9.02 |

  The card says that normalization is "not perfect across all 40 language-locales". Mismatches can make the reported error rates higher.
- Punctuation and capitalization are built in (card, "Why Choose").
- Licence: OpenMDW-1.1 (https://openmdw.ai/license/1-1/). This is a permissive licence. It grants rights "without restriction". The only condition is that you keep the licence and notices when you distribute. The patent and copyright grant ends if you sue about the model materials. It puts no restrictions on outputs.
- Runtimes:
  - NeMo (Python, CUDA)
  - Hugging Face Transformers (streaming example on the card)
  - NeMo-Speech.cpp, with a ready `nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` (742,090,464 bytes, from the HF file list)
- Word timestamps in NeMo-Speech.cpp: "decoder emission positions on the encoder frame grid (80 ms for the shipped models), as in NeMo, not a forced alignment" (https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/asr/configuration.md).

### NeMo-Speech.cpp runtime (serves the NVIDIA models)

Source: https://github.com/NVIDIA/NeMo-Speech.cpp (Apache-2.0, created 2026-07-15, latest release v0.2.0 on 2026-10-02, pushed 2026-10-29)

- Supported ASR models: Nemotron 3.5 ASR Streaming 0.6B, Nemotron Speech Streaming 0.6B (EN), Parakeet TDT 0.6B v3 and Parakeet CTC 1.1B. It also runs Nemotron 3.5 Transcribe 30B-A4B "for complete recordings".
- Diarization: Streaming Sortformer 4-speaker v2 and Nemotron 3 Diarization (8 speakers), "standalone or combined with ASR" (README).
- Backends: CPU, CUDA, Metal and Vulkan (README and docs/build.md).
- Benchmark (BENCHMARK.md): the English sibling model, Nemotron Speech Streaming 0.6B (Q8_0) with 160 ms chunks, takes 27 ms per chunk on an Intel Core i7-11700K with 8 threads (6× real time). It takes 2.3 ms on an RTX 4090. There is no benchmark for the multilingual 3.5 model, Intel Arc or Lunar Lake.
- Server (docs/server.md, docs/api.md): `nemo-speech serve` has these endpoints:
  - `POST /v1/audio/transcriptions` (OpenAI-compatible subset)
  - `WebSocket /v1/audio/transcriptions/realtime` for "live PCM16 transcription"
  - `POST /v1/audio/diarizations`
- Realtime session fields (docs/api.md): `language`, `automatic_punctuation`, `word_timestamps` ("word timings on final events"), `speaker_diarization` ("tag words with speakers; requires a loaded diarizer") and `endpointing_ms`.
  - The server sends partial results (`...delta`) and final results (`...completed`).
  - This matches the project needs: finalized segments, word timings and speaker tags.
- SALM models (Nemotron Transcribe) "send one `error` with code `streaming_unsupported` on connect" to the realtime socket.
- Parakeet TDT v3: "does not support cache-aware streaming; inference is full-utterance only. Streaming requests are rejected" (docs/asr/models.md).

### Nemotron 3 Diarization (companion for speaker labels)

Source: https://huggingface.co/nvidia/Nemotron-3-Diarization

- Release: September 23, 2026. Licence: OpenMDW-1.1.
- It has 99.2M parameters (from the seed blog). It does streaming and offline diarization and "handles up to eight speakers".
- Speakers are ordered by first arrival. A speaker cache keeps the identities stable over time.
- Streaming input buffer latency: 0.32 s, 0.64 s or 1.04 s (recommended presets). 80 ms is the lowest possible value. This does not include compute time.
- NeMo-Speech.cpp default V3 streaming preset: chunk 13 frames + right context 1 frame of 80 ms, which is 1.12 s (docs/asr/models.md).
- Training data includes 21 languages (David AI D12) and simulated 1–8 speaker mixtures.

### Voxtral Mini 4B Realtime 2602 (Mistral)

Source: https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602 (repo created 2026-01-21. Paper: arXiv 2602.11298)

- "Natively streaming architecture and a custom causal audio encoder". The delay is configurable "from 80ms to 2.4s". The recommended delay is 480 ms.
- It supports 13 languages, including English and French. It has a ≈3.4B language model. The BF16 safetensors file is 8.86 GB.
- FLEURS WER (card):

  | Delay | EN | FR |
  |---|---|---|
  | 160 ms | 6.46 | 9.75 |
  | 480 ms | 4.90 | 6.42 |
  | 960 ms | 4.34 | 5.68 |
  | 2400 ms | 4.05 | 5.23 |

- Serving: vLLM (recommended) with the realtime WebSocket API. The card says it "can run on a single GPU with >= 16GB memory". "A single text-token is worth 80ms."
- Other runtimes: Transformers ≥ 5.2.0, ExecuTorch (untested) and community ports (voxtral.c, Rust, MLX). An `onnx-community/Voxtral-Mini-4B-Realtime-2602-ONNX` port exists.
- Licence: Apache-2.0.
- Gaps: the card does not document language identification output, a language tag or timestamps. Speaker labels: no.
- Hardware fit:
  - Remote B (16 GB): yes, per the card. Note that this leaves little headroom when other services also use the GPU.
  - Remote A (11 GB): no documented path. A quantized vLLM run (for example FP8) is not documented for this model. This is unverified.
  - Laptop: no documented Intel GPU or NPU path. CPU speed for a 4B model in real time is unknown.

### NVIDIA Nemotron 3.5 Transcribe 30B-A4B (seed model)

Sources: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B and https://huggingface.co/blog/nvidia/nemotron-transcribe-granary

- Release: 10/28/2026 (card) on Hugging Face, GitHub, build.nvidia.com and NGC. Licence: OpenMDW-1.1.
- Architecture: a speech-augmented LLM. Parts:
  - Nemotron-3.5 Lightning 30B-A3B hybrid Mamba-Transformer MoE backbone
  - 600M ASR encoder
  - ~99M Nemotron-3-Diarization speaker encoder
  - CTC timestamp head
  - 34B parameters total and 4.3B active.
- **Offline only.** The card says: "This is an offline model. Internal audio chunking does not make it a real-time streaming ASR service." The blog says: "Transcribe is built for recorded audio, not live streaming."
- Languages: 40. English and French (France, Canada) are "Leading" quality, with ASR, translation, multispeaker ASR and code-switching all marked supported.
- Accuracy (card):
  - FLEURS WER: EN 3.35, FR 3.16
  - Multilingual Open ASR French mean: 3.92
  - Open ASR English mean: 4.71
  - LID accuracy: FLEURS FR 100.00, EN 99.69
- Speaker labels: prompt with `<spk:0> … <spk:3>` (extend to `<spk:7>`). With vLLM timestamp capture, the response has a `ctc_timestamps` object. It holds word start and end times, a speaker tag per word, diarization segments and a tag-to-diarizer mapping.
  - The blog says it labels "up to eight speakers".
  - Multi-speaker cpWER: AMI IHM 10.29, AMI SDM 17.34, NOTSOFAR-1 SC 25.91.
- Limits for this project:
  - Timestamp requests need `stream=false` and one recording per request.
  - The vLLM quick start targets "one H100 80 GB".
  - The hardware table lists only A100 80GB, H100/H200, L40S 48GB, RTX 5090 (NVFP4), RTX PRO 6000 and Blackwell systems.
- Sizes (HF file list): the NVFP4 repo has 9.99 GB + 9.19 GB LLM shards, a 1.34 GB MTP file and 0.84 GB perception weights. That is about 21 GB.
- NeMo-Speech.cpp (docs/salm/configuration.md, docs/salm/models.md):
  - The defaults fit a 32 GB GPU.
  - The smallest row is "24 GB" with an IQ4_NL decoder, `max_sequences: 4`, `mtp_draft: 0`, and a longest request of 29 minutes.
  - CPU and Vulkan run "llama.cpp's standard path" with an IQ4_NL decoder and no speculative decoding.
  - Batched CUDA serving needs compute capability ≥ 8.0 and CUDA ≥ 12.8.
- MoE expert offload: `src/speechlm/salm_engine.cpp` sets `n_gpu_layers = cfg.gpu >= 0 ? 999 : 0`. That is all layers on the GPU or none. There is no documented partial offload or `--cpu-moe` style expert offload in NeMo-Speech.cpp.
  - Hugging Face Transformers `device_map="auto"` can spill weights to CPU RAM. It is not documented for this model at small VRAM sizes and will be slow. This is unverified.
- Hardware fit:
  - Remote A (11 GB) and remote B (16 GB): no. The weights (~17–21 GB at 4-bit) are larger than the VRAM, and there is no supported expert offload.
  - CPU-only with 128 GB RAM: possible through NeMo-Speech.cpp CPU, offline. There are no published timings.
  - Laptop (32 GB shared): the IQ4_NL decoder plus encoder may fit in memory. It is offline and untested. It is not a live option.

### Parakeet TDT 0.6B v3

Source: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

- Release: 08/14/2025. Licence: CC-BY-4.0. It has 600M parameters and 25 European languages, including English and French.
- "The model automatically detects the language of the audio and transcribes it without requiring additional prompting."
- It gives word, segment and character timestamps, and punctuation and capitalization.
- French WER: FLEURS 5.15, MLS 4.97, CoVoST2 6.05 (card model-index).
- Streaming: only buffered chunked inference with the NeMo script `speech_to_text_streaming_infer_rnnt.py` (example `chunk_secs=2`). It is not cache-aware. NeMo-Speech.cpp rejects streaming for it.
- Fit: a 2–5 s chunked pipeline on any CUDA GPU is plausible. On the laptop, NeMo-Speech.cpp runs it offline on CPU per chunk. Chunk-to-chunk text stitching is the client's job.

### Canary 1B v2

Source: https://huggingface.co/nvidia/canary-1b-v2

- Release: 08/14/2025. Licence: CC-BY-4.0. It has 978M parameters and 25 European languages. It does ASR and EN↔X translation.
- You must pass `source_lang` and `target_lang` when you call it. The card does not document automatic language detection.
- It gives word and segment timestamps (segment only for translation). MLS French WER: 3.36. It needs at least 6 GB RAM.
- It is offline with "dynamic chunking with 1-second overlap" for long-form audio. It is not a streaming model.
- Fit: not a live candidate. It could be a translation option for the translation ticket.

### Qwen3-ASR 1.7B and 0.6B

Source: https://huggingface.co/Qwen/Qwen3-ASR-1.7B (created 2026-01-28. Paper: arXiv 2601.21337)

- Licence: Apache-2.0. It does "language identification and ASR for 52 languages and dialects" (30 languages + 22 Chinese dialects), including English and French.
- Streaming: "Qwen3-ASR fully supports streaming inference. Currently, streaming inference is only available with the vLLM backend. Note that streaming inference does not support batch inference or returning timestamps."
- Timestamps: only with the separate `Qwen3-ForcedAligner-0.6B` (11 languages, including French, up to 5 minutes), offline.
- Streaming vs offline WER on the card table (LibriSpeech clean | other, FLEURS-en, FLEURS-zh):
  - 1.7B offline 1.63 | 3.38, 3.35, 2.41
  - 1.7B streaming 1.95 | 4.51, 4.02, 2.84
- Intel: OpenVINO 2026.4.0 release notes list Qwen3-ASR on CPU and GPU. OpenVINO GenAI 2026.3.0 added "Qwen3-ASR" and an `ASRPipeline` (https://github.com/openvinotoolkit/openvino.genai/releases). The NPU is not listed for Qwen3-ASR.
- Fit: remote A and B through vLLM. Laptop through OpenVINO (CPU, Arc), but OpenVINO streaming for Qwen3-ASR is documented only for the Node.js ASRPipeline. The Python path is unverified.

### Whisper large-v3-turbo

Source: https://huggingface.co/openai/whisper-large-v3-turbo

- Licence: MIT. It is Whisper large-v3 with the decoder pruned from 32 to 4 layers. It has 99 languages.
- Timestamps: sentence-level (`return_timestamps=True`) and word-level (`return_timestamps="word"`).
- Not streaming. It processes 30 s windows. Live use needs a wrapper:
  - whisper_streaming (LocalAgreement): the authors report "3.3 seconds latency" (https://github.com/ufal/whisper_streaming). The README says it "is becoming outdated, replaced by SimulStreaming".
  - SimulStreaming (MIT, https://github.com/ufal/SimulStreaming): about "5-times faster" than whisper_streaming.
- Intel laptop paths:
  - whisper.cpp v1.9.5 (2026-10-06) has Vulkan support and an OpenVINO encoder on "x86 CPUs and Intel GPUs" (https://github.com/ggml-org/whisper.cpp).
  - OpenVINO GenAI `WhisperPipeline` accepts `"NPU"` as a device. The NPU needs `STATIC_PIPELINE` (https://openvinotoolkit.github.io/openvino.genai/docs/use-cases/speech-recognition).
  - The Intel NPU driver release notes list Lunar Lake (Core Ultra Series 2).
  - One user reports 49.8× real time for Whisper base.en INT8 on the Lunar Lake NPU (https://github.com/elizaOS/eliza/issues/7633). This is a single report and is unverified.
- Hallucination on silence and repeated text are known Whisper risks with chunked live use. This project did not test them.

### Kyutai STT 1B en_fr

Sources: https://huggingface.co/kyutai/stt-1b-en_fr and https://github.com/kyutai-labs/delayed-streams-modeling

- Licence: CC-BY-4.0. "An English and French model with ~1B parameters, a 0.5 second delay, and a semantic VAD."
- It is native streaming and returns word-level timestamps.
- Production server: the Rust `moshi-server` over WebSocket, built with `--features cuda`. "On a L40S GPU, we can serve 64 simultaneous connections at a real-time factor of 3x."
- The README does not document a language tag or behaviour on mixed EN/FR audio.
- Fit: a good EN/FR-only option on the CUDA remotes. There is no Intel GPU or NPU runtime (Rust CUDA, PyTorch, MLX only). VRAM need is not stated for the 1B model. This is unverified.

### Multitalker Parakeet Streaming 0.6B v1

Source: https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1

- Licence: NVIDIA Open Model Licence (`nvidia-open-model-license`). It is based on the English Nemotron Speech Streaming model. The training data on the card is English (for example Fisher, CallHome American English).
- It injects "speaker kernels" from a streaming Sortformer diarizer. "The model architecture requires deploying one model instance per speaker."
- Fit: it gives speaker-attributed streaming text, but only for English. Eight speakers would mean eight instances. Not suitable for EN/FR.

### Granite Speech 5.0 (IBM)

Sources: https://huggingface.co/ibm-granite/granite-speech-5.0-470m-turboctc and https://huggingface.co/ibm-granite/granite-speech-5.0-2b

- 470M TurboCTC: Apache-2.0, released October 21, 2026. It covers EN, FR, DE, ES, PT, IT and JA. It is a CTC conformer described as "well suited for deployment on laptops". The card does not document streaming or timestamps.
- 2B: Apache-2.0, released October 20, 2026. It is a speech LLM for ASR and translation. The language is given in the prompt. A llama.cpp GGUF (`granite-speech-5.0-2b-GGUF`) exists. It is not streaming.
- Fit: too new to have streaming evidence. Watch it.

## Hardware fit summary

### Level 1: laptop (Core Ultra 7 258V, Arc 140V, NPU, 32 GB shared)

- **Best fit:** Nemotron 3.5 ASR Streaming 0.6B q8_0 in NeMo-Speech.cpp, on the CPU build. The Vulkan build is an option.
  - The 742 MB file is small.
  - The English sibling model runs at 6× real time on an 8-thread desktop CPU.
  - Several Sources need several streams. Measure how many streams the 258V can run (4 P-cores + 4 E-cores).
  - Vulkan on Arc 140V is supported by ggml in general. NeMo-Speech.cpp Vulkan has not been tested on Arc for this model. This is unverified.
- Add Nemotron 3 Diarization (q8_0) for "diarize" Sources. Measure the extra CPU load.
- NPU: only Whisper through OpenVINO GenAI has a documented NPU path. It is not natively streaming.
- Not practical: Nemotron 3.5 Transcribe (offline, ~17–21 GB) and Voxtral Realtime (4B BF16, no Intel path).

### Level 2: remote A (11 GB VRAM, 128 GB RAM)

- Nemotron 3.5 ASR Streaming 0.6B with diarization: yes, with much headroom. Use the NeMo-Speech.cpp CUDA build or NeMo.
- Qwen3-ASR 1.7B streaming (vLLM): yes.
- Kyutai STT 1B en_fr: probably yes.
- Voxtral Realtime 4B: not in BF16 (the card says ≥ 16 GB). Quantized serving is not documented.
- Nemotron 3.5 Transcribe 30B-A4B: no on the GPU. CPU-only offline with 128 GB RAM is possible but has no timings.
- The GPU model is not known. If it is a pre-Ampere GPU (for example compute capability 7.5), these limits apply:
  - NeMo-Speech.cpp batched SALM needs CC ≥ 8.0.
  - BF16 kernels are not available.
  - Nemotron 3.5 ASR Streaming lists Turing and Volta as supported (card, hardware list), so it still works.

### Level 3: remote B (16 GB VRAM, 128 GB RAM)

- All of level 2.
- Voxtral Mini 4B Realtime in vLLM BF16: yes, per the card (≥ 16 GB). The GPU then has little room for other models.
- Nemotron 3.5 Transcribe 30B-A4B: no. The smallest documented NeMo-Speech.cpp row is 24 GB. The NVFP4 weights are ~21 GB. There is no MoE expert offload in NeMo-Speech.cpp.

## Does any model give speaker labels itself?

- **Nemotron 3.5 Transcribe 30B-A4B: yes, offline.** It has a built-in Sortformer speaker encoder, `<spk:N>` tags for up to 8 speakers, and word-level speaker tags with diarization segments.
- **Multitalker Parakeet Streaming 0.6B: yes, streaming, English only.** It needs an external Sortformer and one instance per speaker.
- **All other candidates: no.** For live EN/FR, pair the ASR with Nemotron 3 Diarization (streaming, 8 speakers, 0.32–1.04 s buffer). NeMo-Speech.cpp joins the two in one realtime WebSocket session (`speaker_diarization: true`).

## Open questions for the decision tickets

1. **Remote GPU models.** What are the exact GPUs (compute capability) on remote A and B? This decides BF16/FP8 support, vLLM support and the NeMo-Speech.cpp CUDA path.
2. **Endpoint protocol.** Which protocol should the app speak to an Endpoint?
   - NeMo-Speech.cpp realtime WebSocket (its own event protocol)
   - vLLM realtime API (Voxtral, Qwen3-ASR)
   - Kyutai moshi-server WebSocket
   - OpenAI-style `POST /v1/audio/transcriptions` on chunks

   One adapter per protocol is likely.
3. **Language switch granularity.** Is a per-utterance language tag (Nemotron 3.5 ASR `auto`) enough for the "Language switch" feature? If not, a switch inside a sentence needs a second pass.
4. **Optional refine pass.** Do we want an offline second pass with Nemotron 3.5 Transcribe (better accuracy, code-switching, speaker labels)? It needs ≥ 24 GB VRAM, or CPU-only on a 128 GB host, with unknown speed.
5. **Laptop backend.** CPU or Vulkan (Arc) for NeMo-Speech.cpp? How many concurrent streams with diarization does the 258V sustain inside 2–5 s?
6. **Measured accuracy on our audio.** Card WERs use different normalizations. Run a small EN/FR test set (including Canadian French and mixed EN/FR) through Nemotron 3.5 ASR Streaming, Voxtral Realtime and Kyutai STT.
7. **Diarization load.** The NeMo-Speech.cpp V3 preset uses a 1.12 s diarization chunk. Check that ASR plus diarization stays inside 5 s end to end.
8. **Licence notices.** OpenMDW-1.1 and CC-BY-4.0 need licence and attribution notices if we redistribute model files. They do not apply if users only download the models themselves.

## Unverified items (summary)

- In-utterance language switch behaviour of Nemotron 3.5 ASR Streaming, Voxtral Realtime and Kyutai STT.
- NeMo-Speech.cpp performance on Lunar Lake CPU and Arc 140V Vulkan.
- Quantized Voxtral Realtime on 11 GB.
- Nemotron 3.5 Transcribe CPU-only speed with 128 GB RAM.
- Whisper NPU speed on Lunar Lake (one user report only).
- Granite Speech 5.0 streaming support.
