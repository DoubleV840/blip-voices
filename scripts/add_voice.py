#!/usr/bin/env python3
"""Checks, adds and removes community voices.

In the GitHub workflow that publishes a submission, in two jobs:

    python3 scripts/add_voice.py --prepare-issue DIR   # check it, write the voice to DIR
    python3 scripts/add_voice.py --publish DIR         # check DIR again, add it to the catalog

The first reads ISSUE_TITLE, ISSUE_BODY, ISSUE_AUTHOR and AUTHOR_CREATED (the
account's creation date) from the environment and handles the submitted file,
with no credentials; the second never opens that file. Both print `key=value`
lines for the workflow (status, name, reason).

By hand:

    python3 scripts/add_voice.py --name bloop --author you --theme cute --description "a wet bloop" bloop.mp3
    python3 scripts/add_voice.py --remove bloop

A voice is a sound, never a video. Any audio file works: a .wav is read as is,
anything else (.mp3, .m4a, .ogg, .flac, .aiff...) goes through ffmpeg first.
The sound is made uniform: mono, 16-bit, 22050 Hz, silence trimmed, at most
0.3 s, faded out, and about as loud as the built-in voices. It is written to
voices/<name>/ (voice.wav for the site, voice.txt, its base64, for Blip) and
catalog.json is rebuilt. A removed voice is listed in removed.json, and Blip
deletes it from the machines that installed it.

Names, descriptions and titles are checked against blocklist.txt and the
English and French lists of the LDNOOBW project.
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
import unicodedata
import urllib.request
import wave
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICES = ROOT / "voices"
CATALOG = ROOT / "catalog.json"
REMOVED = ROOT / "removed.json"
BLOCKLIST = Path(__file__).resolve().parent / "blocklist.txt"
SHARED_BLOCKLISTS = [
    "https://raw.githubusercontent.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words/master/en",
    "https://raw.githubusercontent.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words/master/fr",
]

RATE = 22050
MAX_SECONDS = 0.3
MIN_SECONDS = 0.02
FADE_SECONDS = 0.01
TARGET_RMS = 0.12
PEAK = 0.9
MAX_DOWNLOAD = 2 * 1024 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,19}$")
LOGIN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
# Against throwaway accounts and floods.
MIN_ACCOUNT_DAYS = 7
MAX_PER_DAY = 3
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".aif", ".aiff", ".caf"}
# A file attached to an issue: GitHub takes audio zipped.
ATTACHMENT = re.compile(r"https://github\.com/(?:user-attachments/files|[\w.-]+/[\w.-]+/files)/\d+/[^\s)\]]+")

THEMES = ["retro", "cute", "soft", "machine", "creature", "dark", "weird"]

# The voices Blip ships with (its hooks/voices.ts): listed first on the site.
OFFICIAL = [
    ("classic", "square-wave blip, the classic RPG text box", "retro", 1, 5, False),
    ("nes", "thin 8-bit pulse, like an old cartridge", "retro", 1, 5, False),
    ("soft", "gentle sine, easy on the ears", "soft", 1, 4, False),
    ("bubble", "little rising pops", "cute", 1, 6, False),
    ("typewriter", "mechanical keys clacking", "machine", 3, 1, False),
    ("robot", "metallic, ring-modulated", "machine", 1, 3, False),
    ("deep", "low and ominous, boss-fight energy", "dark", 1, 3, False),
    ("chirp", "tiny bird chirps", "creature", 1, 7, False),
    ("critter", "a babbling little creature (vowel sounds)", "creature", 5, 5, True),
]
RESERVED = {name for name, *_ in OFFICIAL} | {"custom", "on", "off"}


class Refused(Exception):
    """A submission that cannot be added, with the reason to tell its author."""


class Offensive(Refused):
    """A submission whose words are not allowed: removed, not just refused."""


# ---- Words -----------------------------------------------------------------

LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def plain_words(text):
    """Lowercase words, accents and leetspeak undone."""
    plain = unicodedata.normalize("NFKD", (text or "").lower().translate(LEET))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", plain)


_blocked = None


def blocked_terms():
    """The blocked words and phrases, each as its plain words joined by spaces."""
    global _blocked
    if _blocked is None:
        lines = BLOCKLIST.read_text().splitlines() if BLOCKLIST.exists() else []
        for url in SHARED_BLOCKLISTS:
            try:
                with urllib.request.urlopen(url, timeout=15) as response:
                    lines += response.read().decode("utf-8", "replace").splitlines()
            except OSError:
                pass  # The local list still applies.
        terms = {" ".join(plain_words(line)) for line in lines if line.strip() and not line.startswith("#")}
        _blocked = {t for t in terms if len(t) >= 3}
    return _blocked


def check_words(*texts):
    """Raises Offensive when a text holds a blocked word or phrase, spelled
    plainly, with a letter held (fuuun), or spread with dashes (f-u-n)."""
    terms = blocked_terms()
    for text in texts:
        words = plain_words(text)
        held = [re.sub(r"(.)\1+", r"\1", w) for w in words]
        squashed = "".join(words)
        for spelled in (words, held):
            joined = f" {' '.join(spelled)} "
            if any(f" {term} " in joined for term in terms):
                raise Offensive("its name, title or description holds a word that isn't allowed")
        if len(squashed) >= 4 and squashed in terms:
            raise Offensive("its name, title or description holds a word that isn't allowed")


# ---- Sound -----------------------------------------------------------------


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
    """The audio in a download and its extension: the first sound file of a
    zip, or the file itself."""
    name = url.rsplit("/", 1)[-1].lower()
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                extension = Path(member.filename).suffix.lower()
                if extension in AUDIO and "__MACOSX" not in member.filename and member.file_size <= MAX_DOWNLOAD:
                    return archive.read(member), extension
        raise Refused("the zip holds no sound file (.wav, .mp3, .m4a, .ogg, .flac...) under 2 MB")
    if Path(name).suffix in AUDIO:
        return data, Path(name).suffix
    raise Refused(f"{name} is not a zipped sound file")


def has_video(path):
    """Whether a file holds moving pictures; an mp3's cover art is fine."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return False
    run = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=30)
    streams = json.loads(run.stdout or b"{}").get("streams", [])
    return any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams)


