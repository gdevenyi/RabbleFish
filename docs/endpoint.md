# The ASR and translation endpoint

The app never runs models itself (ADR-0001). It sends audio and text to one
NeMo-Speech.cpp server, the **endpoint**, which runs:

- Nemotron 3.5 ASR Streaming 0.6B (transcription)
- Nemotron 3 Diarization (speaker labels)
- Riva-Translate 4B Instruct v2 (translation, optional)

`scripts/setup-endpoint.sh` installs the endpoint on any x86_64 Linux machine:
this laptop, or a GPU machine on your network.

## Set up the endpoint

```sh
scripts/setup-endpoint.sh --backend vulkan
```

The script does these steps. Each step skips its work when the result is
already present and verified, so you can run the script again at any time. A
second run does not use the network.

1. Download the NeMo-Speech.cpp v0.3.0 release archive for the backend, check
   its SHA-256 and extract it. `bin/nemo-speech` is a link to the binary.
2. Download the ASR and diarization GGUF files from Hugging Face. The script
   checks the size and the SHA-256 that Hugging Face gives for each file.
3. Convert `nvidia/Riva-Translate-4B-Instruct-v2` to a Q8_0 GGUF with
   `convert_model.py` from the NeMo-Speech.cpp v0.3.0 source, in a temporary
   `uv` venv with CPU PyTorch. After the conversion, the script deletes the
   source, the venv and the downloaded checkpoint, and keeps only the GGUF.
   `--no-translation` skips this step.
4. Write `endpoint.env` and print the `nemo-speech serve` command.

### Options

| Option | Default | Use |
| --- | --- | --- |
| `--backend vulkan\|cuda\|cpu` | none (required) | Release archive and `--device`. Without it, the script shows a suggestion for this machine and stops. |
| `--prefix DIR` | `${XDG_DATA_HOME:-~/.local/share}/rabblefish/endpoint` | Install directory. It must not contain spaces. |
| `--no-translation` | off | Do not convert the translation model. |
| `--host ADDR` | `127.0.0.1` | Bind address in the env file and the printed command. |
| `--port N` | `8080` | Port in the env file and the printed command. |
| `--threads N` | `4` | Endpoint worker count. |

The script needs `curl`, `tar`, `sha256sum`, `git` and `uv`. It stops with a
clear message when one is missing.

### Choose the backend

- `cuda`: NVIDIA GPU with CUDA compute capability **7.5 or higher** (Turing,
  for example RTX 20xx, T4, and newer). The prebuilt CUDA archive has no code
  for older GPUs. The script reads the compute capability with `nvidia-smi`
  and stops on an older GPU. For an older NVIDIA GPU, use `vulkan`, or build
  NeMo-Speech.cpp from source with `CMAKE_CUDA_ARCHITECTURES` set for that GPU
  (see the NeMo-Speech.cpp `docs/build.md`; the script does not do this).
- `vulkan`: any GPU with a Vulkan driver: Intel and AMD GPUs, integrated GPUs,
  older NVIDIA GPUs.
- `cpu`: no GPU. It works, but real time is not guaranteed.

Other architectures (for example aarch64) are not supported by the script.
Build NeMo-Speech.cpp from source there.

### Disk use

| Item | Size |
| --- | --- |
| Release archive (kept for the checksum) | 10 MB (cpu), 19 MB (vulkan), 704 MB (cuda: it includes cuBLAS) |
| Extracted files of the archive | 25 MB (cpu), 57 MB (vulkan), 1.02 GB (cuda) |
| ASR and diarization models | about 0.85 GB |
| Translation model (Q8_0 GGUF) | about 4.4 GB |
| During the conversion only | about 9 GB checkpoint download and a CPU PyTorch venv (about 2 GB) |

The script stops before the conversion when less than 17 GiB is free under the
prefix. It keeps all temporary files under `<prefix>/work` (never in `/tmp`,
which is a RAM disk on many systems). When a conversion fails, the work files
stay there, and the next run continues the download. Delete
`<prefix>/work` to start again.

## Run the endpoint

Run the command that the script prints, for example:

```sh
~/.local/share/rabblefish/endpoint/bin/nemo-speech serve \
    --asr-model ~/.local/share/rabblefish/endpoint/models/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf \
    --diar-model ~/.local/share/rabblefish/endpoint/models/Nemotron-3-Diarization.q8_0.gguf \
    --nmt.model.path ~/.local/share/rabblefish/endpoint/models/riva-translate-4b-instruct-v2.q8_0.gguf \
    --device vulkan --host 127.0.0.1 --port 8080 --no-ui --threads 4 \
    --asr.endpointing.enable=true --asr.batching.enabled=false \
    --asr.streaming.rnnt_right_context=6
```

Check it:

```sh
curl http://127.0.0.1:8080/ready
```

When the models are loaded, `/ready` gives:

```json
{"capabilities": ["asr", "diarization", "translation", "speech-translation"], "device": "vulkan", "ready": true}
```

`translation` and `speech-translation` are there only when the translation
model is loaded. `GET /v1/models` gives the same models with the capability
names that the app checks: `transcription`, `diarization` and `translation`.

Test a translation:

```sh
curl -s -X POST http://127.0.0.1:8080/v1/translations -H 'Content-Type: application/json' \
    -d '{"input": "The meeting starts at nine.", "source_language": "en", "target_language": "fr"}'
```

### Required flags and why

The app cannot read the server flags, so it cannot check them. Use them all:

- `--asr.endpointing.enable=true`: the endpoint finalizes the text at each
  pause. The app sets `endpointing_ms: 800` for each session.
