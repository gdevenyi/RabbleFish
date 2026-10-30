"""WER of a hypothesis text file against a reference text file.

Usage: python wer.py REF.txt HYP.txt
Both are normalized: lower case, punctuation removed (apostrophes kept), filler words removed.
"""

import re
import sys

import jiwer

FILLERS = {"um", "uh", "mm", "hmm", "mm-hmm", "uh-huh", "euh", "ah", "oh"}


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^\w\s'-]", " ", text)
    return " ".join(w for w in text.split() if w not in FILLERS)


def main() -> None:
    ref = normalize(open(sys.argv[1], encoding="utf-8").read())
    hyp = normalize(open(sys.argv[2], encoding="utf-8").read())
    out = jiwer.process_words(ref, hyp)
    print(
        f"WER {out.wer:.3f}  (sub {out.substitutions}, del {out.deletions}, "
        f"ins {out.insertions}, ref words {len(ref.split())})"
    )


if __name__ == "__main__":
    main()