def converted(data, extension):
    """Any sound as a mono 16-bit WAV at RATE, through ffmpeg: its first 2 s."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise Refused("this file needs ffmpeg to be read, and it is not installed: send a .wav")
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / f"sound{extension}"
        target = Path(folder) / "sound.wav"
        source.write_bytes(data)
        if has_video(source):
            raise Refused("this file holds a video: send a sound only")
        command = [ffmpeg, "-nostdin", "-v", "error", "-i", str(source), "-t", "2", "-vn",
                   "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(target)]
        run = subprocess.run(command, capture_output=True, timeout=60)
        if run.returncode != 0 or not target.exists():
            raise Refused("the sound could not be read: is it really a sound file?")
        return target.read_bytes()


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


def decoded(data, extension):
    """Mono samples and their rate, from a .wav as is, or from any sound file."""
    if data[:4] == b"RIFF":
        try:
            return samples_of(data)
        except Refused:
            if shutil.which("ffmpeg") is None:
                raise
    return samples_of(converted(data, extension))


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


# ---- The catalog -----------------------------------------------------------


def prepared(name, theme, description, data, extension, title="", check_sound=True):
    """A submission checked and its sound made uniform, nothing written yet.
    A name is forgiven its capitals and spaces: "Cat Meow" is cat-meow."""
    name = re.sub(r"[\s_]+", "-", name.strip().lower()).strip("-")
    theme = theme.strip().lower()
    description = " ".join(description.split())
    check_words(name, description, title)
    if not NAME.match(name):
        raise Refused("the name takes 2 to 20 letters, digits or dashes, like cat-meow")
    if name in RESERVED or (VOICES / name).exists() or name in removed():
        raise Refused(f"there is already a voice named {name}: pick another name")
    if theme not in THEMES:
        raise Refused(f"the theme is one of {', '.join(THEMES)}")
    if not 1 <= len(description) <= 60:
        raise Refused("the description takes 1 to 60 characters")
    return name, theme, description, wav_bytes(uniform(*decoded(data, extension))) if check_sound else b""


def add(name, author, theme, description, data, extension=".wav"):
    name, theme, description, wav = prepared(name, theme, description, data, extension)
    write_voice(VOICES / name, name, author, theme, description, wav)
    build_catalog()
    return name


def write_voice(folder, name, author, theme, description, wav):
    folder.mkdir(parents=True)
    (folder / "voice.wav").write_bytes(wav)
    (folder / "voice.txt").write_text(base64.b64encode(wav).decode() + "\n")
    meta = {
        "name": name,
        "author": author,
        "theme": theme,
        "description": description,
        "license": "CC0-1.0",
        "added": datetime.date.today().isoformat(),
    }
    (folder / "voice.json").write_text(json.dumps(meta, indent=2) + "\n")


def publish(folder):
    """Adds a voice prepared by --prepare-issue, checked again without ffmpeg:
    its fields, its .wav's shape, its .txt matching it."""
    meta = json.loads((folder / "voice.json").read_text())
    wav = (folder / "voice.wav").read_bytes()
    name, author = str(meta.get("name", "")), str(meta.get("author", ""))
    if not LOGIN.match(author):
        raise Refused("the author is not a GitHub login")
    name, theme, description, _ = prepared(name, str(meta.get("theme", "")), str(meta.get("description", "")), b"", ".wav", check_sound=False)
    with wave.open(io.BytesIO(wav)) as sound:
        shape = (sound.getnchannels(), sound.getsampwidth(), sound.getframerate())
        frames = sound.getnframes()
    if shape != (1, 2, RATE) or frames > MAX_SECONDS * RATE + 1:
        raise Refused("the prepared sound is not what --prepare-issue writes")
    if (folder / "voice.txt").read_text().strip() != base64.b64encode(wav).decode():
        raise Refused("the prepared voice.txt does not match its voice.wav")
    write_voice(VOICES / name, name, author, theme, description, wav)
    build_catalog()
    return name


