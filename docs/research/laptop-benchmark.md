# Laptop benchmark: streaming ASR and diarization

Ticket: [Measure streaming ASR and diarization speed on the laptop](https://github.com/gdevenyi/live-transcribe-translate/issues/13). Measured on 2026-10-29.

## Question

Can this laptop run Nemotron 3.5 ASR Streaming 0.6B and Nemotron 3 Diarization through NeMo-Speech.cpp in real time, on CPU and on Vulkan? What are the real-time factor, the latency and the memory use, for one source and for several sources at the same time?

## Short answer

- **Yes, on Vulkan (Arc 140V), for 3 sources at the same time, with diarization**, if the server runs with `--asr.batching.enabled=false`. The latency for 3 sources is the same as for 1.
- **CPU: only 1 source.** With 2 sources on the CPU, the server falls behind: word latency grows to 35–40 s and the transcript is not complete.
- **Partial text is live:** partials arrive p50 0.0 s, p95 0.08 s, maximum 0.35 s behind the audio (1 source, Vulkan).
- **Finals (with speaker labels) arrive about 1 s after the end of each utterance** (p50 0.96 s, maximum 1.12 s on Vulkan, with 800 ms endpointing; CPU p50 1.52 s). A word's final latency is therefore the rest of its utterance plus about 1 s. In the AMI test, the longest utterance was 14.6 s, so the maximum word latency was 15.6 s.
- **Bug: dynamic batching across realtime sessions is broken on Vulkan.** With batching on (the server default) and 2 sessions, the server once aborted with `GGML_ASSERT(ne3 == ne13) failed` (`ggml-cpu.c:1280`), and in a second run it gave no output at all. This happens with diarization on or off. With batching off, it works.
- **Endpointing is off by default** in `nemo-speech serve` (`asr.endpointing.enable=false`). Without `--asr.endpointing.enable=true` there is only one final, at the end of the stream; the `endpointing_ms` session field alone does not switch it on.
- **No language field.** The realtime events (`.delta`, `.completed`, and the words) carry no language code or language tag. The French text was correct with no language hint, but the app does not get the language from this endpoint.
- **Diarization quality on the test file:** 5 speakers found (3 AMI English speakers and 2 French speakers), with the same result on CPU and Vulkan. One final can hold words from two speakers (each word has its own `speaker`), so the app must split finals by word speaker.

## Setup

- Laptop: Intel Core Ultra 7 258V (Lunar Lake, 8 cores, AVX2 and AVX-VNNI), Arc 140V iGPU (Mesa Vulkan driver, API 1.4.354), 32 GB RAM. About 7 GB of RAM was free; other programs were running.
- Runtime: NeMo-Speech.cpp v0.2.0 prebuilt `linux-x86_64-cpu` and `linux-x86_64-vulkan` archives, SHA-256 checked against the release.
- Models: `nemotron-3.5-asr-streaming-0.6b.q8_0.gguf` (742 MB) and `Nemotron-3-Diarization.q8_0.gguf` (107 MB) from the NVIDIA Hugging Face repos. Default streaming chunk 160 ms.
- Audio (16 kHz mono):
  - `en_ami`: 60 s of the AMI meeting EN2002d (CC BY 4.0, from the NeMo-Speech.cpp test files); 3 speakers and brief overlap.
  - `fr`: 2 clips from 2 speakers of Multilingual LibriSpeech French (CC BY 4.0), 28 s.
  - `en_fr`: `en_ami` followed by `fr`, 88 s, with a language switch.
  - `long_10min`: `en_fr` repeated 7 times, 614 s.
- Scripts in [`laptop-benchmark/`](laptop-benchmark/):
  - `run_bench.sh`: the offline benchmarks with `nemo-speech bench`.
  - `rt_matrix.sh` and `rt_client.py`: the realtime tests. `rt_client.py` streams each source as 80 ms PCM16 frames at real time to `/v1/audio/transcriptions/realtime`, with `word_timestamps` and `speaker_diarization` on.

## Results: `nemo-speech bench` (no real-time pacing)

| Test | CPU | Vulkan |
|---|---|---|
| Streaming ASR, 88 s `en_fr` | 1.85× real time; chunk mean 86 ms, p95 102 ms, max 167 ms | 2.87× real time; chunk mean 55 ms, p95 69 ms, max 113 ms |
| Streaming ASR, 614 s `long_10min` | 2.43× real time; chunk mean 66 ms, p95 79 ms | 5.27× real time; chunk mean 30 ms, p95 38 ms |
| Streaming diarization, 88 s | 5.9× real time | 29× real time |
| Peak host memory (RSS), ASR | ~1.0 GB | ~0.2 GB (the model is in GPU memory, which is shared RAM on this laptop) |
| Peak host memory (RSS), diarization | ~0.18 GB | ~0.11 GB |

Model load time is about 0.1 s. The tool's "warmup" (55–174 s) is one full timed pass over the input, not model loading.

The `-c 2` rows of `bench` used one input item, so they do not measure two streams. The realtime tests below measure real concurrent sources.

## Results: realtime server, sources streamed at 1× speed, diarization on, endpointing on (800 ms)

| Config | Sources | Server | Finals per source | Word latency p50 / p95 / max | Utterance end → final p50 / max | Speakers |
|---|---|---|---|---|---|---|
| Vulkan, batching on | 1 | OK | 20 | 2.12 / 12.08 / 15.6 s | 0.96 / 1.12 s | 5 |
| Vulkan, batching on | 2 | **no output** (an earlier run aborted with `GGML_ASSERT`) | 1, 0 words | — | — | — |
| Vulkan, batching on, diarization off | 2 | **no output** | 1, 0 words | — | — | — |
| Vulkan, batching off | 2 | OK | 20 | 2.08 / 11.96 / 15.5 s | 0.97 / 1.12 s | 5 |
| **Vulkan, batching off** | **3** | **OK** | 20 | 2.14 / 12.0 / 15.6 s | — | 5 |
| CPU, batching on | 1 | OK | 20 | 2.77 / 12.59 / 16.1 s | 1.52 / 2.12 s | 5 |
| CPU, batching on | 2 | OK but falls behind | 15 (incomplete) | 12.2 / 33.9 / 35.5 s | — | 3 (incomplete) |
| CPU, batching off | 2 | OK but falls behind | 13 (incomplete) | 13.5 / 38.3 / 39.7 s | — | 3 (incomplete) |

"Word latency" is the arrival time of the final that holds the word, minus the time the word ended in the audio. It includes the wait until the utterance ends. "Utterance end → final" is the processing delay: the arrival time minus the end time of the last word of each final.

The 3-source test was not run on the CPU, because 2 sources already fell behind.

## Consequences for the decision tickets

- **Model choice:** on the laptop, use the Vulkan build. NeMo-Speech.cpp with Nemotron 3.5 ASR Streaming and Nemotron 3 Diarization serves at least 3 sources with diarization, in real time. The CPU build is a fallback for one source only.
- **Endpoint configuration:** the server must start with `--asr.endpointing.enable=true --asr.batching.enabled=false` (until the batching bug is fixed upstream).
- **Endpoint contract and timeline:** speaker labels come only with finals, and finals come at the end of an utterance. A long monologue (14.6 s here) has no final and no speaker until it ends. The live text before that must show as partial text (for example in a provisional place for the source) and move into the speaker's column when the final arrives. The 2–5 s "finalized segment" target holds for typical utterances (median 1.8 s), not for long monologues.
- **Language:** this endpoint gives no language per segment. Language switch detection needs another source, for example text language identification on each final in the app, or a different endpoint.
- **Finals with several speakers:** the app must split a final by the per-word `speaker`.

## Not done

- WhisperLive with OpenVINO and OVMS on the NPU (optional in the ticket): not measured.
- Battery and thermal behaviour over a long session: not measured.
- Speaker-label stability (relabels before a final): not measured; this endpoint sends speakers only on finals.
- The upstream batching bug is not reported yet.
