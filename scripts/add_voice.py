#!/usr/bin/env python3
"""Adds a community voice to the catalog.

From an approved issue, in the GitHub workflow:

    python3 scripts/add_voice.py --from-issue

reads ISSUE_BODY and ISSUE_AUTHOR from the environment, downloads the file the
issue links to, and prints `name=<voice>` for the workflow's output.

By hand:

    python3 scripts/add_voice.py --name bloop --author you --description "a wet bloop" bloop.mp3

Any audio file works: a .wav is read as is, anything else (.mp3, .m4a, .ogg,
.flac, .aiff, the sound of an .mp4 or .mov...) goes through ffmpeg first. The
sound is checked and made uniform: mono, 16-bit, 22050 Hz, silence
trimmed, at most 0.3 s, faded out, and about as loud as the built-in voices.
It is written to voices/<name>/ (voice.wav for the site, voice.txt, its
base64, for Blip) and catalog.json is rebuilt. Standard library, and ffmpeg
for what is not a .wav.
"""

import argparse
import base64
import datetime
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import wave
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICES = ROOT / "voices"
CATALOG = ROOT / "catalog.json"

RATE = 22050
MAX_SECONDS = 0.3
MIN_SECONDS = 0.02
FADE_SECONDS = 0.01
TARGET_RMS = 0.12
PEAK = 0.9
MAX_DOWNLOAD = 2 * 1024 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,19}$")
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".aif", ".aiff", ".caf", ".webm", ".mp4", ".mov"}
# A file attached to an issue (a zip...), or a video, whose link has no name.
ATTACHMENT = re.compile(
    r"https://github\.com/(?:user-attachments/files/\d+/[^\s)\]]+"
    r"|user-attachments/assets/[0-9a-f-]{36}"
    r"|[\w.-]+/[\w.-]+/files/\d+/[^\s)\]]+)"
)

# The voices Blip ships with (its hooks/voices.ts): listed first on the site.
OFFICIAL = [
    ("classic", "square-wave blip, the classic RPG text box", 1, 5, False),
    ("nes", "thin 8-bit pulse, like an old cartridge", 1, 5, False),
    ("soft", "gentle sine, easy on the ears", 1, 4, False),
    ("bubble", "little rising pops", 1, 6, False),
    ("typewriter", "mechanical keys clacking", 3, 1, False),
    ("robot", "metallic, ring-modulated", 1, 3, False),
    ("deep", "low and ominous, boss-fight energy", 1, 3, False),
    ("chirp", "tiny bird chirps", 1, 7, False),
    ("critter", "a babbling little creature (vowel sounds)", 5, 5, True),
]
RESERVED = {name for name, *_ in OFFICIAL} | {"custom", "on", "off"}


class Refused(Exception):
    """A submission that cannot be added, with the reason to tell its author."""


def fields_of(body):
    """The answers of an issue form: each `### Label` heading and its text."""
    fields = {}
    for part in re.split(r"^### ", body or "", flags=re.M)[1:]:
        label, _, value = part.partition("\n")
        fields[label.strip().lower()] = value.strip()
    return fields


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "blip-voices"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise Refused("the file is over 2 MB: one short sound is all it takes")
    return data


def audio_from(data, url):
    """The audio in a download and its extension: the file itself, or the first
    audio file of a zip."""
    name = url.rsplit("/", 1)[-1].lower()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                extension = Path(member.filename).suffix.lower()
                if extension in AUDIO and "__MACOSX" not in member.filename and member.file_size <= MAX_DOWNLOAD:
                    return archive.read(member), extension
        raise Refused("the zip holds no audio file under 2 MB")
    if Path(name).suffix in AUDIO:
        return data, Path(name).suffix
    if "/user-attachments/assets/" in url:
        return data, ".mp4"
    raise Refused(f"{name} is neither a zip nor an audio file")


