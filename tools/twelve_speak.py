#!/usr/bin/env python3
"""Twelve Twelve Labs: read a script in a cloned voice, one sentence at a time,
and check every sentence by transcribing it back.

CSM (the cloning model) drops or garbles words on long inputs. This tool splits
the script into sentences, generates each one with the reference voice, has the
speech-to-text engine transcribe the result, and regenerates any sentence whose
words don't match, keeping the best attempt. It talks to the local API, so the
backend must be running (default http://127.0.0.1:3900).

    python tools/twelve_speak.py --ref me.wav --ref-text "words said in me.wav" \
        --text script.txt --out episode_voice.wav

Needs only the standard library plus ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import difflib
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900")
SAMPLE_RATE = 24000


def split_sentences(text: str, max_chars: int = 180) -> list[str]:
    """Sentence-sized chunks. Long sentences break at commas/semicolons."""
    text = re.sub(r"\s+", " ", text).strip()
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        sent = sent.strip()
        if not sent:
            continue
        while len(sent) > max_chars:
            cut = max(sent.rfind(", ", 0, max_chars), sent.rfind("; ", 0, max_chars))
            if cut < max_chars // 3:
                cut = sent.rfind(" ", 0, max_chars)
            if cut <= 0:
                break
            out.append(sent[: cut + 1].strip())
            sent = sent[cut + 1:].strip()
        if sent:
            out.append(sent)
    return out


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def similarity(want: str, heard: str) -> float:
    """0..1 word-level match between the script sentence and its transcription."""
    a, b = _words(want), _words(heard)
    if not a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, p in files.items():
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
                 f'filename="{p.name}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
        body += p.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _post(url: str, fields: dict[str, str], files: dict[str, Path], timeout: int) -> bytes:
    body, ctype = _multipart(fields, files)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from None


def _post_json(url: str, payload: dict, timeout: int) -> bytes:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=timeout).read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {url} ({e}). Is the backend running? "
                           "cd ~/TwelveTwelveLabs && bun run dev:api") from None


def generate(base: str, text: str, ref: Path, ref_text: str, timeout: int = 280) -> bytes:
    return _post(f"{base}/generate",
                 {"text": text, "engine": "mlx-audio", "ref_text": ref_text, "language": "English"},
                 {"ref_audio": ref}, timeout)


def transcribe(base: str, wav: Path, timeout: int = 120) -> str:
    raw = _post(f"{base}/v1/audio/transcriptions",
                {"language": "en", "response_format": "json"}, {"file": wav}, timeout)
    return json.loads(raw).get("text", "")


def concat(parts: list[Path], out: Path, gap: float) -> None:
    """Join sentence clips with a short pause, mono 24 kHz, light loudness match."""
    with tempfile.TemporaryDirectory() as td:
        silence = Path(td) / "gap.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", str(gap), str(silence)], check=True)
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{p}'\nfile '{silence}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-ar", str(SAMPLE_RATE), "-ac", "1", "-af", "loudnorm=I=-18:TP=-2", str(out)],
                       check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, type=Path, help="reference recording of the voice (10-20 s, clean)")
    ap.add_argument("--ref-text", required=True, help="the exact words spoken in the reference")
    ap.add_argument("--text", required=True, help="script text, or a path to a .txt file")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--attempts", type=int, default=3, help="tries per sentence when the check fails")
    ap.add_argument("--threshold", type=float, default=0.85, help="word match needed to accept a sentence")
    ap.add_argument("--gap", type=float, default=0.3, help="pause between sentences, seconds")
    ap.add_argument("--no-verify", action="store_true", help="skip the speech-to-text check")
    args = ap.parse_args()

    script = Path(args.text).read_text() if Path(args.text).is_file() else args.text
    sentences = split_sentences(script)
    if not sentences:
        print("nothing to read", file=sys.stderr)
        return 2
    print(f"{len(sentences)} sentence(s); verify={'off' if args.no_verify else 'on'}")

    # Cloning needs the CSM model active; the backend keeps whichever model was used last.
    _post_json(f"{args.url}/engines/select",
               {"family": "tts", "backend_id": "mlx-audio", "model_id": "csm"}, 120)

    work = Path(tempfile.mkdtemp(prefix="twelve_"))
    kept: list[Path] = []
    report = []
    for i, sent in enumerate(sentences):
        best_score, best_path = -1.0, None
        for attempt in range(1, (1 if args.no_verify else args.attempts) + 1):
            path = work / f"s{i:03d}_a{attempt}.wav"
            path.write_bytes(generate(args.url, sent, args.ref, args.ref_text))
            if args.no_verify:
                best_score, best_path = 1.0, path
                break
            heard = transcribe(args.url, path)
            score = similarity(sent, heard)
            print(f"  [{i + 1}/{len(sentences)}] try {attempt}: match {score:.2f}  heard: {heard.strip()[:90]}")
            if score > best_score:
                best_score, best_path = score, path
            if score >= args.threshold:
                break
        kept.append(best_path)
        report.append({"sentence": sent, "score": round(best_score, 2),
                       "ok": args.no_verify or best_score >= args.threshold})

    concat(kept, args.out, args.gap)
    weak = [r for r in report if not r["ok"]]
    print(f"wrote {args.out}  ({len(weak)} sentence(s) below threshold)")
    for r in weak:
        print(f"  weak ({r['score']}): {r['sentence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
