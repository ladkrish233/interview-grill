"""Live Teams transcript: mic + speaker loopback -> Vosk (CPU) -> transcript.jsonl

usage: uv run python capture.py [--out transcript.jsonl] [--list] [--mic NAME] [--loopback NAME] [--model PATH]
Speaker = which device the audio came from: mic = interviewer, loopback = candidate (use headphones).
"""
import argparse, json, sys, threading, time, warnings
from pathlib import Path

if len(sys.argv) < 2:  # soundcard (Linux) builds its program name from argv[1]
    sys.argv.append("--run")
import numpy as np
import soundcard as sc
from vosk import KaldiRecognizer, Model, SetLogLevel

warnings.filterwarnings("ignore", message=".*discontinuity.*")
RATE, BLOCK = 16000, 1600  # 100 ms blocks

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="transcript.jsonl")
ap.add_argument("--list", action="store_true")
ap.add_argument("--mic")
ap.add_argument("--loopback")
ap.add_argument("--model", default=str(Path(__file__).parent / "models/vosk-model-en-us-0.22-lgraph"))
ap.add_argument("--run", action="store_true")
args = ap.parse_args()

if args.list:
    for m in sc.all_microphones(include_loopback=True):
        print("LOOPBACK" if m.isloopback else "MIC     ", m.name)
    sys.exit()


def pick(name, loopback):
    if name:
        return sc.get_microphone(name, include_loopback=True)
    if loopback:
        spk = sc.default_speaker()  # loopback id = speaker id (+ ".monitor" on Linux), name match on Windows
        for m in sc.all_microphones(include_loopback=True):
            if m.isloopback and (spk.id in m.id or spk.name in m.name):
                return m
        sys.exit("no loopback for the default speaker; use --list and --loopback")
    # default_microphone() can be a loopback "monitor" on Linux; never use that as the interviewer's mic
    mics = sc.all_microphones(include_loopback=False)
    if not mics:
        sys.exit("no microphone found; use --list and --mic")
    return mics[0]


SetLogLevel(-1)
model = Model(args.model)
out = open(args.out, "a", buffering=1)
lock, seq = threading.Lock(), [0]


def emit(speaker, text):
    if not text:
        return
    with lock:
        seq[0] += 1
        line = {"seq": seq[0], "t": time.time(), "speaker": speaker, "text": text}
        out.write(json.dumps(line) + "\n")
        print(f"[{speaker}] {text}", file=sys.stderr)


def listen(speaker, dev):
    rec = KaldiRecognizer(model, RATE)
    with dev.recorder(samplerate=RATE, channels=1, blocksize=BLOCK) as r:
        while True:
            pcm = (np.clip(r.record(numframes=BLOCK)[:, 0], -1, 1) * 32767).astype(np.int16).tobytes()
            if rec.AcceptWaveform(pcm):
                emit(speaker, json.loads(rec.Result())["text"])


mic, loop = pick(args.mic, False), pick(args.loopback, True)
print(f"interviewer <- {mic.name}\ncandidate   <- {loop.name}\nwriting {args.out}", file=sys.stderr)
for spk, dev in (("interviewer", mic), ("candidate", loop)):
    threading.Thread(target=listen, args=(spk, dev), daemon=True).start()
while True:
    time.sleep(1)