def converted(data, extension):
    """Any audio as a mono 16-bit WAV at RATE, through ffmpeg: its first 2 s."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise Refused("this file needs ffmpeg to be read, and it is not installed: send a .wav")
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / f"sound{extension}"
        target = Path(folder) / "sound.wav"
        source.write_bytes(data)
        command = [ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-t", "2", "-vn",
                   "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(target)]
        run = subprocess.run(command, capture_output=True, timeout=60)
        if run.returncode != 0 or not target.exists():
            raise Refused("the sound could not be read: is it really an audio file?")
        return target.read_bytes()


def decoded(data, extension):
    """Mono samples and their rate, from a .wav as is, or from any audio."""
    if data[:4] == b"RIFF":
        try:
            return samples_of(data)
        except Refused:
            if shutil.which("ffmpeg") is None:
                raise
    return samples_of(converted(data, extension))


def samples_of(data):
    """Mono samples from -1 to 1, and their rate."""
    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as error:
        raise Refused(f"the .wav could not be read ({error}): export it as 16-bit PCM WAV") from error

    if width == 1:
        values = [(b - 128) / 128 for b in frames]
    elif width == 2:
        values = [v / 32768 for v in struct.unpack(f"<{len(frames) // 2}h", frames)]
    elif width == 3:
        values = [int.from_bytes(frames[i : i + 3], "little", signed=True) / 8388608 for i in range(0, len(frames), 3)]
    elif width == 4:
        values = [v / 2147483648 for v in struct.unpack(f"<{len(frames) // 4}i", frames)]
    else:
        raise Refused(f"{width * 8}-bit audio is not supported: export it as 16-bit PCM WAV")

    mono = [sum(values[i : i + channels]) / channels for i in range(0, len(values), channels)]
    return mono, rate


def uniform(samples, rate):
    """Resampled to RATE, silence trimmed, cut to MAX_SECONDS, faded, levelled."""
    if rate != RATE:
        step = rate / RATE
        samples = [
            samples[int(j * step)] + (samples[min(int(j * step) + 1, len(samples) - 1)] - samples[int(j * step)]) * (j * step - int(j * step))
            for j in range(int((len(samples) - 1) / step))
        ]

    peak = max((abs(s) for s in samples), default=0)
    if peak < 0.001:
        raise Refused("the sound is silent")
    loud = [i for i, s in enumerate(samples) if abs(s) > peak * 0.05]
    samples = samples[loud[0] : loud[-1] + 1]

    samples = samples[: int(MAX_SECONDS * RATE)]
    if len(samples) < MIN_SECONDS * RATE:
        raise Refused("the sound is too short once its silence is trimmed")
    fade = min(len(samples), int(FADE_SECONDS * RATE))
    for i in range(fade):
        samples[-1 - i] *= i / fade

    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) or 1
    scale = TARGET_RMS / rms
    peak = max(abs(s) for s in samples) * scale
    if peak > PEAK:
        scale *= PEAK / peak
    return [s * scale for s in samples]


def wav_bytes(samples):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    return out.getvalue()


def add(name, author, description, data, extension=".wav"):
    name = name.strip().lower()
    description = " ".join(description.split())
    if not NAME.match(name):
        raise Refused("the name takes 2 to 20 lowercase letters, digits or dashes")
    if name in RESERVED or (VOICES / name).exists():
        raise Refused(f"there is already a voice named {name}: pick another name")
    if not 1 <= len(description) <= 60:
        raise Refused("the description takes 1 to 60 characters")

    wav = wav_bytes(uniform(*decoded(data, extension)))
    folder = VOICES / name
    folder.mkdir(parents=True)
    (folder / "voice.wav").write_bytes(wav)
    (folder / "voice.txt").write_text(base64.b64encode(wav).decode() + "\n")
    meta = {
        "name": name,
        "author": author,
        "description": description,
        "license": "CC0-1.0",
        "added": datetime.date.today().isoformat(),
    }
    (folder / "voice.json").write_text(json.dumps(meta, indent=2) + "\n")
    build_catalog()
    return name


def build_catalog():
    official = [
        {"name": n, "author": "blip", "description": d, "official": True, "variants": v, "spread": s, "vowels": vw}
        for n, d, v, s, vw in OFFICIAL
    ]
    community = sorted(
        (json.loads(p.read_text()) for p in VOICES.glob("*/voice.json")),
        key=lambda v: (v.get("added", ""), v["name"]),
        reverse=True,
    )
    CATALOG.write_text(json.dumps({"voices": official + community}, indent=2, ensure_ascii=False) + "\n")


def from_issue():
    fields = fields_of(os.environ.get("ISSUE_BODY", ""))
    author = os.environ.get("ISSUE_AUTHOR", "").strip()
    sound = fields.get("sound", "")
    url = ATTACHMENT.search(sound)
    if url is None:
        raise Refused("no file attached: drag your zipped sound into the Sound field")
    data, extension = audio_from(download(url.group(0)), url.group(0))
    return add(fields.get("voice name", ""), author, fields.get("description", ""), data, extension)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-issue", action="store_true", help="read the approved issue from the environment")
    parser.add_argument("--name")
    parser.add_argument("--author")
    parser.add_argument("--description")
    parser.add_argument("--catalog-only", action="store_true", help="only rebuild catalog.json")
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args()

    try:
        if args.catalog_only:
            build_catalog()
            return
        if args.from_issue:
            name = from_issue()
        else:
            if not (args.name and args.author and args.description and args.file):
                parser.error("give --name, --author, --description and a sound file, or --from-issue")
            name = add(args.name, args.author, args.description, args.file.read_bytes(), args.file.suffix.lower())
    except Refused as refused:
        message = str(refused)
        if os.environ.get("ERROR_FILE"):
            Path(os.environ["ERROR_FILE"]).write_text(message + "\n")
        print(f"refused: {message}", file=sys.stderr)
        sys.exit(1)

    print(f"name={name}")


if __name__ == "__main__":
    main()
