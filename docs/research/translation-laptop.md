# Laptop benchmark: Riva-Translate in NeMo-Speech.cpp next to live ASR

Ticket: [Measure Riva-Translate in NeMo-Speech.cpp on the laptop next to ASR](https://github.com/gdevenyi/live-transcribe-translate/issues/25). Measured on 2026-10-30 (the valid rerun; the first runs were discarded because a build and an ACPI event storm loaded the laptop).

## Question

Is NeMo-Speech.cpp `/v1/translations` with `nvidia/Riva-Translate-4B-Instruct-v2` fast and good enough on the laptop for live translation of segments? Target from [Choose the translation approach](https://github.com/gdevenyi/live-transcribe-translate/issues/12): under about 1 s per segment, and the ASR stays in real time.

## Short answer

- **1 source: yes, on Vulkan.** With one live ASR session, translation p50 is 0.74 s (max 2.7 s for a 30-word segment), and the ASR stays in real time (final 0.96 s after the utterance end, p50).
- **2 sources: no.** Shared on the Arc iGPU, translation p50 is 1.2 s (max 5.2 s), but the ASR degrades: partial lag p95 about 4 s and finals up to 6 s after the utterance end. With translation on the CPU, the ASR stays in real time, but translation p50 is 4.6 s (max 12.6 s).
- **3 sources: no.** Shared on the GPU, the ASR falls 20–38 s behind. On the CPU, translation p50 is 6.8 s (max 19.6 s), and the ASR partial lag p95 reaches 12 s.
- **Latency grows with segment length**: short segments take 0.3–0.9 s, and the longest (about 30 words) 2.4–2.7 s even with no load.
- **Quality is good** for this test. The main errors come from the ASR text ("à quicomte" became "To whom would I have to pay to be released?") and from missing context ("we died" became "nous sommes morts").
- `--nmt.backend.gpu -1` in the Vulkan build did **not** move translation to the CPU (same latency as on the GPU). The CPU numbers come from the separate CPU-only build.

## Setup

- Laptop: Core Ultra 7 258V, Arc 140V (Vulkan), 32 GB RAM. NeMo-Speech.cpp v0.2.0 prebuilt archives.
- Model: `nvidia/Riva-Translate-4B-Instruct-v2`, converted with the project's `convert_model.py` (v0.2.0 checkout) to `riva-translate-4b-instruct-v2.q8_0.gguf` (4.4 GB). Licence: NVIDIA Open Model License.
- Segments: the 20 NeMo finals of the 88 s English/French test audio (15 English, 5 French), with their recorded final times. `nmt_bench.py` sends each one with `source_language` and `target_language` (en→fr, fr→en).
- `alone`: segments one after another. `live N`: N ASR sessions stream the audio at 1× (`rt_client.py`, diarization on), and N translation streams each post every segment at its recorded final time.
- Setup A: one Vulkan server with ASR, diarization and NMT (`--threads 8`, endpointing on, batching off). Setup B: the same ASR server without NMT, plus a CPU-build server with only NMT.
- `rerun.sh` started each run only when CPU user+system was under 10 %, and logged it before and after (`rerun.log`).

## Results

| Setup | Sources | Translation p50 / p95 / max | ASR partial lag p95 | ASR utterance end → final p50 / max | ASR finals (of 20) |
|---|---|---|---|---|---|
| A, translation only | — | 0.73 / 2.35 / 2.40 s | — | — | — |
| A, ASR only (control) | 3 | — | 0.21–0.24 s | 0.96–1.09 / 1.26 s | 20 |
| A | 1 | 0.74 / 2.68 / 2.70 s | 0.52 s | 0.96 / 2.64 s | 20 |
| A | 2 | 1.16 / 3.31 / 5.18 s | 3.75–4.05 s | 1.84–1.90 / 6.21 s | 20 |
| A | 3 | 1.86 / 5.64 / 7.92 s | 31–33 s | 21–25 / 38 s | 14 |
| B, translation only (CPU) | — | 1.95 / 5.33 / 5.83 s | — | — | — |
| B | 1 | 2.15 / 5.91 / 6.11 s | 0.07 s | 0.96 / 1.03 s | 20 |
| B | 2 | 4.59 / 8.67 / 12.64 s | 0.09 s | 0.96 / 1.04 s | 20 |
| B | 3 | 6.82 / 13.99 / 19.58 s | 11.8–12.0 s | 1.00–1.07 / 8.0 s | 18 |

Every translation and its latency: [translations_alone.md](translation-laptop/translations_alone.md). Raw data: `translation-laptop/rerun/`.

## Consequences for "Choose the translation approach"

Riva-Translate-4B on the laptop meets the target only with **one** source. Options for more sources (for the user to decide):
- Translate only some sources, or only when there is one source.
- Run translation at the configurable alternative endpoint (a machine with a real GPU), keeping the same API.
- A smaller model (for example Hy-MT2 1.8B through an OpenAI-compatible server, or Opus-MT on the CPU), not measured here.

## Not measured

- Riva-Translate on monster or epic.
- BLEU or COMET on this test set (the French source is read speech with no reference translation).
- `nmt.pool.contexts` greater than 1 (default 1: translation requests are served one at a time).
