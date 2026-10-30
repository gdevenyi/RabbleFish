import json

from rabblefish.sources import PwDumpStream, SourceRegistry, source_from_node


def node(obj_id, serial, media_class, name, description=None):
    props = {"media.class": media_class, "node.name": name, "object.serial": serial}
    if description:
        props["node.description"] = description
    return {"id": obj_id, "type": "PipeWire:Interface:Node", "info": {"props": props}}


MIC = node(58, 58, "Audio/Source", "alsa_input.mic", "Digital Microphone")
SPEAKER = node(54, 54, "Audio/Sink", "alsa_output.speaker", "Speaker")
OUR_STREAM = node(300, 9100, "Stream/Input/Audio", "pw-record")


def test_microphone_and_monitor_are_sources():
    mic = source_from_node(MIC)
    mon = source_from_node(SPEAKER)
    assert (mic.kind, mic.key, mic.serial) == ("microphone", "microphone:alsa_input.mic", 58)
    assert (mon.kind, mon.description) == ("monitor", "Monitor of Speaker")


def test_streams_and_other_objects_are_not_sources():
    assert source_from_node(OUR_STREAM) is None
    assert source_from_node({"id": 1, "type": "PipeWire:Interface:Port", "info": {}}) is None


def test_stream_parser_handles_split_arrays():
    text = json.dumps([MIC]) + "\n" + json.dumps([SPEAKER])
    stream = PwDumpStream()
    first = stream.feed(text[:30])
    rest = stream.feed(text[30:])
    assert first == []
    assert [len(a) for a in rest] == [1, 1]


def test_registry_add_change_remove():
    reg = SourceRegistry()
    assert reg.apply([MIC, SPEAKER, OUR_STREAM]) is True
    assert {s.kind for s in reg.sources()} == {"microphone", "monitor"}
    assert reg.apply([MIC]) is False  # same object again: no change
    assert reg.apply([{"id": 58, "info": None}]) is True
    assert [s.kind for s in reg.sources()] == ["monitor"]


def test_key_survives_new_serial():
    reg = SourceRegistry()
    reg.apply([MIC])
    reg.apply([{"id": 58, "info": None}, node(70, 9200, "Audio/Source", "alsa_input.mic")])
    src = reg.get("microphone:alsa_input.mic")
    assert src is not None and src.serial == 9200
