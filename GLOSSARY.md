# Live Transcribe Translate

Live transcription of the audio on a Linux desktop, with one timeline column for each speaker and optional translation.

## Language

### Capture

**Session**:
One continuous run of transcription, from start to stop. Speaker identity and display names are valid only inside one session.
_Avoid_: Recording, meeting, run

**Source**:
One audio input that the user selects for a session, for example a microphone or the monitor of an output device. Each source stays a separate stream.
_Avoid_: Device, channel, input

### Speakers

**Speaker**:
One distinct voice that the app detects inside a session. A speaker has a generated label and an optional display name.
_Avoid_: Participant, user, voice

**Display name**:
The real name that the user assigns to a speaker, for example "Alice" for "Speaker 2".
_Avoid_: Alias, nickname

**Correction**:
A change by diarization to the speaker of segments that are already finalized. A correction is a move or a merge.
_Avoid_: Reassignment, fix, relabel

**Move**:
A correction that gives one segment to a different speaker.

**Merge**:
A correction that finds two speakers are the same voice and joins one into the other. The joined speaker no longer has a column.
_Avoid_: False split (that is the cause, not the correction)

### Transcript

**Segment**:
One finalized piece of speech from one speaker, with a start time, an end time, a detected language and its text.
_Avoid_: Utterance, line, chunk

**Partial text**:
Text from a source that is still changing and has no speaker yet. It becomes one or more segments when it is finalized.
_Avoid_: Draft, interim, buffer

**Language switch**:
A change in the detected language between segments, or inside one segment, of the same speaker.
_Avoid_: Code-switch (unless inside one segment)

**Translation**:
The text of a segment in the target language, shown with the original text.

**Target language**:
The one language that the user selects for translation in a session.

### Display

**Timeline**:
The scrollable view of the full session transcript, with time on the vertical axis and one column for each speaker.
_Avoid_: Feed, log, chat

**Column**:
The vertical lane in the timeline that holds the segments of one speaker.
_Avoid_: Track, lane

**Collapsed column**:
A column that shows only its name and marks for when its speaker spoke, because the speaker was silent for some time and is not pinned.
_Avoid_: Hidden column, minimized

**Silence fold**:
A thin marker in the timeline that stands for a long silence of all speakers, in place of empty space.
_Avoid_: Gap, break

**Live edge**:
The current time of the session in the timeline. Segments appear just behind it when they are finalized.
_Avoid_: Now line, bottom

**Overview**:
A small view of the whole session that shows when each speaker spoke, used to move through the timeline.
_Avoid_: Minimap, scrubber

### Inference

**Endpoint**:
A configured network address that serves one model task (transcription, diarization or translation). An endpoint can be on this laptop or on a remote machine.
_Avoid_: Backend, server, provider
