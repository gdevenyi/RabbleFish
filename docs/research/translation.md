# Research: local translation options

Ticket: [#6 Survey local translation options](https://github.com/gdevenyi/live-transcribe-translate/issues/6)
Map: [#1](https://github.com/gdevenyi/live-transcribe-translate/issues/1)
Date of research: 2026-10-29

## Question

Which local translation options can translate finalized Segments (English and
French; more languages are a benefit) into one Target language with low latency?
Include NLLB, MADLAD, SeamlessM4T, Opus-MT, and a local LLM through an
OpenAI-compatible chat API. For each option: quality, latency per Segment,
context handling across Segments, licence, and fit to the three hardware levels.

Hardware levels (from the map):

1. Laptop: Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU, NPU, 32 GB shared RAM, no NVIDIA.
2. Remote A: NVIDIA GPU, 11 GB VRAM, 128 GB RAM.
3. Remote B: NVIDIA GPU, 16 GB VRAM, 128 GB RAM.

## Short answer

- **Recommended default: a translation-tuned LLM behind an OpenAI-compatible
  chat Endpoint.** The best candidate today is **Tencent Hy-MT2** (1.8B or 7B,
  released 2026-05-21, Apache-2.0, 33 languages incl. English and French, GGUF
  and FP8 builds published by Tencent). It takes a plain-text prompt, so any
  OpenAI-compatible server (llama.cpp `llama-server`, vLLM, SGLang, OpenVINO
  Model Server) can serve it. Its model card documents prompt patterns for
  background context and terminology, which matches our need to pass earlier
  Segments and a glossary.
- **The app should define one "translation Endpoint" interface = OpenAI chat
  completions.** Then the user can point it at Hy-MT2, Gemma 4, Qwen3.5, or any
  other model without code changes. Thinking/reasoning mode must be off.
- **Fast fallback for the laptop CPU: Opus-MT (Marian) through CTranslate2.**
  One small model per direction (fr->en, en->fr), about 75M (base) parameters,
  Apache-2.0 or CC-BY-4.0, very low latency on CPU int8. No cross-Segment
  context. This needs a small custom HTTP wrapper, because CTranslate2 is a
  library, not a server.
- **MADLAD-400 (Apache-2.0)** is the best permissive classic multilingual MT
  model (419 languages). 3B parameters; runs on CPU int8 or on any NVIDIA level.
  Use it if we want many source languages without an LLM.
- **NLLB-200 and SeamlessM4T v2 are CC-BY-NC-4.0** (non-commercial). The NLLB
  card also says "not released for production deployment". Do not make them the
  default. SeamlessM4T adds nothing for text-to-text over NLLB, because its text
  path is NLLB-derived and its extra size is for speech.
- **Nemotron 3.5 Transcribe (the seed model) does speech translation** (audio
  in, translated text out), but its smallest listed consumer GPU is an RTX 5090
  (32 GB, NVFP4). It does not fit any of our three levels, and it does not
  translate text Segments. It is a data point, not an option for this ticket.

## Comparison table

Sizes in GB are **computed, not measured**: fp16/bf16 = 2 bytes/param,
int8 = 1 byte/param, Q4 GGUF = about 0.55 bytes/param, plus runtime overhead.
Latency values are **estimates**, not measured on our hardware (see each section).

| Option | Params | Licence | En/Fr quality (published) | Latency per Segment (est., ~30 tokens) | Context across Segments | Laptop | Remote A 11 GB | Remote B 16 GB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Opus-MT base fr-en (2020) | 75M | Apache-2.0 | newstest2014 fr->en BLEU 37.8 | tens of ms on CPU int8 | none (sentence-level) | yes, CPU (CT2) | yes | yes |
| Opus-MT tc-big fr-en / en-fr (2022) | ~230M (transformer-big; not on card) | CC-BY-4.0 | flores101 fr->en BLEU 46.0, en->fr BLEU 52.2 | under ~0.1 s on CPU int8 | none | yes, CPU (CT2) | yes | yes |
| NLLB-200 distilled 600M / 1.3B / 3.3B | 0.6-3.3B | **CC-BY-NC-4.0** | not pulled (see notes) | 0.1-1 s CPU; under 0.2 s GPU | none; 512-token input limit | yes, CPU (CT2) | yes (3.3B fp16 ~6.6 GB) | yes |
| MADLAD-400 3B / 7.2B / 10.7B | 2.9-10.7B | Apache-2.0 | paper: 10.7B "competitive with significantly larger models" | 3B: ~0.5-1.5 s CPU int8; under 0.3 s GPU | none | 3B yes (int8 ~3 GB) | 3B fp16, 7.2B int8 | 3B, 7.2B int8, 10.7B int8 (~11 GB) tight |
| SeamlessM4T v2 large (T2TT path) | 2.3B (includes speech parts) | **CC-BY-NC-4.0** | not pulled | similar to NLLB 1.3B (est.) | none | possible (PyTorch CPU) | yes | yes |
| LLM via chat API: Hy-MT2 1.8B / 7B | 1.8B / 7B | Apache-2.0 | vendor claims beat Microsoft/Doubao APIs (1.8B) | 1.8B Q4: ~0.5-1.5 s laptop; 7B: ~0.3-0.8 s GPU | **yes**: background + terminology prompts | 1.8B yes; 7B Q4 (~4.5 GB) yes, slower | 7B Q4 or FP8 | 7B FP8/bf16 (~15 GB, tight) |
| LLM via chat API: TranslateGemma 4B / 12B / 27B | 4.3B / 12.2B / 27B | Gemma Terms of Use | WMT24++ (55 langs) MetricX 5.32 / 3.60 / 3.09 | 4B Q4: ~1-2 s laptop | weak: 2K context, one content item | 4B yes | 4B; 12B Q4 (~7 GB) | 12B Q4/int8 |
| LLM via chat API: general model (Gemma 4 E4B, Qwen3.5-9B, Qwen3-30B-A3B) | 4-30B | Apache-2.0 | no MT numbers pulled | similar to above; thinking must be off | **yes**: free-form prompt | E4B yes | 9B Q4 | 9B; 30B-A3B Q4 with CPU offload |
| Nemotron 3.5 Transcribe 30B-A4B (speech translation) | 33.7B total, ~4.3B active | OpenMDW-1.1 | FLEURS speech fr->en BLEU 38.19 (different task) | n/a | n/a | no | no | no |

## Option details

### Opus-MT (Helsinki-NLP, Marian)

- **What it is.** Bilingual Marian transformer models from the OPUS-MT project.
  One model per direction: `opus-mt-fr-en`, `opus-mt-en-fr`, and the newer
  "tc-big" models `opus-mt-tc-big-fr-en`, `opus-mt-tc-big-en-fr`.
- **Size.** `opus-mt-fr-en` has 75.2M parameters (Hub metadata,
  https://huggingface.co/Helsinki-NLP/opus-mt-fr-en). The tc-big models are
  "transformer-big" (card "Model info", release 2022-03-09,
  https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-fr). The parameter count
  for tc-big is not on the card; ~230M is the usual transformer-big size
  (unverified).
- **Quality.**
  - `opus-mt-fr-en` (2020-02-26 weights): newstest2014 fr->en BLEU 37.8,
    chr-F 0.633; Tatoeba BLEU 57.5 (https://huggingface.co/Helsinki-NLP/opus-mt-fr-en).
  - `opus-mt-tc-big-fr-en`: flores101-devtest BLEU 46.0, chr-F 0.694
    (https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-fr-en).
  - `opus-mt-tc-big-en-fr`: flores101-devtest BLEU 52.2, chr-F 0.725
    (https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-fr).
  - These are sentence-level news/web scores. Spoken, disfluent ASR text will
    score lower with every option here.
- **Latency.** CTranslate2's own benchmark (CTranslate2 3.6.0, Opus-MT en-de
  base, 4 threads on a Xeon 8275CL c5.2xlarge) gives 525 target tokens/s fp32
  and 696 tokens/s int8 on CPU, 516 MB RAM at int8; on an A10G GPU 5,876-9,297
  tokens/s (https://github.com/OpenNMT/CTranslate2#benchmarks). That is batch
  throughput, not single-request latency, but it shows that one 30-token Segment
  takes tens of milliseconds on CPU. **Derived estimate, not measured.**
- **Context.** None. The model translates each input independently. We can
  prepend the previous Segment and cut it from the output, but that is fragile.
- **Language switch.** A Language switch means a model switch (fr->en vs en->fr).
  Both models are small, so we can keep both loaded. For other source languages
  we need more pair models.
- **Licence.** `opus-mt-fr-en`: Apache-2.0 (card metadata). tc-big models:
  CC-BY-4.0 (card metadata). Both allow commercial use; CC-BY needs attribution.
- **Runtime.** CTranslate2 converts OPUS-MT/Marian models directly
  (https://github.com/OpenNMT/CTranslate2, latest release v4.8.4, 2026-10-25).
  CTranslate2 GPU support is NVIDIA CUDA only (compute capability >= 3.5); CPU
  support is x86-64 (SSE4.1+, AVX/AVX2/AVX512, Intel MKL and oneDNN) and ARM64
  (https://opennmt.net/CTranslate2/hardware_support.html). It does not use the
  Arc iGPU or the NPU. CTranslate2 has no HTTP server; we must wrap it.
- **Fit.** Laptop: yes (CPU int8, under 1 GB RAM). Remote A and B: yes, trivial.

### NLLB-200 (Meta)

- **What it is.** Many-to-many MT for 200 languages. Hub checkpoints: distilled
  600M, distilled 1.3B, 1.3B, 3.3B (https://huggingface.co/facebook/nllb-200-3.3B).
- **Quality.** The model card says evaluation used BLEU, spBLEU, chrF++ on
  FLORES-200, but per-pair numbers are not in the Hub repo. I did not pull the
  fra-eng / eng-fra rows from the separate metrics file in the fairseq repo.
  **Unverified for our pair.**
- **Limits.** Card, "Out-of-scope use cases": "NLLB-200 is a research model and
  is not released for production deployment"; "The model was trained with input
  lengths not exceeding 512 tokens"; trained on general domain text, mainly
  tested on the Wikimedia domain
  (https://huggingface.co/facebook/nllb-200-distilled-600M).
- **Latency.** Not measured. 600M distilled is about 8x Opus-MT base in size;
  with CTranslate2 int8 on CPU expect roughly 0.1-0.5 s per Segment, and less on
  any NVIDIA level. **Estimate.**
- **Context.** None. Sentence-level, 512-token input cap.
- **Language switch.** Needs a source-language token (`src_lang`, e.g.
  `fra_Latn`) and a forced target token. The app must pass the detected language.
- **Licence.** CC-BY-NC-4.0 (card metadata). Non-commercial only.
- **Runtime.** CTranslate2 supports NLLB and M2M-100 (README model list).
- **Fit.** Laptop: 600M/1.3B on CPU int8. Remote A: 3.3B fp16 (~6.6 GB computed)
  fits. Remote B: fits.

### MADLAD-400 MT (Google)

- **What it is.** T5-based many-to-many MT for 419 languages (Hub language
  list). Sizes: 3B (2,940M params, Hub metadata), 7.2B, 10.7B (card quotes the
  paper: "a 7.2B 48-layer parameter model and a 10.7B 32-layer parameter
  model") (https://huggingface.co/google/madlad400-3b-mt). Paper: arXiv
  2309.04662, 2023-09-09 (https://arxiv.org/abs/2309.04662).
- **Quality.** The abstract says the 10.7B MT model "is competitive with models
  that are significantly larger". Evaluation used WMT, NTREX, Flores-200 and
  Gatones (card). I did not pull per-pair fr/en numbers. **Unverified for our
  pair.**
- **Language switch.** Good fit: the input only needs a target token, e.g.
  `<2en> ...`; the source language is not given (card usage examples). A
  Language switch inside the source needs no change in the request.
- **Latency.** Not measured. 3B is large for a seq2seq model on CPU. The card
  links a Candle Q4K GGUF build (1.65 GB vs 11.8 GB fp32). Expect roughly
  0.5-1.5 s per Segment on the laptop CPU at int8, well under 0.3 s on GPU.
  **Estimate.**
- **Context.** None (sentence-level).
- **Licence.** Apache-2.0 (card). Commercial use allowed.
- **Runtime.** CTranslate2 lists MADLAD-400 as a supported encoder-decoder model
  (README). Candle also runs it (card).
- **Fit.** Laptop: 3B int8 (~3 GB) on CPU. Remote A: 3B fp16 (~6 GB) or 7.2B
  int8 (~7 GB). Remote B: 7.2B int8; 10.7B int8 (~11 GB) is tight.

### SeamlessM4T v2 (Meta)

- **What it is.** One 2.3B-parameter model (Hub metadata) for speech and text
  tasks; text-to-text translation (T2TT) is one task
  (https://huggingface.co/facebook/seamless-m4t-v2-large). Paper arXiv
  2312.05187, 2023-12-08 (https://arxiv.org/abs/2312.05187).
- **Text path.** The card says the text modality of SeamlessM4T is based on
  NLLB-200. For text-only input, it is an NLLB-class model with extra weight for
  speech that we do not use.
- **Quality.** T2TT numbers are in the paper; I did not pull them. Expect
  NLLB-class quality. **Unverified.**
- **SeamlessStreaming.** This is a streaming speech-in model (simultaneous
  translation of audio). It does not apply to finalized text Segments.
- **Context.** None for T2TT.
- **Language switch.** Needs `src_lang` and `tgt_lang` (card usage example).
- **Licence.** CC-BY-NC-4.0 (card metadata). Non-commercial only.
- **Runtime.** Transformers (PyTorch). Not in the CTranslate2 model list.
- **Fit.** Possible on all levels, but there is no reason to choose it over
  NLLB for text.

### Local LLM through an OpenAI-compatible chat API

This option is a protocol, not one model. The app sends
`POST /v1/chat/completions` with the Segment text (plus optional context) to an
Endpoint. The user picks the server and the model.

#### Servers that expose this API

| Server | Hardware it reaches | Source |
| --- | --- | --- |
| llama.cpp `llama-server` | CPU; Intel GPU via SYCL; any GPU via Vulkan; NVIDIA via CUDA | https://github.com/ggml-org/llama.cpp (README: "Launch OpenAI-compatible API server"; backends table lists SYCL for Intel GPU and Vulkan) |
| OpenVINO Model Server (OVMS) v2026.4.1 (2026-10-06) | Intel CPU, Arc iGPU, NPU | Chat completions, completions and responses APIs; "NPU device works only with the Stateful servable type" (https://github.com/openvinotoolkit/model_server/blob/main/docs/llm/reference.md) |
| vLLM, SGLang | NVIDIA GPU | Hy-MT2 card gives `vllm serve` and `sglang.launch_server` commands |

#### Candidate models

**Tencent Hy-MT2 (recommended).**
- Released 2026-05-21 in 1.8B, 7B and 30B-A3B (MoE) sizes; 33 languages incl.
  English and French (https://huggingface.co/tencent/Hy-MT2-1.8B, "News" and
  "Supported Languages").
- Tencent publishes FP8 and GGUF builds (incl. 2-bit and 1.25-bit GGUF for
  1.8B) (card "Model Links").
- Vendor claim: 7B and 30B-A3B "outperform open-source models such as
  DeepSeek-V4-Pro and Kimi K2.6 in fast-thinking mode", and 1.8B "surpasses
  mainstream commercial APIs from providers such as Microsoft and Doubao
  overall" (card). Report: arXiv 2605.22064. **Vendor claim; no independent
  check here.**
- Prompt: plain user message, no system prompt. Card gives English templates for
  default translation, terminology ("Reference the following translations: X
  translates to Y ..."), style, and "Background Information" context. This works
  with any OpenAI-compatible server.
- Recommended sampling for 1.8B/7B: temperature 0.7, top_p 0.6, top_k 20,
  repetition_penalty 1.05 (card). We should test temperature 0 for stable output.
- Licence: Apache-2.0. The card metadata for 1.8B and 7B says `apache-2.0`, and
  the GitHub repo LICENSE.txt says "Hy-MT2 is licensed under the Apache License,
  Version 2.0" (https://github.com/Tencent-Hunyuan/Hy-MT2/blob/main/LICENSE.txt). Note: the earlier HY-MT1.5 (2025-12-30) uses the
  "Tencent HY Community License", which "does not apply in the European Union,
  United Kingdom and South Korea" (https://huggingface.co/tencent/HY-MT1.5-1.8B/blob/main/License.txt).
  Do not mix the two.
- Fit (computed): 1.8B Q4 ~1 GB, 7B Q4 ~4.5 GB, 7B FP8 ~8 GB. Laptop: 1.8B on
  Arc iGPU (llama.cpp SYCL/Vulkan), 7B Q4 possible but slower. Remote A: 7B Q4 or
  FP8. Remote B: 7B FP8; bf16 (~15 GB) is too tight with KV cache.

**Google TranslateGemma.**
- 4B / 12B / 27B, based on Gemma 3; technical report arXiv 2601.09012, submitted
  2026-01-13 (https://arxiv.org/abs/2601.09012). 55 languages.
- WMT24++ (55 languages): MetricX 5.32 / 3.60 / 3.09 and COMET 81.6 / 83.5 / 84.4
  for 4B / 12B / 27B (https://huggingface.co/google/translategemma-4b-it). The
  report says the models show "consistent and substantial gains over the
  baseline Gemma 3 models across all sizes".
- Limits: total input context 2K tokens; the chat template needs a user content
  list with exactly one entry that carries `source_lang_code` and
  `target_lang_code` fields (model card). A plain OpenAI `messages` payload does
  not carry these fields. **Open question:** how llama.cpp or vLLM pass them.
  Context from earlier Segments has to go into the single text item.
- Licence: Gemma Terms of Use (use restrictions apply). Repo is gated.
- Fit (computed): 4B Q4 ~2.5 GB (laptop), 12B Q4 ~7 GB (Remote A), 12B int8
  ~12 GB (Remote B).

**General instruction LLMs (fallback / user choice).**
- Gemma 4 E4B (Apache-2.0, updated 2026-07-20,
  https://huggingface.co/google/gemma-4-E4B-it). Note: Gemma 4 is Apache-2.0,
  unlike Gemma 3 (Gemma terms).
- Qwen3.5-9B (Apache-2.0, https://huggingface.co/Qwen/Qwen3.5-9B) and
  Qwen3-30B-A3B-Instruct-2507 (Apache-2.0, 30.5B total,
  https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507).
- I pulled no MT benchmark numbers for these. Their advantage is free-form
  prompts: we can pass earlier Segments, Display names and a glossary.
- **Thinking mode must be off** (for Qwen: `enable_thinking=false` in the chat
  template). Reasoning tokens would break the 2-5 s budget. The Nemotron card
  also says "reasoning off" for translation.

#### Latency of the LLM option

No primary benchmark for our hardware. Decoding is limited by memory bandwidth.
The 258V supports LPDDR5X-8533 (Intel ARK,
https://www.intel.com/content/www/us/en/products/sku/240957/intel-core-ultra-7-processor-258v-12m-cache-up-to-4-80-ghz/specifications.html);
on a 128-bit bus that is about 136 GB/s peak (computed; ARK does not list the
bandwidth). A 4B Q4 model (~2.5 GB) reads all weights for each token, so the
upper bound is about 50 tokens/s; real speed is lower. A 30-token Segment then
needs roughly 1-2 s including prompt processing. On an NVIDIA card with 11-16 GB
the same Segment should take well under 1 s for a 7B Q4 model. **All estimates;
benchmark first.**

#### Context across Segments

This is the main reason to prefer an LLM. We can send:
- the last N source Segments and their translations (for pronouns, gender,
  register, and for short Segments like "Oui." or "Exactly");
- a glossary of names and terms (Display names, project words);
- the source language hint from Language switch detection (optional; LLMs can
  detect it).

Cost: longer prompts increase prefill time. Keep N small (2-4 Segments) and
measure.

### Not an option here: Nemotron 3.5 Transcribe speech translation

- The seed model does "speech translation" with the prompt
  `Please translate the given speech to <target language>.`; French is
  "Leading" quality for "Translation <-> English"
  (https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B).
- FLEURS speech fr->en BLEU 38.19, en->fr 42.51; CoVoST2 fr->en 41.14 (card).
  These are speech-to-text-translation scores; do not compare them with the text
  MT scores above.
- Hardware table: smallest consumer entry is RTX 5090 (NVFP4); the reference
  deployment is 1x H100 80 GB. No entry fits 11 or 16 GB. Licence OpenMDW-1.1.
- It translates audio, not our finalized text, and one call would not return both
  the source transcript and the translation aligned. Relevant to the ASR tickets,
  not to this one.

## Fit per hardware level

### Laptop (Core Ultra 7 258V, Arc 140V, NPU, 32 GB shared)

- CTranslate2 reaches the CPU only (no Intel GPU support). Opus-MT int8 is the
  fastest path. MADLAD-3B int8 and NLLB-600M int8 also run.
- The Arc 140V (64 INT8 TOPS, 8 Xe-cores) and the NPU (47 INT8 TOPS) (Intel ARK)
  are reachable through llama.cpp (SYCL or Vulkan) and OVMS. These serve LLMs
  with an OpenAI-compatible API: Hy-MT2-1.8B, TranslateGemma-4B, Gemma 4 E4B.
- The ASR model will likely also use the iGPU/NPU and shared memory. Translation
  on the CPU (Opus-MT) avoids competition for the GPU. This trade-off needs a
  test.

### Remote A (NVIDIA, 11 GB VRAM)

- Hy-MT2-7B Q4 (GGUF, llama.cpp) or FP8 (vLLM; FP8 needs a recent GPU
  generation, unverified for this card). TranslateGemma-12B Q4. MADLAD-3B fp16 or
  7.2B int8.
- VRAM is shared with any ASR model on the same card. Plan for this.

### Remote B (NVIDIA, 16 GB VRAM)

- Hy-MT2-7B FP8, TranslateGemma-12B int8, MADLAD-7.2B int8, Qwen3.5-9B.
- 128 GB system RAM allows MoE models (Qwen3-30B-A3B, Hy-MT2-30B-A3B) with
  expert offload to CPU in llama.cpp, but latency is unknown.

## Recommendation for the downstream decisions

1. Define the translation Endpoint as **OpenAI chat completions** (base URL,
   model name, optional API key, prompt template). This covers every LLM option
   on every hardware level.
2. Default model: **Hy-MT2-7B** on Remote A/B, **Hy-MT2-1.8B** on the laptop.
   Alternative: TranslateGemma if its template works through the chosen server.
3. Optional second Endpoint type: **CTranslate2 seq2seq** (Opus-MT or MADLAD) for
   lowest latency on CPU. This needs a small wrapper service, because the app
   never runs models in-process.
4. Avoid NLLB and SeamlessM4T as defaults because of CC-BY-NC-4.0.

## Open questions for the decision tickets

1. **Benchmark per Segment on each hardware level** (median and p95 latency for
   20-60 token Segments): Opus-MT CT2 int8 CPU, MADLAD-3B, Hy-MT2-1.8B/7B,
   TranslateGemma-4B/12B. All latency numbers in this file are estimates.
2. **Quality on our data:** spoken, disfluent ASR text with fr/en code-switching.
   Build a small test set (about 100 Segments) and compare with COMET or by hand.
3. **Commercial use?** If the app may ever be used commercially, NLLB and
   SeamlessM4T are out, and TranslateGemma needs a check of the Gemma terms.
4. **How many earlier Segments to send as context**, and does context help more
   than it costs in latency?
5. **TranslateGemma through an OpenAI-compatible server:** how do llama.cpp, vLLM
   or OVMS pass `source_lang_code`/`target_lang_code`?
6. **Laptop resource sharing:** can ASR and translation share the Arc iGPU/NPU,
   or should translation stay on the CPU?
7. **Translate when the source language equals the Target language?** Skip the
   call (cheap) or pass through.
8. **Do we translate per Segment or batch several finalized Segments** from
   different Speakers into one request? Batching lowers cost but adds delay.
