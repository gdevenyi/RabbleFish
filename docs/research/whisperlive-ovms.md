# Laptop benchmark: WhisperLive (OpenVINO) and OVMS (GPU and NPU)

Ticket: [Measure WhisperLive (OpenVINO) and OVMS (NPU) on the laptop](https://github.com/gdevenyi/live-transcribe-translate/issues/17). Measured on 2026-10-29. Compare with [laptop-benchmark.md](https://github.com/gdevenyi/live-transcribe-translate/blob/research/laptop-benchmark/docs/research/laptop-benchmark.md) (NeMo-Speech.cpp).

## Question

Can WhisperLive with its OpenVINO backend, and OpenVINO Model Server (OVMS) with Whisper on the GPU or the NPU, serve live transcription on this laptop? How do they compare with NeMo-Speech.cpp on Vulkan?

## Short answer

- **OVMS with Whisper large-v3-turbo is fast and handles language switches, but it gives text only.** It returns no speakers, no language code and no timestamps. It is not a streaming server: the app must cut the audio into windows.
  - **GPU (INT8):** a 5 s window takes p50 0.3 s. With 3 sources, p50 0.55–0.6 s and maximum 0.98 s.
  - **NPU (FP16):** a 5 s window takes p50 0.56 s. With 3 sources, p50 up to 1.1 s and maximum 1.7 s. The NPU leaves the GPU free for other models.
  - **INT8 on the NPU fails** on every request ("Response generation failed").
  - **Language:** Whisper detects the language for each window. On the GPU, all English and French windows were correct. On the NPU, 1 of 6 French windows was translated into English.
  - **Windows cut words:** "près de lui" became "un bon. / de lui" at a window boundary. The app would need to cut at pauses (VAD), not at fixed times.
- **WhisperLive with the OpenVINO backend is not suitable for this project.**
  - It has no diarization. Only the `faster_whisper` backend gets a diarizer (`server.py`).
  - It has no language detection. If the client gives no language, the backend sets `"en"` (`openvino_backend.py`). With `en`, the French was sometimes translated into English. With `fr`, the English became mixed nonsense ("si vous askz me").
  - Speed on the Arc GPU is good: 3 sources, completed segments p50 2.4 s and maximum 8.7 s after the speech; partial text p50 0.2–0.6 s.
- **WhisperLive with the `faster_whisper` backend (CPU) and diarization is too slow and inaccurate:** with `small` and 1 source, completed segments arrived p50 10 s and maximum 21.6 s after the speech. It found 7 speakers where there are 5. It detected English once and locked the language, so it translated the French into English.
- **The NPU works inside the OVMS `-gpu` container with no host driver.** The image brings its own NPU user-space driver; the host needs only the `intel_vpu` kernel module and `/dev/accel`. Native OpenVINO on the host (pip) sees only CPU and GPU until `intel-npu-driver` is installed.

## Comparison with NeMo-Speech.cpp (same laptop, same 88 s English and French audio)

| | NeMo-Speech.cpp, Vulkan | OVMS, GPU | OVMS, NPU | WhisperLive OpenVINO, GPU |
|---|---|---|---|---|
| Model | Nemotron 3.5 ASR Streaming 0.6B Q8_0 + Nemotron 3 Diarization | Whisper large-v3-turbo INT8 | Whisper large-v3-turbo FP16 | Whisper large-v3-turbo INT8 |
| Protocol | realtime WebSocket | REST, file per request | REST, file per request | WebSocket |
| Live partial text | yes, p95 0.08 s | no (app windows) | no (app windows) | yes, p50 0.2–0.6 s |
| Time to final text | ~1 s after the utterance ends | window length + 0.3–1 s | window length + 0.6–1.7 s | segment p50 1.9–2.5 s, max 8.7 s |
| 3 sources in real time | yes (batching off) | yes | yes | yes |
| Speakers | yes, 8 max, per word | no | no | no |
| Language switch EN↔FR | correct text, no language code | correct, no language code | 1 of 6 FR windows translated | no (fixed language) |
| Word timestamps | yes | only with a graph option | only with a graph option | segment times |

## Setup

- Laptop and audio: as in [laptop-benchmark.md](https://github.com/gdevenyi/live-transcribe-translate/blob/research/laptop-benchmark/docs/research/laptop-benchmark.md) (`en_fr.wav`: 60 s AMI English meeting followed by 28 s French, 16 kHz mono).
- WhisperLive 0.10.0 (pip, Python 3.12) with `openvino` 2026.4.1 and `openvino-genai` 2026.4.1. Server `run_server.py` from tag v0.10.0. OpenVINO selected `GPU` (Arc 140V). Model `OpenVINO/whisper-large-v3-turbo-int8-ov`. Client [`wl_client.py`](whisperlive-ovms/wl_client.py) streams 256 ms int16 frames at real time with `use_vad: true`.
- OVMS `openvino/model_server:2026.4.1-gpu` under rootless Podman (`--device /dev/dri`, plus `--device /dev/accel` for the NPU, `--group-add keep-groups`). Models pulled with `--source_model`. Client [`ovms_client.py`](whisperlive-ovms/ovms_client.py) cuts each source into 5 s windows, posts each window to `/v3/audio/transcriptions` when its end is reached in real time (`temperature=0`, no `language`), one request at a time per source. Latency = result arrival − window end.
- NPU model compile time at OVMS start: about 2 min 15 s. Container memory with the FP16 model on the NPU: about 3.7 GB.

## Results

### WhisperLive, OpenVINO backend, GPU, large-v3-turbo INT8

| Run | Completed segment latency p50 / p95 / max | Partial latency p50 / p95 | Note |
|---|---|---|---|
| 1 source, `language=en` | 1.85 / 3.91 / 8.44 s | 0.19 / 3.70 s | French partly translated into English |
| 1 source, `language=fr` | 2.05 / 4.28 / 8.28 s | 0.20 / 4.01 s | English part became mixed French and English |
| 2 sources, `en` | 1.88–2.05 / 3.9–5.1 / 6.5 s | 0.36 / 2.6 s | this time the French stayed French |
| 3 sources, `en` | 2.36–2.56 / 4.6–5.7 / 8.7 s | 0.57–0.64 / 3.4–3.8 s | |

Each client loads its own model ("Single model mode currently only works with custom models"). The first connect took 18 s, including the download.

### WhisperLive, `faster_whisper` backend, CPU, `small`, auto language, diarization

1 source: completed segments p50 10.0 s, p95 20.3 s, max 21.6 s; partials p50 5.0 s. 7 speakers reported for 5 real speakers. Language reported once as `en`; the French was translated into English.

### OVMS, 5 s windows, automatic language

| Device / model | Sources | Request time p50 / max | Latency after window end p50 / max |
|---|---|---|---|
| GPU, INT8 | 1 | 0.31 / 0.81 s | 0.33 / 0.84 s |
| GPU, INT8 | 2 | 0.35–0.37 / 0.66 s | 0.36–0.37 / 0.66 s |
| GPU, INT8 | 3 | 0.32–0.60 / 0.97 s | 0.33–0.61 / 0.98 s |
| NPU, INT8 | 1 | — | every request failed: `S2tExecutor failed: Response generation failed` |
| NPU, FP16 | 1 | 0.56 / 0.63 s | 0.56 / 0.64 s |
| NPU, FP16 | 2 | 0.58–0.62 / 1.14 s | 0.59–0.63 / 1.15 s |
| NPU, FP16 | 3 | 0.64–1.09 / 1.69 s | 0.64–1.10 / 1.69 s |

The text of every window is in `results/ovms_*.json`.

## Consequences for the decision tickets

- **WhisperLive: rule out** as the laptop endpoint, because the OpenVINO backend has no diarization and no language detection, and the CPU backend with diarization is too slow.
- **OVMS on the NPU is a real option for text-only ASR**, for example for "single speaker" sources (a headset microphone). It leaves the GPU free for NeMo-Speech.cpp, which then serves only the "diarize" sources. The cost: the app must window the audio at pauses, there are no partials, and the NPU sometimes translated French into English.
- **Diarization on the laptop still needs NeMo-Speech.cpp** (Nemotron 3 Diarization). None of the OpenVINO paths gives speakers.
- **Language codes:** no tested laptop endpoint returns a language code. The app needs its own language identification on the text, or Whisper's detected language through another API.

## Not done

- OVMS with `enable_word_timestamps` and `stream=true` (partial results over SSE).
- OVMS on the CPU.
- WhisperLive with smaller OpenVINO models (`small`, `medium`).
- A VAD-based windowing client for OVMS; the fixed 5 s windows only show the speed.