def check_author(author, created):
    """Refuses an account younger than a week, and a fourth voice in a day."""
    if not LOGIN.match(author):
        raise Refused("the author is not a GitHub login")
    try:
        born = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as error:
        raise Refused("the author's account could not be checked") from error
    if datetime.datetime.now(datetime.timezone.utc) - born < datetime.timedelta(days=MIN_ACCOUNT_DAYS):
        raise Refused(f"voices are shared from GitHub accounts at least {MIN_ACCOUNT_DAYS} days old: come back soon")
    today = datetime.date.today().isoformat()
    shared_today = [
        v for v in (json.loads(p.read_text()) for p in VOICES.glob("*/voice.json"))
        if v.get("author") == author and v.get("added") == today
    ]
    if len(shared_today) >= MAX_PER_DAY:
        raise Refused(f"{MAX_PER_DAY} voices a day at most: this one is welcome tomorrow")


def removed():
    return json.loads(REMOVED.read_text()) if REMOVED.exists() else []


def remove(name):
    folder = VOICES / name
    if not folder.is_dir():
        raise Refused(f"there is no community voice named {name}")
    shutil.rmtree(folder)
    REMOVED.write_text(json.dumps(sorted({*removed(), name}), indent=2) + "\n")
    build_catalog()


def build_catalog():
    official = [
        {"name": n, "author": "blip", "theme": t, "description": d, "official": True, "variants": v, "spread": s, "vowels": vw}
        for n, d, t, v, s, vw in OFFICIAL
    ]
    community = sorted(
        (json.loads(p.read_text()) for p in VOICES.glob("*/voice.json")),
        key=lambda v: (v.get("added", ""), v["name"]),
        reverse=True,
    )
    catalog = {"themes": THEMES, "voices": official + community, "removed": removed()}
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")


# ---- Issues ----------------------------------------------------------------


def submission():
    """The submission an issue holds: its title, its fields, and its sound."""
    title = os.environ.get("ISSUE_TITLE", "")
    fields = fields_of(os.environ.get("ISSUE_BODY", ""))
    check_words(title, fields.get("voice name", ""), fields.get("description", ""))
    url = ATTACHMENT.search(fields.get("sound", ""))
    if url is None:
        raise Refused("no sound attached: drag your sound file (or a zip of it) into the Sound field")
    data, extension = audio_from(download(url.group(0)), url.group(0))
    return title, fields, data, extension


def prepare_issue(folder):
    """Checks the submission in the environment and writes its voice to `folder`."""
    author = os.environ.get("ISSUE_AUTHOR", "").strip()
    title, fields, data, extension = submission()
    check_author(author, os.environ.get("AUTHOR_CREATED", ""))
    name, theme, description, wav = prepared(
        fields.get("voice name", ""), fields.get("theme", ""), fields.get("description", ""), data, extension, title
    )
    write_voice(folder, name, author, theme, description, wav)
    return name, theme, (len(wav) - 44) / 2 / RATE


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prepare-issue", metavar="DIR", type=Path, help="check the submission in the environment")
    parser.add_argument("--publish", metavar="DIR", type=Path, help="add a voice --prepare-issue wrote")
    parser.add_argument("--remove", metavar="NAME", help="remove a community voice")
    parser.add_argument("--catalog-only", action="store_true", help="only rebuild catalog.json")
    parser.add_argument("--name")
    parser.add_argument("--author")
    parser.add_argument("--theme")
    parser.add_argument("--description")
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args()

    try:
        if args.catalog_only:
            build_catalog()
        elif args.remove:
            remove(args.remove)
            print(f"name={args.remove}")
        elif args.prepare_issue:
            name, theme, seconds = prepare_issue(args.prepare_issue)
            print(f"status=ok\nname={name}\ntheme={theme}\nseconds={seconds:.2f}")
        elif args.publish:
            print(f"status=ok\nname={publish(args.publish)}")
        else:
            if not (args.name and args.author and args.theme and args.description and args.file):
                parser.error("give --name, --author, --theme, --description and a sound file")
            name = add(args.name, args.author, args.theme, args.description, args.file.read_bytes(), args.file.suffix.lower())
            print(f"name={name}")
    except Refused as refused:
        # Checking a submission, a refusal is an answer, not a failure.
        if args.prepare_issue:
            status = "offensive" if isinstance(refused, Offensive) else "invalid"
            print(f"status={status}\nreason={refused}")
            return
        if os.environ.get("ERROR_FILE"):
            Path(os.environ["ERROR_FILE"]).write_text(f"{refused}\n")
        print(f"refused: {refused}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
