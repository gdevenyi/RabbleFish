# Research: PipeWire multi-source capture from Python

Ticket: [#7](https://github.com/gdevenyi/live-transcribe-translate/issues/7). Date: 2026-10-29.

## Question

How can a Python process list PipeWire sources (microphones and sink monitors) for a selection UI, and capture several of them at the same time as separate streams with accurate timestamps on a shared clock? Compare options such as pw-record subprocesses, PulseAudio compatibility libraries (pulsectl, sounddevice), GStreamer and direct PipeWire bindings. Note sample rate and format handling, and how to detect when a device appears or goes away.

## Short answer

**Recommendation for the first version: one `pw-record` subprocess per Source, plus one `pw-dump --monitor` subprocess for the device list and hot-plug events.** Use no native Python bindings.

- **Capture.** Start one `pw-record --raw --rate 16000 --channels 1 --format s16 --target <object.serial> -P '{ stream.capture.sink=true node.dont-fallback=true node.dont-reconnect=true }' -` for each Source. Read stdout with `asyncio`. PipeWire does the downmix, the format conversion and the resampling in the stream.
- **Listing and hot-plug.** Parse the JSON stream from `pw-dump --monitor`. A new node arrives as a full object. A removed node arrives as `{"id": N, "info": null}`.
- **Timestamps.** The raw pipe has no timestamps. Give each Source a `time.monotonic_ns()` anchor when its first bytes arrive. Then compute the time of each sample from the sample count. All Sources then share one clock: CLOCK_MONOTONIC. Check drift (sample time against wall time) at intervals and re-anchor when it is more than about 50 ms. This accuracy (tens of ms) is sufficient for a Timeline with a 2-5 s latency target.
- **Three settings are mandatory.** We tested them on this laptop (PipeWire 1.6.9, WirePlumber 0.5.18):
  1. If you target a sink by **name** and do not set `stream.capture.sink=true`, WirePlumber **links the stream to the default microphone, with no error**. If you target a sink by **serial**, it links to the monitor ports.
  2. If you do not set `node.dont-reconnect=true` and the target goes away, the stream **moves to a different device, with no error**. With the property set, `pw-record` exits with code 1 and prints `target not found`.
  3. `node.dont-fallback=true` stops a fallback to the default device when the target cannot be linked.
- **Upgrade path.** Use GStreamer (`pipewiresrc` in one pipeline, through PyGObject) when we need sample-accurate alignment on one pipeline clock. Use JACK-Client on `pipewire-jack` when we need all Sources in one process cycle. Both need more work. See the caveats below.
- **Do not use** `sounddevice` for multi-source capture. It cannot select individual PipeWire nodes. Use `pulsectl` only for control and listing. It does not capture audio.

## Comparison table

| Option | List sources incl. monitors | Capture many at once | Timestamps / shared clock | Hot-plug detection | Install under uv | Licence | Status (2026-10-29) |
|---|---|---|---|---|---|---|---|
| **`pw-record` subprocess** (pw-cat, part of PipeWire) | No (use `pw-dump`) | Yes: one process per Source. Tested with 2 at once, no sample loss | None in the stream. Reconstruct from sample count + monotonic anchor | Exits when target goes away, if `node.dont-reconnect=true` | Nothing to install (system tool) | MIT (PipeWire) | PipeWire 1.6.9 local; docs show 1.6.11 |
| **`pw-dump --monitor`** subprocess | Yes: all nodes as JSON, incl. `media.class`, `node.name`, `object.serial` | n/a | n/a | Yes: add = full object, remove = `{"id":N,"info":null}` (tested) | Nothing to install | MIT | as above |
| **pulsectl / pulsectl-asyncio** (libpulse via pipewire-pulse) | Yes: `source_list()` shows `*.monitor` sources and `monitor_of_sink` | **No**: control API only | n/a | Yes: `event_mask_set` + `event_listen`, or async generator in pulsectl-asyncio | Pure Python wheel (needs system libpulse) | MIT / MIT | 24.12.0 (2024-12-26) / 1.3.2 (2026-06-27) |
| **sounddevice** (PortAudio) | **No**: only ALSA PCMs (`pipewire`, `pulse`, `default`) plus raw `hw:` devices | Only the default source per stream; node choice needs env vars per process | `inputBufferAdcTime` per callback, per stream | No | Pure Python wheel (needs system libportaudio) | MIT | 0.5.6 (2026-08-17); PortAudio last release v19.7.0 (2021-04-06) |
| **GStreamer `pipewiresrc`** via PyGObject | Yes: `Gst.DeviceMonitor` + `pipewiredeviceprovider` gives serial and name. Monitors are not listed as sources | Yes: many `pipewiresrc` elements in one pipeline | **Best**: one `GstPipeWireClock`, all buffer PTS on one running time | Yes: DeviceMonitor bus messages; `on-disconnect=eos\|error` per element | **Hard**: PyGObject 3.58.1 is sdist only; needs system gobject-introspection + cairo headers + compiler, or a venv with system site-packages | LGPL-2.1+ (GStreamer, PyGObject); plugin MIT | GStreamer 1.28.8, plugin 1.6.9 local |
| **WirePlumber GI (`Wp-0.5`)** via PyGObject | Yes (tested): `ObjectManager` with `object-added` / `object-removed` | No (control only) | n/a | Yes (signals) | Same PyGObject problem | MIT | WirePlumber 0.5.18 local |
| **JACK-Client** on `pipewire-jack` | Yes: `get_ports()` incl. sink monitor ports | Yes: N input ports in one process callback | One frame clock (`last_frame_time`) for all ports in a cycle | Port and client registration callbacks | Pure Python wheel (cffi; needs libjack from pipewire-jack) | MIT | 0.5.7 (2026-09-23). **Not tested** (pipewire-jack not installed here) |
| **Direct libpipewire bindings** | — | — | `pw_stream_get_time_n()` gives `now` (ns) + `ticks` | registry events | No maintained Python binding found. ctypes/cffi to libpipewire is possible but not done | — | `pipewire_python` 0.2.3 (2023-02-09) only wraps the CLI tools |

## Test system

All tests ran on the Level 1 laptop: Intel Core Ultra 7 258V, kernel 7.2.11, PipeWire 1.6.9, WirePlumber 0.5.18, pipewire-pulse (server reports "PulseAudio (on PipeWire 1.6.9) 15.0.0"), GStreamer 1.28.8, Python 3.14. The graph settings are `clock.rate=48000`, `clock.allowed-rates=[ 48000 ]`, `clock.quantum=1024` (21.3 ms) (`pw-metadata -n settings`). The internal digital microphone is `alsa_input.pci-0000_00_1f.3-platform-sof_sdw.HiFi__Mic__source`, **4 channels, s32le, 48 kHz**. The test scripts were throwaway scripts in a scratch directory. They are not in the repo.

## Option details

### 1. `pw-record` subprocesses (recommended)

`pw-record` is `pw-cat` in capture mode. It is part of PipeWire (MIT).

- `--target` takes "the object.serial or node.name of a target node"; `--raw` writes raw samples; `-` writes to stdout; `--latency` defaults to 100 ms; `--rate`, `--format`, `--channels` set the raw format. Source: [pw-cat(1)](https://docs.pipewire.org/page_man_pw-cat_1.html). The local `pw-record --help` also shows `-P/--properties` (set node properties), `-q/--quality` (resampler quality 0-15, default 4) and `-n/--sample-count`.
- **Format conversion is done for you.** We asked for 16 kHz mono s16 from the 4-channel s32le 48 kHz mic. The stream linked all 4 mic ports (`capture_FL/FR/RL/RR`) and delivered mono 16 kHz. Thus the app does not need its own resampler. Most ASR endpoints want 16 kHz mono. The downstream endpoint tickets must confirm this.
- **Concurrent capture is clean.** Two `pw-record` processes (mic + speaker monitor) at the same time, read from Python threads: mic 3.860 s of audio in 3.882 s wall time, monitor 3.092 s in 3.076 s. A monitor of an active sink (a 440 Hz tone played into a null sink with `pw-play`) gave 5.908 s of audio in 5.888 s wall time. The RMS was 2113 for a tone with amplitude 3000, so the signal was intact.
- **Start offset is invisible.** In the concurrent test the monitor stream started about 0.8 s after the mic stream (the sink was suspended). Nothing in the byte stream tells you this. Thus you must take the anchor time when the **first bytes of each Source** arrive, not when the process starts.
- **Targeting a sink monitor, tested with `pw-link -l` while capture ran:**

  | `pw-record` arguments | Linked to |
  |---|---|
  | `--target 54` (serial of the speaker sink) | `...Speaker__sink:monitor_FL/FR` (correct) |
  | `--target <sink node.name>` | `...Mic__source:capture_*` (**wrong, no error**) |
  | `--target <sink node.name> -P '{ stream.capture.sink=true }'` | `...Speaker__sink:monitor_FL/FR` (correct) |

  The cause is in WirePlumber. `cutils.getTargetDirection()` only selects sink-side (input) targets for a capture stream when `stream.capture.sink` is true (`/usr/share/wireplumber/scripts/lib/common-utils.lua`, WirePlumber 0.5.18). The name lookup in `linking/find-defined-target.lua` requires that direction to match, but the numeric lookup does not. When no target matches, WirePlumber falls back to the default source. This is session-manager behaviour. It can change between WirePlumber versions. Thus always set `stream.capture.sink=true` for monitors **and** `node.dont-fallback=true`.
- **Target goes away, tested by unloading a null sink during capture:**
  - Without `node.dont-reconnect`: `pw-record` keeps running. Its ports are re-linked to `...Speaker__sink:monitor_FL/FR`, which is a different device. The app gets wrong audio and no error.
  - With `node.dont-reconnect=true`: `pw-record` exits with code 1. stderr shows `stream node ... error: target not found`.
  - This matches [pipewire-props(7)](https://docs.pipewire.org/page_man_pipewire-props_7.html): `node.dont-reconnect` — "When the node has a target configured and the target is destroyed, destroy the node as well"; `node.dont-fallback` — "If linking this node to its specified target does not succeed, session manager should not fall back to linking it to the default target"; `target.object = <node.name|object.serial>` replaces the deprecated `node.target`.
- **Timestamps.** The raw output has no time information. The app must compute `t(sample k) = anchor_ns + k / rate`. PipeWire resamples follower devices to the graph driver. Thus the sample rate seen in the pipe is nominal and drift against CLOCK_MONOTONIC should be small. **We did not measure drift over a long Session.** This is an open question. An xrun or a dropped period is also invisible in the pipe. The drift check (sample time against `time.monotonic_ns()`) detects it.
- **Cost.** One small process per Source. For 8 Sources this is 8 processes. CPU use was not measured but is expected to be low (pure copy + resample).

### 2. `pw-dump --monitor` for the Source list and hot-plug

- `pw-dump` prints the PipeWire objects as JSON. `-m/--monitor` prints changes (local `pw-dump --help`).
- **Tested:** with `pw-dump --monitor` running, we loaded and unloaded a null sink. The add event contained the full node object: `type: PipeWire:Interface:Node`, `media.class: Audio/Sink`, `node.name: probe_dm`, `object.serial: 8846`. The removal events were `{"id": N, "info": null}` for the node and its ports. The output is a sequence of JSON arrays, not JSON lines. Parse it with `json.JSONDecoder.raw_decode`.
- `id` (203) and `object.serial` (8846) are different numbers. Keep a map `id -> node` to handle removals. Use `object.serial` as the target for `pw-record`, because PipeWire reuses ids but not serials ([pipewire-props(7)](https://docs.pipewire.org/page_man_pipewire-props_7.html): `target.object` "uses the more unique object.serial").
- **Building the selection UI:**
  - Microphones are `media.class == "Audio/Source"` (and `Audio/Source/Virtual`, for example `easyeffects_source`).
  - Monitors are not separate nodes in PipeWire. Show each `Audio/Sink` as "Monitor of <node.description>" and capture it with `stream.capture.sink=true`.
  - Use `node.description` as the label. On this laptop it is, for example, "Core Ultra 200V Series Processors HD Audio Digital Microphone".
  - Filter out our own `pw-record` stream nodes (`Stream/Input/Audio`).
- The pulse layer shows the same serials: `pactl list short sources` shows `54 ...Speaker__sink.monitor`, and the PipeWire serial of that sink is 54.

### 3. pulsectl and pulsectl-asyncio (control only)

- pulsectl is "for controlling PulseAudio sound server ... as opposed to e.g. submitting sound samples to play and player-like client" ([README](https://github.com/mk-fg/python-pulse-control)). It cannot capture audio. MIT, 24.12.0, 2024-12-26 ([PyPI](https://pypi.org/project/pulsectl/)).
- **Tested** against pipewire-pulse: `source_list()` returned the 4 sink monitors (`monitor_of_sink` = sink index) and the 3 real/virtual sources (`monitor_of_sink = 4294967295`, which means none).
- Events: `pulse.event_mask_set('all')`, `event_callback_set(fn)`, `event_listen(timeout)`. Event types are `change`, `new`, `remove` ([README](https://github.com/mk-fg/python-pulse-control)). The blocking event loop cannot run in more than one thread.
- pulsectl-asyncio (MIT, 1.3.2, 2026-06-27) adds an asyncio main loop and an async-generator event API ([README](https://github.com/mhthies/pulsectl-asyncio)).
- Use: an alternative to `pw-dump --monitor` if we prefer a Python API. To capture, it still needs a separate tool (`parec`, `pw-record`).

### 4. sounddevice / PortAudio (not suitable)

- **Tested:** sounddevice 0.5.6 with system PortAudio "V19.7.0-devel". `query_hostapis()` returned only **ALSA** and **OSS**. `query_devices()` listed raw `hw:0,x` devices and ALSA plugin PCMs (`pipewire`, `pulse`, `default`). No PipeWire node or monitor appears by name.
- PortAudio's last release is v19.7.0 (2021-04-06). Its `src/hostapi` folder has `alsa, jack, pulseaudio, ...` but no `pipewire` ([GitHub](https://github.com/PortAudio/portaudio/tree/master/src/hostapi), [releases](https://github.com/PortAudio/portaudio/releases)). The PulseAudio host API was merged in 2023 (PR #336) but is not in a release.
- The callback gives `time.inputBufferAdcTime` in seconds on the stream's own time base ([sounddevice docs](https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html)). There is no shared clock between streams.
- Opening a raw `hw:` device bypasses PipeWire and blocks other users of the device. The `pipewire` PCM only gives the default source unless you set an environment variable such as `PIPEWIRE_NODE` per process. Thus it gives no benefit over `pw-record`.

### 5. GStreamer `pipewiresrc` via PyGObject (best clock, more risk)

- The plugin `pipewire` (1.6.9, MIT/X11) has `pipewiresrc`, `pipewiresink` and `pipewiredeviceprovider` (local `gst-inspect-1.0 pipewire`).
- `pipewiresrc` properties (local `gst-inspect-1.0 pipewiresrc`): `target-object` ("The source name/serial to connect to"), `stream-properties`, `provide-clock` (default true), `do-timestamp`, `on-disconnect` (`none` default, `eos`, `error`), `min-buffers`/`max-buffers`, `keepalive-time`, `client-name`.
- **Shared clock, tested:** two `pipewiresrc` elements (mic + monitor with `stream-properties="props,stream.capture.sink=true"`) in one pipeline used one `GstPipeWireClock`. Every buffer PTS is on one pipeline running time. Buffers were one quantum (341 samples at 16 kHz = 1024 at 48 kHz, 21.3 ms). This is the best shared-clock solution of all options.
- **Data loss with Python `appsink`, tested:** with `appsink emit-signals=true` and a Python `new-sample` handler, we received only 22-55 % of the expected audio (for example 3.75 s in a 9.5 s PTS span), with no `DISCONT` flags after the first buffer. A `queue` after `pipewiresrc` did not fix it. The same pipelines with `filesink` lost no data: `gst-launch-1.0` gave 7.93 s in about 8 s, and the same pipeline in-process from Python gave 9.9 s in about 10 s for the monitor. Thus the loss is in our appsink/Python handler path. The cause is not known. A pull loop (`try_pull_sample`) in a dedicated thread could fix it but is **not tested**. Do not choose GStreamer until a test shows loss-free capture into Python.
- **Device list, tested:** `Gst.DeviceMonitor` with the `pipewiredeviceprovider` returned every source and sink with `object.serial`, `node.name` and the matching element (`pipewiresrc`/`pipewiresink`). Sink monitors are not listed as sources, so the UI must add them as for `pw-dump`. One quirk: `easyeffects_source` (`Audio/Source/Virtual`) was mapped to `pipewiresink`.
- **Install, verified on PyPI:** PyGObject 3.58.1 (2026-10-09, LGPL-2.1+) publishes only `pygobject-3.58.1.tar.gz`. Under a `uv` venv it builds from source. It needs the gobject-introspection and cairo development packages and a C compiler. The alternative is a venv with `--system-site-packages`. This is a real cost for the "Python backend (uv)" constraint.
- Licence: GStreamer core and PyGObject are LGPL-2.1+. Dynamic linking from an app with any licence is normally fine.

### 6. WirePlumber GObject-introspection (`Wp-0.5`)

- The system has `Wp-0.5.typelib`. **Tested:** `Wp.ObjectManager` with interest in `Wp.Node` and `Wp.OBJECT_FEATURES_ALL` listed all 8 audio nodes with serial, `media.class`, `node.name` and `node.description`.
- PyGObject note: the interface method `get_properties` is hidden by `GObject.get_properties`. Use `Wp.PipewireObject.get_properties(node).get("media.class")`.
- `object-removed` was connected but not exercised. The Python process dumped core at exit in each run (not investigated).
- It has the same PyGObject install cost as GStreamer and gives nothing more than `pw-dump --monitor` for our needs.

### 7. JACK-Client on pipewire-jack (not tested)

- With `pipewire-jack`, PipeWire nodes appear as JACK ports, including sink `monitor_*` ports. One JACK client can register N input ports and connect each to a different device. All ports are processed in **one** process callback per graph cycle. The frame time is common to all ports in that cycle (`last_frame_time`, `frames_since_cycle_start`) ([JACK-Client docs](https://jackclient-python.readthedocs.io/en/0.5.5/api.html)).
- `samplerate` is the graph rate (48000 here), so the app must resample to 16 kHz itself. `blocksize` is the quantum.
- The docs warn: "Most Python interpreters use a global interpreter lock (GIL), which violates the above real-time requirement" and "Python is not really suitable for real-time processing". Thus the callback must only copy into a ring buffer.
- Hot-plug: `set_port_registration_callback`, `set_client_registration_callback`.
- JACK-Client 0.5.7 (2026-09-23, MIT) is a pure-Python cffi wheel. It needs `libjack` from the `pipewire-jack` package, which is **not installed** on this laptop. Not tested.

### 8. Direct libpipewire bindings

- There is no official or maintained Python binding for libpipewire. A GitHub search for Python PipeWire projects found only apps and CLI wrappers. `pipewire_python` 0.2.3 (2023-02-09, MIT) wraps `pw-cat`/`pw-cli` ([repo](https://github.com/pablodz/pipewire_python)).
- The C API has what we would want. `pw_stream_get_time_n()` fills `struct pw_time` with `now` (ns), `rate`, `ticks`, `delay`, `queued`, `buffered` and `size`, and the docs show how to extrapolate the current graph position ([pw_time](https://docs.pipewire.org/structpw__time.html)). This would give exact capture timestamps per stream on the monotonic clock.
- To get this from Python, we would write a ctypes/cffi layer over `pw_main_loop`, `pw_stream` and SPA POD format building. This is a large and fragile job. Do it only if the `pw-record` timestamp error is too large in practice.

## Sample rate and format handling

- The graph runs at 48 kHz on this laptop (`clock.allowed-rates=[ 48000 ]`). Device formats differ: the mic is 4 ch s32le, the sinks are 2 ch s32le, and Easy Effects is float32le (`pactl list short sources`).
- PipeWire's stream adapter converts to the format that the stream asks for. With `pw-record` this is `--rate/--format/--channels`, and the resampler quality is `-q` (default 4). With GStreamer, `audioconvert ! audioresample` plus caps do it.
- `node.rate` and `node.force-rate` change the **graph** rate and affect other apps ([pipewire-props(7)](https://docs.pipewire.org/page_man_pipewire-props_7.html)). Do not set them. Resample in the stream.
- `stream.dont-remix=true` keeps the original channels. Use it only if a future "diarize" Source needs the separate channels of a mic array. Mono is the default.
- Suggested wire format to endpoints: 16 kHz, mono, s16le = 32 kB/s (256 kbit/s) per Source. 8 Sources = 2 Mbit/s. This fits easily on a LAN link to Remote A/B.

## Fit to hardware levels

- **Level 1, laptop (Core Ultra 7 258V):** capture always runs here, because the audio devices are here. All tests in this file ran on this machine. `pw-record` needs no GPU and no NPU. The laptop's built-in mic is a 4-channel DMIC array. PipeWire downmixes it to mono for us.
- **Level 2/3, remote GPU hosts:** they do not capture. They receive the 16 kHz mono stream per Source from the backend. Capture choice has no effect there, except the bandwidth figure above.

## Open questions for the decision tickets

1. **Drift over long Sessions.** Measure sample-count time against `time.monotonic_ns()` for 1 hour with a USB mic and an internal sink. Is the drift under 50 ms? If not, how often must we re-anchor?
2. **Monitor of a suspended sink.** When nothing plays, the monitor delivered silence after a start delay of about 0.8 s. Is silence always delivered while the sink is idle, or can there be gaps? This affects the timestamp anchor.
3. **GStreamer appsink loss.** Does a pull thread (`try_pull_sample`) or `appsink drop=false max-buffers=0 sync=false` with no signals give loss-free capture into Python? Only if yes is GStreamer a candidate for exact alignment.
4. **JACK path.** Install `pipewire-jack` and test JACK-Client with 8 ports. Is a Python process callback without xruns possible at quantum 1024?
5. **Wire format.** Do the chosen inference Endpoints want 16 kHz mono s16, or float32, or 24 kHz? This sets the `pw-record` arguments.
6. **Reconnect policy.** When a Source goes away (`pw-record` exits with "target not found"), should the Session mark the Column as paused and restart automatically when a node with the same `node.name` returns? Serials change on return, so the match must use `node.name`.
7. **Echo.** A mic near the speakers also captures the sink monitor audio. Do we need echo cancellation (PipeWire `module-echo-cancel`) before diarization? This is out of scope here.

## Sources

- PipeWire pw-cat(1) man page: https://docs.pipewire.org/page_man_pw-cat_1.html
- PipeWire pipewire-props(7): https://docs.pipewire.org/page_man_pipewire-props_7.html
- PipeWire `struct pw_time`: https://docs.pipewire.org/structpw__time.html
- WirePlumber 0.5.18 linking scripts (local): `/usr/share/wireplumber/scripts/lib/common-utils.lua`, `/usr/share/wireplumber/scripts/linking/find-defined-target.lua`; upstream https://gitlab.freedesktop.org/pipewire/wireplumber
- GStreamer pipewire plugin: local `gst-inspect-1.0 pipewire` / `pipewiresrc` (plugin 1.6.9)
- pulsectl: https://github.com/mk-fg/python-pulse-control , https://pypi.org/project/pulsectl/
- pulsectl-asyncio: https://github.com/mhthies/pulsectl-asyncio
- python-sounddevice: https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html , https://github.com/spatialaudio/python-sounddevice
- PortAudio: https://github.com/PortAudio/portaudio (releases, `src/hostapi`)
- JACK-Client: https://jackclient-python.readthedocs.io/en/0.5.5/api.html , https://github.com/spatialaudio/jackclient-python
- PyGObject: https://pypi.org/project/PyGObject/ , https://pygobject.gnome.org
- pipewire_python: https://github.com/pablodz/pipewire_python
