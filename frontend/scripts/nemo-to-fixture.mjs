// Converts a recorded NeMo-Speech.cpp realtime event log (JSONL) into the small
// fixture that the dev-only demo mode replays (src/demo/nemoFixture.json).
//
//   node scripts/nemo-to-fixture.mjs <rt_events.jsonl> > src/demo/nemoFixture.json
//
// - Each `.completed` final is split at every change of word `speaker`, as the backend
//   does (one Segment has exactly one Speaker).
// - `lang` comes from a small stop-word count, because the recording has no language.
//   Segments under 3 words get `null`, as the contract says.
// - Partial text is the accumulated `.delta` text, reset at each final.
// - `t` is the wall time of the event in the recording (seconds since the session opened).
import { readFileSync } from 'node:fs'

const FR = new Set(
  'le la les de des du un une et je tu il elle nous vous ils est pas ne plus dans pour qui que lui mes mon sa son ses ce au aux à fis eût était comme faire près sur'.split(' '),
)
const EN = new Set(
  'the a an and i you we it is are to of in on that this what if not by be was me just like think know need yeah okay'.split(' '),
)

// Hand-made translations of the French segments into English (the demo's target language).
const TRANSLATIONS = {
  "panel le second siècle je fis serment d'ouvrir tous les trésors de la terre":
    'panel, the second century I swore to open all the treasures of the earth',
  'à qui compte mes maîtrises en liberté': 'to whoever counts my masteries in freedom',
  'mais je ne fus pas plus heureux': 'but I was no happier',
  "dans le troisième, je promis de faire puissant monarque mon libérateur, d'être toujours près de lui en esprit":
    'in the third, I promised to make my liberator a mighty monarch, to be always near him in spirit',
  "lorsqu'il eût achevé ce repas comme il était bon musulman, il se lavalait main, le visage et les pieds":
    'when he had finished this meal, as he was a good Muslim, he washed his hands, his face and his feet',
  'et fit sa prière': 'and said his prayer',
}

function detectLang(words) {
  if (words.length < 3) return null
  let fr = 0
  let en = 0
  for (const w of words) {
    const k = w.toLowerCase().replace(/[^\p{L}']/gu, '')
    if (FR.has(k) || /[éèêàçù]/.test(k)) fr++
    if (EN.has(k)) en++
  }
  if (fr === en) return null
  return fr > en ? 'fr' : 'en'
}

const round = (x) => Math.round(x * 100) / 100
const lines = readFileSync(process.argv[2], 'utf8').trim().split('\n').map((l) => JSON.parse(l))
const partials = []
const finals = []
let text = ''
for (const e of lines) {
  if (e.type === 'conversation.item.input_audio_transcription.delta') {
    if (!e.delta) continue
    text += e.delta
    partials.push({ t: round(e._t), audio_time: round(e.audio_processed), text: text.trim() })
  } else if (e.type === 'conversation.item.input_audio_transcription.completed') {
    text = ''
    const segments = []
    for (const w of e.words) {
      const last = segments[segments.length - 1]
      const word = { w: w.word, start: round(w.start), end: round(w.end) }
      if (last && last.speaker === w.speaker) {
        last.words.push(word)
        last.end = word.end
      } else segments.push({ speaker: w.speaker, start: word.start, end: word.end, words: [word] })
    }
    for (const s of segments) {
      s.text = s.words.map((w) => w.w).join(' ')
      s.lang = detectLang(s.words.map((w) => w.w))
      if (TRANSLATIONS[s.text]) s.translation = TRANSLATIONS[s.text]
    }
    finals.push({ t: round(e._t), segments })
  }
}
const duration = round(Math.max(...lines.map((e) => e._t ?? 0)))
process.stdout.write(JSON.stringify({ duration, partials, finals }) + '\n')