- `--asr.batching.enabled=false`: with batching, two or more concurrent
  realtime sessions give no output or abort
  ([NVIDIA/NeMo-Speech.cpp#89](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/89)).
  The app opens one session for each Source.
- `--threads N`: N must be at least the number of Sources that you capture at
  the same time, because each Source holds one connection for the whole
  Session.
- `--no-ui`: the app does not use the NeMo-Speech.cpp browser playground.
- `--asr.streaming.rnnt_right_context=6`: the endpoint decodes in chunks of
  560 ms, not the 160 ms of the server default (`1`). This gives fewer errors on
  continuous speech, mainly in French, and fewer lost sessions when the GPU is
  near its limit. Partial text arrives about 0.2 s later, and finals about 0.2 s
  later. Use an explicit value: `-1` gives `3` with this model. All sessions of
  the endpoint use the same value.

## Point the app at the endpoint

Set the base URL of the endpoint with the key `asr_endpoint_url` in the config
file (`~/.config/rabblefish/config.toml`):

```toml
asr_endpoint_url = "ws://127.0.0.1:8080"
```

or with the environment variable, which overrides the file:

```sh
export RABBLEFISH_ASR_ENDPOINT_URL=ws://127.0.0.1:8080
```

The default is `ws://127.0.0.1:8080`, so a local endpoint on port 8080 needs
no setting. `rabblefish config` shows the effective value. The "Endpoint" chip of the
UI shows whether the endpoint is ready and which capabilities (transcription,
diarization, translation) it has.

## Remote endpoint

To use a GPU on another machine:

1. Copy this repository (or only `scripts/setup-endpoint.sh`) to the GPU
   machine, and run the script there with the correct backend:

   ```sh
   scripts/setup-endpoint.sh --backend cuda --host 0.0.0.0 --port 8080
   ```

2. Start the endpoint there (printed command or the systemd unit).
3. On the laptop, set the endpoint URL to the GPU machine in
   `~/.config/rabblefish/config.toml`:

   ```toml
   asr_endpoint_url = "ws://gpu-host.lan:8080"
   ```

Bind the host carefully. **The endpoint has no login by default**: anyone who
can reach the port can use the models. Use one of these:

- Keep `--host 127.0.0.1` on the GPU machine and use an SSH tunnel from the
  laptop: `ssh -N -L 8080:127.0.0.1:8080 gpu-host`. The app then uses
  `ws://127.0.0.1:8080`. This is the safest choice.
- Bind to the address of a private network only (for example a VPN or
  WireGuard address), not `0.0.0.0`.
- Bind to `0.0.0.0` only on a network that you trust, and block the port in
  the firewall for other hosts.

## systemd user units

`scripts/systemd/` has two templates. The script does not install them.

- `rabblefish-endpoint.service` runs `nemo-speech serve` with the values from
  `<prefix>/endpoint.env`, which the script writes. Run the script again to
  change the backend, host, port or threads, then restart the unit.
- `rabblefish.service` runs `rabblefish serve`. It expects the `rabblefish` CLI in
  `~/.local/bin/rabblefish` (`uv tool install ./backend` from the repository root;
  see `README.md`). It uses
  `Wants=` for the endpoint, not `Requires=`, because the endpoint can be on
  another machine, and `rabblefish serve` starts also when the endpoint is not ready.

Install them:

```sh
mkdir -p ~/.config/systemd/user
cp scripts/systemd/rabblefish-endpoint.service scripts/systemd/rabblefish.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rabblefish-endpoint.service
systemctl --user enable --now rabblefish.service
```

Show the state and the log:

```sh
systemctl --user status rabblefish-endpoint.service
journalctl --user -u rabblefish-endpoint.service -f
```

The units use the default prefix
(`~/.local/share/rabblefish/endpoint`). For another prefix or
`XDG_DATA_HOME`, change the paths with
`systemctl --user edit --full rabblefish-endpoint.service`.

To start the units at boot without a login, enable lingering:
`loginctl enable-linger $USER`.

For a remote endpoint, install `rabblefish-endpoint.service` on the GPU machine and
`rabblefish.service` on the laptop.

## Update or remove

- To update NeMo-Speech.cpp after you get a new version of this repository, run
  the script again with the same options as before (`--backend`, `--prefix`,
  `--host`, `--port`, `--threads`, `--no-translation`), then restart the
  endpoint. The script writes `endpoint.env` again from these options, and the
  default applies to each option that you omit. If you omit `--no-translation`
  and you do not have the translation model, the script starts the download and
  conversion of that model. The script downloads the new archive and changes the
  `bin/nemo-speech` link. The models stay. A running endpoint continues to use
  the old binary until you restart it. The script does not delete the old
  version: delete
  `<prefix>/nemo-speech-<old version>-*` and
  `<prefix>/downloads/nemo-speech-<old version>-*` when the new version works.
- The script does not download a model file again when the local file is
  correct, so it does not see a new upload to Hugging Face with the same file
  name. To get the new file, delete the file and its `.sha256` file from
  `<prefix>/models`, then run the script again.
- NeMo-Speech.cpp v0.3.0 changes the conversion of cache-aware RNNT Q8_0 models:
  the pointwise convolution weights stay in F16, and upstream says that this
  prevents some lost speech. The runtime cannot repair an older file. The ASR
  file on Hugging Face (2026-09-10) is older than this change, and its 48
  pointwise convolution tensors are Q8_0. It works with v0.3.0, but it does not
  have this fix. The script uses this published file.
- The script does not change an installed systemd unit, and the unit holds the
  server flags. When the flags change, copy
  `scripts/systemd/rabblefish-endpoint.service` to `~/.config/systemd/user/`
  again, then run `systemctl --user daemon-reload` and restart the endpoint.
- To use another backend, run the script again with the new `--backend`. It
  downloads the new archive and changes the `bin/nemo-speech` link. The models
  stay.
- To remove everything, stop the units and delete the prefix directory.
