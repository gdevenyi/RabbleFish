"""PipeWire source discovery: microphones and sink monitors, from `pw-dump --monitor`.

A Source (see GLOSSARY.md) is a microphone (`Audio/Source*` node) or the monitor of an
output device (`Audio/Sink` node, captured with `stream.capture.sink=true`). Its key uses
`node.name`, not `object.serial`, so a selection survives a device that goes away and
comes back with a new serial.

A Source is muted when PipeWire reports the node as muted (`pactl set-sink-mute` or
`set-source-mute`, or the mute in a volume control). pw-dump sends the node again when
this changes.
"""

import asyncio
import codecs
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["microphone", "monitor"]

NODE_TYPE = "PipeWire:Interface:Node"
MICROPHONE_CLASSES = ("Audio/Source", "Audio/Source/Virtual")
SINK_CLASS = "Audio/Sink"


@dataclass(frozen=True)
class Source:
    key: str  # "<kind>:<node.name>"
    kind: SourceKind
    node_name: str
    description: str
    serial: int  # target for pw-record; changes when the device comes back
    muted: bool = False  # see node_muted()


def _param(params: list, name: str):
    """The value of `name` in a flat [name, value, name, value, ...] list, or None."""
    for i in range(0, len(params) - 1, 2):
        if params[i] == name:
            return params[i + 1]
    return None


def node_muted(info: dict, kind: SourceKind) -> bool:
    """True if the `Props` params of a node say that the captured audio is muted.

    A microphone is muted by its `mute`. The monitor of a sink is muted by the sink's
    `mute` when `monitor.channel-volumes` is on (the monitor then follows the sink volume,
    as in PulseAudio; this is the usual setting), and by `monitorMute`.
    """
    props = (info.get("params") or {}).get("Props") or []
    muted = False
    for p in props:
        if not isinstance(p, dict):
            continue
        if kind == "microphone":
            muted |= p.get("mute") is True
            continue
        follows = _param(p.get("params") or [], "monitor.channel-volumes")
        muted |= p.get("monitorMute") is True
        muted |= p.get("mute") is True and follows is not False
    return muted


def source_from_node(obj: dict) -> Source | None:
    """Return the Source for a pw-dump node object, or None if it is not one."""
    if obj.get("type") != NODE_TYPE or not obj.get("info"):
        return None
    props = obj["info"].get("props") or {}
    media_class = props.get("media.class")
    if media_class in MICROPHONE_CLASSES:
        kind: SourceKind = "microphone"
    elif media_class == SINK_CLASS:
        kind = "monitor"
    else:
        return None
    name = props.get("node.name")
    serial = props.get("object.serial")
    if name is None or serial is None:
        return None
    description = props.get("node.description") or props.get("node.nick") or name
    if kind == "monitor":
        description = f"Monitor of {description}"
    muted = node_muted(obj["info"], kind)
    return Source(f"{kind}:{name}", kind, name, description, int(serial), muted)


class PwDumpStream:
    """Split the `pw-dump --monitor` output, a sequence of JSON arrays, into arrays."""

    def __init__(self) -> None:
        self._buf = ""
        self._decoder = json.JSONDecoder()

    def feed(self, text: str) -> list[list[dict]]:
        self._buf += text
        out = []
        while True:
            stripped = self._buf.lstrip()
            if not stripped:
                self._buf = ""
                return out
            try:
                value, end = self._decoder.raw_decode(stripped)
            except json.JSONDecodeError:
                self._buf = stripped  # incomplete: wait for more text
                return out
            self._buf = stripped[end:]
            if isinstance(value, list):
                out.append(value)


class SourceRegistry:
    """The current Sources, kept up to date from pw-dump objects.

    pw-dump sends a full object when a node appears or changes, and
    `{"id": N, "info": null}` when an object goes away. Removals carry only the id,
    so the registry maps PipeWire ids to Sources.
    """

    def __init__(self) -> None:
        self._by_id: dict[int, Source] = {}

    def apply(self, objects: Iterable[dict]) -> bool:
        """Apply one pw-dump update. Return True if the Source list changed."""
        before = self.sources()
        for obj in objects:
            obj_id = obj.get("id")
            if obj_id is None:
                continue
            if obj.get("info") is None:
                self._by_id.pop(obj_id, None)
                continue
            source = source_from_node(obj)
            if source is not None:
                self._by_id[obj_id] = source
            elif obj.get("type") == NODE_TYPE:
                self._by_id.pop(obj_id, None)
        return self.sources() != before

    def sources(self) -> list[Source]:
        return sorted(self._by_id.values(), key=lambda s: (s.kind, s.description))

    def get(self, key: str) -> Source | None:
        return next((s for s in self._by_id.values() if s.key == key), None)


async def list_sources() -> list[Source]:
    """Return the current Sources once (`pw-dump` without monitoring)."""
    proc = await asyncio.create_subprocess_exec(
        "pw-dump", "-N", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    registry = SourceRegistry()
    registry.apply(json.loads(out))
    return registry.sources()


async def watch_sources(
    registry: SourceRegistry, on_change: Callable[[list[Source]], Awaitable[None]]
) -> None:
    """Keep `registry` up to date until cancelled; call `on_change` after each change."""
    proc = await asyncio.create_subprocess_exec(
        "pw-dump", "-m", "-N", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    assert proc.stdout is not None
    stream = PwDumpStream()
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        while chunk := await proc.stdout.read(65536):
            changed = False
            for objects in stream.feed(decoder.decode(chunk)):
                changed |= registry.apply(objects)
            if changed:
                await on_change(registry.sources())
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
