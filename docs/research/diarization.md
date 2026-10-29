# Research: Survey streaming diarization

Ticket: [#4](https://github.com/gdevenyi/live-transcribe-translate/issues/4). Map: [#1](https://github.com/gdevenyi/live-transcribe-translate/issues/1).
Date of research: 2026-10-29. Feeds decision tickets #9 (build new or fork) and #10 (ASR and diarization per hardware level).

## Question

Which diarization options work in a streaming way with 2–5 s latency and support at least 8 speakers in one session? Include NVIDIA Sortformer (streaming), diart, pyannote, NeMo and others, and joint ASR+diarization models. For each: maximum speakers, latency, how speaker identities stay stable over a long session, how it handles overlapping speech, licence, and hardware needs for the levels in the map.

## Short answer

- **Recommended: NVIDIA Nemotron 3 Diarization** (`nvidia/Nemotron-3-Diarization`; the Hub also resolves the lower-case slug `nvidia/nemotron-3-diarization`). It is the only open model found that meets all hard requirements together: it streams, it has 0.32–1.04 s input-buffer latency, it supports **8 speakers**, it has no session-length limit, and it has a permissive licence (OpenMDW-1.1). Release date: 2026-09-23. Size: 100M parameters. [model card](https://huggingface.co/nvidia/Nemotron-3-Diarization)
- It runs in three runtimes: NeMo (PyTorch, CUDA), Hugging Face Transformers (streaming API), and **NeMo-Speech.cpp** (ggml; CPU, CUDA, Vulkan, Metal). NeMo-Speech.cpp has a realtime WebSocket server that tags words with speakers. NVIDIA ships an official Q8_0 GGUF (107 MB) in the model repo. This gives a possible path for the laptop (CPU or Vulkan on Arc 140V), but laptop speed is **not verified**.
- **Fallback for more than 8 speakers, or when an NVIDIA-family model is not wanted: diart** (MIT). It streams with 0.5–5 s latency and has `max_speakers=20` by default. But it has maintenance risk: last release v0.9.2 is from 2025-02, it pins NumPy < 2, and pyannote 4.0 support is an open issue.
- **Not suitable as the live diarizer:**
  - Streaming Sortformer 4spk v2/v2.1: maximum 4 speakers. Nemotron 3 Diarization replaces it.
  - pyannote.audio `community-1`: an offline whole-file pipeline. It is not streaming. diart is the streaming wrapper for pyannote models.
  - Nemotron 3.5 Transcribe 30B-A4B: the card says it is an offline model.
  - VibeVoice-ASR-Streaming (joint ASR and diarization, 2.0 s): the released checkpoints target recordings of **at most 8 minutes**.
- **Best ASR pairing with Nemotron 3 Diarization** (NVIDIA guide): `nvidia/nemotron-3.5-asr-streaming-0.6b`. It is multilingual (40 locales, English and French included) and uses masked ASR per speaker. The other option, `multitalker-parakeet-streaming-0.6b-v1`, gives better overlap handling but is **English only**. Because the project needs French, the Nemotron 3.5 ASR pairing is the default.
- **Latency budget fits.** All NVIDIA latency numbers are *input-buffer* latency and do not include compute time. On an RTX PRO 5000, compute is fast (RTFx 38 eager / 164 compiled at the 1.04 s setting). On the remote GPUs, total latency of about 1–2 s for diarization is realistic. On the laptop it is not measured.
- **UI note.** Speaker labels can change for a short time before they become stable. NeMo-Speech.cpp says this "can take up to 10 s with V2". The "finalized segments" design must hold back speaker assignment, or allow a late relabel, for some seconds.

## Comparison table

"Latency" is the input-buffer (algorithmic) latency from the source. It does not include compute time unless this table says so.

| Option | Type | Streaming | Latency | Max speakers | ≥ 8 spk? | Session length | Overlap | Licence | Status / version |
|---|---|---|---|---|---|---|---|---|---|
| **Nemotron 3 Diarization** | E2E diarizer (Sortformer family) | Yes | 0.32 / 0.64 / 1.04 s (30.4 s offline mode) | 8 | **Yes** | Unlimited with chunked inference | Native multi-label output (T × 8) | OpenMDW-1.1 | Released 2026-09-23 |
| Streaming Sortformer 4spk v2.1 | E2E diarizer | Yes | 0.32 / 1.04 s (30.4 s offline mode) | 4 | No | Long-form; can degrade on very long audio | Native multi-label output (T × 4) | NVIDIA Open Model License | Superseded by Nemotron 3 Diarization |
| diart (`SpeakerDiarization`) | Segmentation + embedding + incremental clustering | Yes | 0.5–5 s (configurable; step 0.5 s, window 5 s) | 20 (default, configurable) | **Yes** | Unlimited | Segmentation model detects up to 2 simultaneous speakers out of 3 local speakers per window | MIT (code); MIT segmentation-3.0; gated pyannote weights | v0.9.2, 2025-02-12; NumPy < 2 |
| pyannote.audio `community-1` | Segmentation + embedding + clustering | **No** (offline pipeline) | n/a | Not fixed; `max_speakers` option | Yes (offline) | Whole file | Overlap-aware; also "exclusive" output | CC-BY-4.0 (weights); MIT (code) | pyannote.audio 4.0.7, 2026-06-30 |
| NeMo cascaded (VAD + TitaNet + clustering + MSDD) | Cascaded | Not documented as streaming | n/a | Not stated | Unknown | Whole file | MSDD handles overlap | Apache-2.0 (code) | Older NeMo path |
| Nemotron 3.5 Transcribe 30B-A4B | Speech-LLM, joint ASR + speaker tags | **No** ("offline model") | n/a | Prompt example uses 4 tags | Unverified | ≤ 1 h per request | Speaker-tagged words | OpenMDW-1.1 | 2026; needs 1× H100 80 GB |
| VibeVoice-ASR-Streaming 1.5B / 7B | Speech-LLM, joint ASR + diarization | Yes | 2.00 s expected attribution latency (2.9 s chunk + 0.5 s lookahead) | Not stated | Unknown | **≤ 8 min** (released checkpoints) | Serialized: overlap becomes consecutive segments | MIT | Paper 2026-09 |
| Multitalker Parakeet streaming 0.6B v1 | Speaker-conditioned streaming ASR (needs a diarizer) | Yes | Set by ASR context (`[70,13]`) | Follows diarizer (8 with Nemotron 3 Diarization) | With Nemotron 3 Diarization | Unlimited | Best: one ASR stream per speaker | NVIDIA Open Model License | **English only** |
| sherpa-onnx speaker diarization | Segmentation + embedding + clustering (ONNX) | **No** (only `offline-speaker-diarization` examples) | n/a | Cluster count or threshold | Yes (offline) | Whole file | pyannote segmentation-3.0 | Apache-2.0 | v2.0.1, 2026-10-26 |

## Option details

### 1. NVIDIA Nemotron 3 Diarization (recommended)

Source: [model card](https://huggingface.co/nvidia/Nemotron-3-Diarization), [ASR integration guide](https://huggingface.co/nvidia/Nemotron-3-Diarization/blob/main/ASR_INTEGRATION_GUIDE.md), [Hugging Face blog](https://huggingface.co/blog/nvidia/nemotron-diarization), [demo Space](https://huggingface.co/spaces/nvidia/nemotron-diarization).

- **What it is.** An end-to-end streaming diarizer that follows Sortformer. Architecture: 31-layer Transformer encoder with RoPE, 80 ms encoder frames, and output upsampled to 10 ms. 100M parameters. Release date 2026-09-23. (model card)
- **Max speakers.** 8. The output is `[T, 8]` per-speaker activity probabilities. Training data has mixtures of 1–8 speakers. (model card)
- **Latency.** Input-buffer latency is `(CHUNK_LEN + RIGHT_CONTEXT) × 80 ms`. Recommended presets: 1.04 s (low), 0.64 s (very low), 0.32 s (ultra-low), and 30.4 s (offline-like). Compute time is not included. (model card)
- **Speed (measured by NVIDIA on RTX PRO 5000, BF16).** RTFx at batch size 1, eager / `torch.compile`: 38 / 164 at 1.04 s; 12.5 / 54 at 0.32 s. Streaming Sortformer v2.1 gets 16 / 42 at 1.04 s. (model card)
- **Accuracy (DER, collar 0 s unless noted).** At 1.04 s latency: DIHARD III full 13.18 (5–9 speakers: 28.65); NOTSOFAR1 SC full 12.77 (5–7 speakers: 15.44); AMI SDM 12.80; CALLHOME part 2 (collar 0.25 s) 10.29. The 4-speaker v2.1 model at 1.04 s gives 19.60, 31.81, 21.73 and 11.31 on the same sets. (model card)
- **Speaker identity over a long session.** The model uses an Arrival-Order Speaker Cache (AOSC) and a FIFO queue. The AOSC keeps embeddings of speakers it saw before, so speaker identities stay the same across chunks. Output channels are ordered by the first arrival of each speaker. With chunked inference, the maximum audio duration is not limited. (model card; [Streaming Sortformer paper, arXiv 2507.18446](https://arxiv.org/abs/2507.18446))
- **Label stability.** NeMo-Speech.cpp documents that, in live mode, "Speaker labels can change until the diarizer confirms them, which can take up to 10 s with V2." The same document does not give a number for V3 (Nemotron 3 Diarization). ([NeMo-Speech.cpp CLI guide](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/cli.md))
- **Overlap.** The output is multi-label: each of the 8 channels is an independent probability per 10 ms frame. Two or more speakers can be active in the same frame. (model card)
- **Labels are anonymous.** The guide says speaker numbers "do not identify real-world names". The application must map numbers to names (in our domain: Speaker → Display name). (ASR integration guide)
- **Languages.** Training data includes English, Mandarin, Hindi, Kannada, Telugu, Bengali and multilingual sets (VoxConverse, DIHARD, CALLHOME, YODAS-v2). The card gives no French-specific evaluation. **French accuracy is not verified.** (model card)
- **Licence.** OpenMDW-1.1. The card says the model "is ready for commercial or non-commercial use". (model card)
- **Runtimes.**
  - NeMo (`SortformerEncLabelModel`), NeMo Framework v3.0, Python ≥ 3.12. The model card lists supported hardware as NVIDIA GPUs from Ampere and newer, on Linux. (model card)
  - Hugging Face Transformers (from source): `AutoModelForAudioFrameClassification`, with a streaming API that passes `speaker_cache` from chunk to chunk. (model card)
  - NeMo-Speech.cpp (Apache-2.0, ggml): `nemo-speech diarize`, and `nemo-speech transcribe --live --diarize`. Its server has `WebSocket /v1/audio/transcriptions/realtime` with `speaker_diarization: true`, and `POST /v1/audio/diarizations`. The docs say "V2 supports up to four speakers and V3 up to eight". Build presets exist for `cpu`, `cuda`, `metal` and `vulkan`, including `vulkan-diar` and `<backend>-server`. The converter supports Sortformer v3 checkpoints. The NVIDIA repo has an official `Nemotron-3-Diarization.q8_0.gguf` (107 MB). ([README](https://github.com/NVIDIA/NeMo-Speech.cpp), [API](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/api.md), [build](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/build.md), [converter](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/conversion/diarization.py), [HF files](https://huggingface.co/nvidia/Nemotron-3-Diarization/tree/main))
- **ASR pairing (NVIDIA guide).** The coupled streaming pipeline `SpeakerTaggedASR` in NeMo Speech (`speech_to_text_multitalker_streaming_infer.py`) has two options:
  - Option 1: `multitalker-parakeet-streaming-0.6b-v1`, `masked_asr=false`. English only. Best for overlap.
  - Option 2: `nemotron-3.5-asr-streaming-0.6b`, `masked_asr=true`, `target_lang=auto`. 40 language-locales, including `en` and `fr`. The guide says it can recognize overlapped speech "to a certain degree".
  - `max_num_of_spks=8`. `cache_gating=true` runs speaker-specific ASR only for speakers that were active recently, which reduces compute.
  - The guide shows how to build a live WebSocket service. It uses one session for each client, and model weights can be shared. The guide calls the example script "an offline streaming replay and evaluation driver". (ASR integration guide; [Nemotron 3.5 ASR card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b))

### 2. NVIDIA Streaming Sortformer 4spk v2 / v2.1

Source: [v2.1 model card](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1).

- 117M parameters. FastConformer (NEST) encoder + 18-layer Transformer, with 4 sigmoid outputs.
- **Max 4 speakers.** The card says that "performance degrades on recordings with 5 and more speakers". This **fails the 8-speaker requirement**.
- Latency presets: 1.04 s (RTF 0.093 on RTX 6000 Ada) and 30.4 s. Speaker identity uses the same AOSC mechanism.
- The card says it is "primarily in English" and that performance "may degrade on very long recordings".
- Licence: NVIDIA Open Model License.
- The card now shows a notice that points to Nemotron 3 Diarization ("supporting 8 speakers and greatly improved accuracy"). Use it only if V3 does not work on some runtime.

### 3. diart (streaming pyannote)

Source: [GitHub juanmc2005/diart](https://github.com/juanmc2005/diart), [config source](https://github.com/juanmc2005/diart/blob/main/src/diart/blocks/diarization.py), paper: Coria et al., ASRU 2021, "Overlap-aware low-latency online speaker diarization based on end-to-end local segmentation".

- **Method.** A rolling 5 s window, updated every 0.5 s. A pyannote segmentation model does local diarization. Then an embedding model and **incremental clustering** assign each local speaker to a global speaker. The paper says that latency "can be adjusted between 500ms and 5s". (README)
- **Max speakers.** `max_speakers: int = 20` by default. It is configurable. (config source)
- **Latency.** `duration=5`, `step=0.5`, and `latency` in `[step, duration]`. (config source)
- **Speed.** The README lists per-chunk model times on an AMD Ryzen 9 CPU and an RTX 4060 Max-Q. For example, `pyannote/segmentation-3.0` takes 11 ms on CPU and 8 ms on GPU; `pyannote/embedding` takes 26 ms on CPU and 12 ms on GPU. It is CPU-capable.
- **Speaker identity over a long session.** Global speaker centroids are updated incrementally (`rho_update`). A new speaker is created when the distance is above `delta_new`. Cannot-link constraints stop the merge of two speakers that are in the same window. Identity drift depends on the tuned `tau/rho/delta` values. The README gives different values for DIHARD III, AMI and VoxConverse.
- **Overlap.** The segmentation model is overlap-aware. `pyannote/segmentation-3.0` uses powerset classes that allow up to 3 speakers per 10 s chunk and up to 2 speakers at the same time. ([segmentation-3.0 card](https://huggingface.co/pyannote/segmentation-3.0)). diart also uses overlap-aware statistics pooling.
- **Licence.** Code: MIT. `pyannote/segmentation-3.0`: MIT, gated (you must accept terms on the Hub).
- **Maintenance risk (facts):**
  - Last release v0.9.2, 2025-02-12. The last push to the repo was 2026-06-19. ([GitHub API](https://api.github.com/repos/juanmc2005/diart))
  - `numpy>=1.20.2,<2.0.0` pin. ([setup.cfg](https://github.com/juanmc2005/diart/blob/main/setup.cfg))
  - Open issue [#282 "Pyannote 4.0.0"](https://github.com/juanmc2005/diart/issues/282), since 2025-10-01.
  - The README says that to reproduce the paper results, you should install `pyannote.audio<3.1`.
  - WhisperLiveKit marks its diart profile "[Not recommended]". It is limited to Python 3.11 and 3.12 "because Diart 0.9.2 requires NumPy below 2". WhisperLiveKit recommends Sortformer instead. ([WhisperLiveKit README](https://github.com/QuentinFuxa/WhisperLiveKit))
- **Accuracy.** The paper table is an image in the README. Numbers are not transcribed here. They come from 2021 and use older models.

### 4. pyannote.audio and `speaker-diarization-community-1`

Source: [pyannote/pyannote-audio](https://github.com/pyannote/pyannote-audio), [community-1 card](https://huggingface.co/pyannote/speaker-diarization-community-1).

- pyannote.audio 4.0.7 (2026-06-30). MIT. Requires Python ≥ 3.11 and torch ≥ 2.8.
- `community-1` is a whole-file pipeline (`pipeline("audio.wav")`). It has `num_speakers`, `min_speakers` and `max_speakers` options. The README does not document a streaming mode. The only streaming reference is a 2021 VAD blog post. **It is not a streaming diarizer.** For streaming, use it through diart, or as an offline re-diarization pass after the session ends.
- DER (collar 0, overlap included, 2025-09): AMI SDM 19.9, DIHARD 3 full 20.2, CALLHOME part 2 26.7, VoxConverse 11.2. (card)
- Licence: CC-BY-4.0 for the pipeline weights, gated.
- `precision-2` / `precision` are pyannoteAI **cloud** pipelines (API key). A self-hosted version is for enterprise only. ([precision card](https://huggingface.co/pyannote/speaker-diarization-precision))

### 5. NeMo cascaded diarizer (clustering + MSDD)

Source: [NeMo speaker diarization models](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/models.html).

- The docs describe this pipeline: VAD, then speaker embeddings, then clustering, then the Multi-Scale Diarization Decoder (MSDD). The docs give no maximum speaker count. The docs do not call it streaming. For streaming, the same page shows only Sortformer and Streaming Sortformer.
- It is not a candidate for live use. It can be an offline re-diarization option.

### 6. Joint ASR + diarization models

**Nemotron 3.5 Transcribe 30B-A4B** ([card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B)). This is the seed model from the map.
- The card says: "**This is an offline model.** Internal audio chunking does not make it a real-time streaming ASR service."
- It does speaker-attributed transcription with `<spk:N>` tags. The prompt example lists 4 tags. Mean cpWER is 15.80 on AMI, CALLHOME, Mixer 6 and NOTSOFAR-1.
- It handles recordings up to 1 h. It is deployed on 1× H100 80 GB. FP8 and NVFP4 variants exist. Licence: OpenMDW-1.1.
- It **does not qualify** as the live diarizer. It can be an end-of-session "re-transcribe and re-diarize" pass on a large GPU. It does not fit Remote A or B in BF16 (34B total parameters).

**VibeVoice-ASR-Streaming 1.5B / 7B** (Microsoft; [7B card](https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-7B), [tech report arXiv 2609.02812](https://arxiv.org/abs/2609.02812)).
- One LLM (Qwen2.5 backbone) interleaves audio chunks and speaker-attributed text. It has no separate diarization stage. Speakers get ordinal labels "in order of first appearance", and a label "is reused whenever that speaker is recognized again". (report §3.1)
- Latency: 2.9 s chunks + 0.5 s lookahead. Expected speaker-attribution latency is 2.00 s; with 15-frame chunks it is 1.53 s. (report §3.1, §4)
- 10 languages, including English and French. French on MLC-Challenge: WER 16.42, cpWER 21.50. (report Table 2)
- Overlap: "simultaneous speech is emitted as consecutive labeled segments rather than as parallel streams". (report §3.1)
- **Blocker:** "Keeping the history uncompressed has a cost that grows linearly with recording length … the released checkpoints target recordings of up to eight minutes." (report §3.1)
- The card and report do not state a maximum speaker count.
- Licence: MIT.
- **Hardware (estimate, not measured):** the 7B model in BF16 needs about 15 GB of weights alone. It does not fit Remote A (11 GB) without quantization. Community AWQ and GGUF quantizations exist on the Hub. They are not verified here.
- **It does not qualify** for long live sessions.

**Multitalker Parakeet streaming 0.6B v1** ([card](https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1)).
- This is a speaker-conditioned ASR model. It is not a diarizer. "Speaker kernels" from diarizer activity steer one ASR stream for each speaker. The card says it needs "one model instance per speaker". It handles fully overlapped speech.
- English only (per the Nemotron 3 Diarization integration guide).
- Licence: NVIDIA Open Model License.
- Use it only for English-only diarize sources if overlap accuracy is important.

### 7. Others checked

- **sherpa-onnx** (Apache-2.0, v2.0.1, 2026-10-26). The Python examples contain only `offline-speaker-diarization.py`. It uses pyannote segmentation-3.0 and 3D-Speaker or NeMo embeddings in ONNX. It is not streaming. ([repo](https://github.com/k2-fsa/sherpa-onnx/tree/master/python-api-examples), [docs](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html))
- **WhisperLiveKit** (Apache-2.0). This is an application, not a model. Its diarization backends are Streaming Sortformer / NeMo 3 (recommended) and diart (not recommended). This is relevant to ticket #9 (fork or build). ([README](https://github.com/QuentinFuxa/WhisperLiveKit))
- **Cloud services** (Azure ConversationTranscriber, Google STT, pyannoteAI). These are out of scope because the map wants self-hosted endpoints. The VibeVoice report measured an average speaker-attribution latency of 8.21 s for Azure CT and 9.12 s for Google STT (first label). Google labels are "still being revised tens of seconds later". (report §4)

## Fit to hardware levels

| Level | Nemotron 3 Diarization | diart | Notes |
|---|---|---|---|
| **Laptop** (Core Ultra 7 258V, Arc 140V, NPU, 32 GB, no NVIDIA) | Possible through NeMo-Speech.cpp `cpu` or `vulkan` build, using the official Q8_0 GGUF (107 MB). **Real-time speed on this CPU or iGPU is not verified.** NeMo (PyTorch) and the Transformers path list only NVIDIA GPUs. | Runs on CPU (model times are about tens of ms per 0.5 s step on a desktop Ryzen 9). Intel XPU support through PyTorch is not verified. | No source shows OpenVINO or NPU support for either model. Test NeMo-Speech.cpp `bench diarize` on the laptop first. |
| **Remote A** (11 GB VRAM, 128 GB RAM) | Fits easily: 100M parameters, about 0.2 GB in BF16 (estimate from the 199 MB `.nemo` file). Room is left for `nemotron-3.5-asr-streaming-0.6b` (600M). | Fits easily. | VRAM for multi-speaker ASR streams grows with active speakers; `cache_gating` limits it. Exact VRAM is not measured. |
| **Remote B** (16 GB VRAM, 128 GB RAM) | Fits easily, with more headroom for several sources and sessions. | Fits easily. | VibeVoice-7B BF16 (about 15 GB weights, estimate) would just fit, but the 8-minute limit rules it out. |

## Open questions for downstream tickets

For **#10 (ASR and diarization per hardware level)**:
1. **Laptop speed.** Does NeMo-Speech.cpp run Nemotron 3 Diarization faster than real time at the 1.04 s preset on the Core Ultra 7 258V CPU, or on Arc 140V through Vulkan, together with streaming ASR? Measure it with `nemo-speech bench diarize`. If it is too slow, the laptop must use diart on CPU (max 20 speakers) or send "diarize" sources to a remote endpoint.
2. **French accuracy.** No source gives a French DER for Nemotron 3 Diarization. Test it on a French multi-speaker recording, with a language switch inside the session.
3. **A 9th speaker.** The model has 8 fixed output channels. The sources do not say what happens when a 9th speaker arrives: a merge with an existing channel, or a drop. Test this. If the app must support more than 8 speakers per source, diart is the only streaming option found.
4. **Which ASR pairing.** Coupled `SpeakerTaggedASR` with Nemotron 3.5 ASR (masked, multilingual) or a separate ASR with diarization labels merged by timestamp? The coupled path gives better overlap handling, but ties the app to NeMo (Python, CUDA) on the endpoint.

For **#9 (build new or fork)**:
5. NeMo-Speech.cpp already has a realtime WebSocket server with speaker-tagged words, and an OpenAI-style REST API. Can it be the inference endpoint without changes? The app would then only be a client.
6. WhisperLiveKit already integrates Sortformer diarization and simultaneous translation. Does it support Nemotron 3 Diarization (8 speakers) now, or only the 4-speaker v2?

For the **app design** (both tickets):
7. **Label settling time.** Speaker labels can change for up to about 10 s (documented for V2; not documented for V3). How long must the app wait before it puts a Segment into a final Column, and does the UI allow a late move between Columns?
8. **Multiple sources.** Diarization runs per Source. Speaker numbers from two "diarize" sources are independent. The app must map (Source, speaker number) to a Column and a Display name. Is a cross-source speaker merge needed (for example, the same person on the mic and on a call), or is manual merge in the UI enough?
9. **Offline re-diarization.** Should the app run an optional end-of-session pass (pyannote `community-1`, Nemotron 3 Diarization in 30.4 s mode, or Nemotron 3.5 Transcribe) to correct labels in the saved Session?

## Sources (primary)

- Nemotron 3 Diarization model card and ASR integration guide: https://huggingface.co/nvidia/Nemotron-3-Diarization
- Streaming Sortformer 4spk v2.1 model card: https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1
- Streaming Sortformer paper: https://arxiv.org/abs/2507.18446
- Nemotron 3.5 ASR streaming 0.6B card: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b
- Multitalker Parakeet streaming card: https://huggingface.co/nvidia/multitalker-parakeet-streaming-0.6b-v1
- Nemotron 3.5 Transcribe 30B-A4B card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B
- NeMo-Speech.cpp README, CLI, API, build docs, converter: https://github.com/NVIDIA/NeMo-Speech.cpp
- NeMo diarization docs: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/models.html
- diart repo and source: https://github.com/juanmc2005/diart
- pyannote.audio repo: https://github.com/pyannote/pyannote-audio
- pyannote community-1 card: https://huggingface.co/pyannote/speaker-diarization-community-1
- pyannote segmentation-3.0 card: https://huggingface.co/pyannote/segmentation-3.0
- VibeVoice-ASR-Streaming card and report: https://huggingface.co/microsoft/VibeVoice-ASR-Streaming-7B , https://arxiv.org/abs/2609.02812
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx
- WhisperLiveKit: https://github.com/QuentinFuxa/WhisperLiveKit
