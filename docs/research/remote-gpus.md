# Remote GPU benchmark: streaming ASR options on monster and epic

Ticket: [Measure ASR options on the remote GPUs](https://github.com/gdevenyi/live-transcribe-translate/issues/18). Measured on 2026-10-29. The method and the audio are the same as in [laptop-benchmark.md](https://github.com/gdevenyi/live-transcribe-translate/blob/research/laptop-benchmark/docs/research/laptop-benchmark.md).

## Question

How do the ASR options compare on the two remote machines? The baseline is the laptop stack (NeMo-Speech.cpp with Nemotron 3.5 ASR Streaming 0.6B and Nemotron 3 Diarization). The bigger options are Voxtral Mini 4B Realtime, Qwen3-ASR 1.7B and Kyutai STT 1B.

## Short answer

- **NeMo-Speech.cpp with Nemotron is the only option that gives speakers.** It runs **8 sources** in real time on both machines and uses 1.2–1.5 GB of VRAM.
  - monster needs a CUDA build from source for `sm_61`. The prebuilt CUDA archive needs compute capability 7.5 or newer, and the Vulkan build handles only 4 sources.
  - Speaker labels come with finals, about 0.86 s after each utterance ends. In a long monologue a word can wait up to 15.5 s for its final.
  - WER: English 19–20 %, French 12.9 %.
- **Voxtral Mini 4B Realtime (epic only)** is the most accurate in French (WER **2.9 %**), and its text arrives about **0.42 s** (p50, maximum 1.0 s) after the speech, with no long-monologue wait.
  - It has no speakers, no language code and no per-utterance finals.
  - It takes about 13.8 GB of the 16 GB. NeMo with diarization still fits next to it (about 1 GB left), with no slowdown for either.
- **Kyutai STT 1B en_fr (epic only)** is nearly as good in French (WER **2.9 %**), the weakest of the good options in English (26.2 %), and has low latency: each word arrives final about 0.41 s (p50) after the speech, maximum 1.4 s.
  - It needs only 3.7 GB of VRAM, so NeMo with diarization fits easily next to it (5.1 GB in total).
  - The first French words after the switch were wrong ("But on a second siècle"). It has no speakers and no language code.
  - It cannot run on monster: candle's kernels need compute capability 7.0 or newer.
- **Qwen3-ASR 1.7B: rule out.** It cuts the audio into fixed 5 s chunks with no context between them. It repeats itself ("Yeah." ×25), and its WER is 36 % in English and 20 % in French. It is the only option with language tags, one per chunk.
- **No ASR option gives speakers except NeMo.** A bigger model on epic therefore means two streams per source: text from the bigger model, speakers from NeMo. The app must then match words to speaker turns by time.
- **The NeMo server needs `--threads` at least equal to the number of sources.** The default 4 refuses the 5th realtime session at the handshake.

## Comparison (88 s `en_fr.wav`: 60 s AMI English meeting, then 28 s French read speech)

| | NeMo, laptop Vulkan | NeMo, monster Vulkan | NeMo, monster CUDA (sm_61) | NeMo, epic CUDA | Voxtral 4B Realtime, epic | Kyutai STT 1B, epic | Qwen3-ASR 1.7B, epic |
|---|---|---|---|---|---|---|---|
| Sources in real time (tested) | 3 | 4 (6 falls behind) | **8** | **8** | 3 | 3 | 3 |
| Live text delay | partials ~0.08 s | partials ≤ 0.24 s (4 src) | partials ≤ 0.14 s | partials ≤ 0.03 s | words ~0.42 / 0.82 / 0.98 s* | words 0.41 / 0.89 / 1.37 s* | words 1.74 / 4.12 / 5.39 s* |
| Final after utterance end, p50 | 0.96 s | 0.89–1.12 s | 0.87–0.96 s | 0.85–0.88 s | no per-utterance finals | each word is final | per 5 s chunk |
| Word latency incl. waiting for the final, p50 / max | 2.1 / 15.6 s | 2.1 / 15.7 s | 2.0 / 15.6 s | 2.0 / 15.5 s | = live delay | = live delay | = live delay |
| WER English (AMI) | 20.6 % | 20.6 % | 19.1 % | 19.9 % | 21.3 % | 26.2 % | 36.2 % |
| WER French (MLS) | 10.0 % | 12.9 % | 12.9 % | 12.9 % | **2.9 %** | **2.9 %** | 20.0 % |
| EN→FR switch | correct | correct | correct | correct | correct | first words wrong | tag switches at 60 s |
| Language code | no | no | no | no | no | no | **yes** (per chunk) |
| Speakers | **yes** (5) | **yes** (5) | **yes** (5) | **yes** (5) | no | no | no |
| VRAM | shared | 1.07 GB | 1.23 GB | 1.4–1.5 GB | 13.8 GB (preallocated at 0.87) | 3.7 GB (batch 8), 10 GB (batch 64) | 7.2 GB (preallocated at 0.5) |
| Next to NeMo diarization | — | — | — | — | fits, 1.07 GB left | fits, 5.1 GB total | fits, 8.7 GB total |

\* p50 / p95 / max of the word arrival time minus the end time of the same word in the NeMo output. This is approximate: it depends on matching words between models, and on NeMo's own word times.

The WER test set is small: 141 English words of meeting speech with overlap, and 70 French words of read speech. The French figures say little about conversational French, and a difference of a few points in English is within noise. There was no real recording to test with.

## Setup

- **monster:** GTX 1080 Ti 11 GB (compute capability 6.1), driver 580, CUDA 12.9, 125 GB RAM, 40 cores.
- **epic:** RTX 5080 16 GB (compute capability 12.0), driver 615, CUDA 13.4, 123 GB RAM, 32 cores.
- **Audio, references and WER:** the same audio as the laptop benchmark. References: the AMI manual transcript (`ami_en2002d_2132.json`, segments in time order) and the MLS French text. [`wer.py`](remote-gpus/wer.py) lower-cases, removes punctuation and filler words, and runs `jiwer`.
- **Clients:** all clients send 80 ms frames at 1× real time.
  - NeMo: [`rt_client.py`](remote-gpus/rt_client.py), with `language: auto` and diarization on.
  - vLLM realtime: `epic/vllm_rt_client.py`.
  - Kyutai (msgpack, 24 kHz): `epic/kyutai_rt_client.py`.
- **Interference:** another GPU engine ran on both machines during the first runs. All those runs were discarded (on monster their VRAM peak was 7.3 GB, against 1.1 GB in clean runs).
  - Every reported run passed an idle check before and after the run, with no other compute process during the run (`gpucheck.txt` and `mon.txt` / `mem.log` in each run folder).
- **Software:**
  - NeMo-Speech.cpp v0.2.0, with `--asr.endpointing.enable=true --asr.batching.enabled=false` (batching breaks concurrent sessions: [NVIDIA/NeMo-Speech.cpp#89](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/89)).
    - monster Vulkan: the prebuilt archive.
    - monster CUDA: built from source with `scripts/configure.sh cuda-server -DCMAKE_CUDA_ARCHITECTURES=61` and `cmake --build --preset cuda-server`, after `scripts/build_sentencepiece_static.sh`. It took about 3 min.
    - epic CUDA: the prebuilt archive.
  - vLLM 0.32.0 from PyPI (torch 2.13.0+cu130) on epic.
  - moshi-server 0.6.4 on epic, built without the lockfile (cudarc 0.19.10 for CUDA 13.4, PyO3 against Python 3.12). It used the official `config-stt-en_fr-hf.toml` with `batch_size` 8.

## Details per option

### NeMo-Speech.cpp (Nemotron 3.5 ASR Streaming 0.6B Q8_0 + Nemotron 3 Diarization Q8_0)

- **monster, Vulkan:** 1–4 sources kept up. Partial lag p95 grew to 0.24 s at 4 sources. At 6 sources the GPU was at 99 %, and the final p50 rose to 1.1–2.0 s (maximum 4.3 s).
- **monster, CUDA sm_61:** 8 sources with partial lag p95 ≤ 0.06 s and final p50 ≤ 0.96 s. Peak GPU use was 14–64 %. More than 8 was not tested.
- **epic, CUDA:** 8 sources with GPU use up to 52 %. VRAM is 1.39 GB after start, peak 1.48 GB. RSS grew from 450 MB to 908 MB over many sessions on one server process (seen, not investigated).
- **Concurrent sessions:** the server's `--threads` (default 4) is the maximum number of concurrent realtime sessions. A 5th or later session fails with a handshake timeout.
- **Language:** no `language` field in any event, with `language: auto`. See [NVIDIA/NeMo-Speech.cpp#90](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/90).

### Voxtral Mini 4B Realtime (`mistralai/Voxtral-Mini-4B-Realtime-2602`)

- **Serve command:** `vllm serve mistralai/Voxtral-Mini-4B-Realtime-2602 --tokenizer-mode mistral --config-format mistral --load-format mistral --compilation-config '{"cudagraph_mode":"PIECEWISE"}' --max-model-len 2048 --gpu-memory-utilization 0.87`.
  - With `--max-model-len 8192` it fails: 5.22 GiB of KV cache is needed and only 2.15 GiB is available.
- **Memory:** weights 8.43 GiB, KV cache 3.77 GiB. 3 sources used about 26 % of the KV cache (sliding window).
- **Protocol:** `transcription.delta` events, then one `transcription.done` after the final commit. It has no per-utterance finals, no `audio_processed` and no language.
- **Text:** French after 61 s was correct ("Pendant le second siècle, je fis serment…").

### Kyutai STT 1B en_fr (`kyutai/stt-1b-en_fr`, candle files)

- **Delay:** the model has a fixed 0.48 s delay (6 × 80 ms). Each word arrives final, with no revisions.
- **Protocol:** Ready, Step (with 4 semantic voice-activity values), Word, EndWord and Marker. It has no language.
- **Batch size:** at batch_size 64 (official), VRAM is 10 GB, with the same latency for 1 source.
- **monster:** candle-kernels 0.9.2 fails in nvcc on `moe_wmma.cu` for `sm_61` (WMMA needs compute capability 7.0 or newer). Earlier blockers were fixed: the old cudarc did not know CUDA 12.9/13.4, and PyO3 refused Python 3.14.

### Qwen3-ASR 1.7B (`Qwen/Qwen3-ASR-1.7B`)

- **Serve command:** `vllm serve Qwen/Qwen3-ASR-1.7B --hf-overrides '{"architectures":["Qwen3ASRRealtimeGeneration"]}' --max-model-len 4096 --gpu-memory-utilization 0.5`.
- **How it works:** independent 5 s segments, with up to 64 tokens each, and a `language English<asr_text>…` prefix per segment.
- **Problems:** repetition loops. The output is not deterministic: 198, 246 and 248 words in three runs of the same input.

## Consequences for "Choose the remote ASR model"

- **monster:** NeMo-Speech.cpp CUDA built for `sm_61` is the only realistic option. It is better than Vulkan (8 sources against 4), and none of the bigger models run there.
- **epic:** there are two choices.
  - **Same stack** (NeMo CUDA): simple, one stream per source, speakers built in, but weaker French and the long-monologue wait.
  - **Bigger text model plus NeMo for speakers:** Voxtral (the best French, but it fills the GPU) or Kyutai (nearly as good in French, small, weaker English). Each diarized source then needs two sessions, and the app must give each word a speaker by time. The live text arrives in under 1 s, but the speaker for a word still arrives with NeMo's final.
- **Language code:** only Qwen3-ASR gives one, and it is ruled out. The app-side text language identification stays necessary in every case.

## Problems and machine state

- **Docker on epic:** GPU containers fail. `nvidia-container-toolkit` is not installed, but `daemon.json` still names the NVIDIA runtime. The unused `vllm/vllm-openai:v0.32.0` image (23.4 GB) is still on epic.
- **Disk:** both machines keep their files in `/var/tmp/ltt-bench`. On epic this includes vLLM in a venv (8.3 GB), the Hugging Face caches (Voxtral 8.3 GB, Qwen 4.4 GB, Kyutai 2.3 GB) and the Kyutai build (about 2.2 GB).
- **State:** no benchmark process is left running on either machine.

## Files

`remote-gpus/monster/` and `remote-gpus/epic/` hold one folder per run:
- `summary.json`: the client summary
- `rt_events_src*.jsonl`: every server event
- `hyp_src*.txt`: the joined transcript
- `wer.txt`: the WER output
- `gpucheck.txt`: the idle checks
- memory monitor logs

They also hold the server and build logs, and the scripts.
