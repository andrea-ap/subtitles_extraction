# -*- coding: utf-8 -*-
"""Traduzione sottotitoli: video (MKV/MP4) -> sottotitoli italiani (GUI portatile).

Pipeline: [sottotitolo incorporato | audio -> Whisper] -> film.<lingua>.srt -> Argos -> film.it.srt
Lingue sorgente: inglese, spagnolo, russo, ucraino
Uso:  Avvia.bat            (GUI)
      python app.py --cli film.mkv [--model small|medium|large-v3] [--lang auto|en|es|ru|uk] [--force]
"""
import json
import os
import queue
import re
import subprocess
import sys
import textwrap
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUNTIME = BASE / "runtime"
MODELS_DIR = RUNTIME / "models"
LOG_FILE = BASE / "app.log"

# --- ambiente --------------------------------------------------------------
if sys.executable.lower().endswith("pythonw.exe") or sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(LOG_FILE, "w", encoding="utf-8")
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HOME"] = str(MODELS_DIR)
os.environ["ARGOS_PACKAGES_DIR"] = str(RUNTIME / "argos")


def _setup_paths():
    dirs = []
    ff = RUNTIME / "ffmpeg"
    if ff.exists():
        dirs.append(ff)
    for p in sys.path:
        nv = Path(p) / "nvidia"
        if nv.is_dir():
            dirs += [d for d in nv.glob("*/bin") if d.is_dir()]
    for d in dirs:
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(d))
        except (AttributeError, OSError):
            pass


_setup_paths()

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm"}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
LANGS = {"eng": "Inglese", "en": "Inglese", "ita": "Italiano", "it": "Italiano", "fra": "Francese",
         "fre": "Francese", "spa": "Spagnolo", "deu": "Tedesco", "ger": "Tedesco", "jpn": "Giapponese",
         "por": "Portoghese", "rus": "Russo", "zho": "Cinese", "chi": "Cinese", "kor": "Coreano",
         "und": "Non specificata", "": "Non specificata"}


class Cancelled(Exception):
    pass


# --- ffprobe ---------------------------------------------------------------
def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, creationflags=NOWIN, **kw)


def probe(mkv):
    r = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(mkv)])
    if r.returncode != 0:
        raise RuntimeError("ffprobe: " + (r.stderr.strip() or "errore"))
    d = json.loads(r.stdout)
    audio, subs, ai = [], [], 0
    for s in d.get("streams", []):
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        item = {"lang": tags.get("language", "und").lower(), "codec": s.get("codec_name", "?"),
                "title": tags.get("title", ""), "index": s["index"]}
        if s.get("codec_type") == "audio":
            item.update(pos=ai, ch=s.get("channels", 0))
            audio.append(item)
            ai += 1
        elif s.get("codec_type") == "subtitle":
            item["forced"] = int((s.get("disposition") or {}).get("forced", 0))
            subs.append(item)
    return {"duration": float(d.get("format", {}).get("duration") or 0), "audio": audio, "subs": subs}


SRC_LANGS = {"en": ("Inglese", ("eng", "en")), "es": ("Spagnolo", ("spa", "es")),
             "ru": ("Russo", ("rus", "ru")), "uk": ("Ucraino", ("ukr", "uk"))}
LANG_CHOICES = ["Automatica"] + [v[0] for v in SRC_LANGS.values()]
LANG_BY_NAME = {v[0]: k for k, v in SRC_LANGS.items()}


def iso2(code3):
    for k, (_, codes) in SRC_LANGS.items():
        if code3 in codes:
            return k
    return None


def best_sub(subs, lang):
    codes = SRC_LANGS[lang][1]
    c = [s for s in subs if s["lang"] in codes and s["codec"] in TEXT_CODECS]
    c.sort(key=lambda s: s["forced"])
    return c[0] if c else None


def gpu_name():
    try:
        r = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def fmt_time(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# --- traduzione ------------------------------------------------------------
def _clean(line):
    line = re.sub(r"\{\\[^}]*\}", "", line)
    return re.sub(r"<[^>]+>", "", line).strip()


def _prepare(raw):
    """-> (parti da tradurre, dialogo?, corsivo?)"""
    italic = bool(re.search(r"<i>", raw, re.I))
    lines = [_clean(l) for l in raw.splitlines()]
    lines = [l for l in lines if l]
    dialogue = len(lines) > 1 and sum(l.startswith(("-", "–", "—")) for l in lines) >= 2
    parts = lines if dialogue else ([" ".join(lines)] if lines else [])
    return parts, dialogue, italic


_ACC = {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}


def _fix_accents(text):
    """Argos scrive spesso saro', piu', e' al posto di sarò, più, è."""
    def rep(m):
        w = m.group(0)
        if w.lower() in ("po'", "mo'", "be'"):
            return w
        if w.lower().endswith("che'"):
            return w[:-2] + "é"
        return w[:-2] + _ACC[w[-2].lower()] if w[-2].islower() else w[:-2] + _ACC[w[-2].lower()].upper()
    return re.sub(r"\b[A-Za-z]*[aeiouAEIOU]'(?![A-Za-z])", rep, text)


def _assemble(parts, dialogue, italic):
    parts = [_fix_accents(p) for p in parts]
    if dialogue:
        text = "\n".join(parts)
    else:
        text = parts[0]
        if len(text) > 44:
            text = "\n".join(textwrap.wrap(text, 44))
    return f"<i>{text}</i>" if italic else text


# --- lavoro ----------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, q, mkv, info, audio_pos, model, force, lang="auto"):
        super().__init__(daemon=True)
        self.q, self.mkv, self.info = q, Path(mkv), info
        self.audio_pos, self.model, self.force, self.lang = audio_pos, model, force, lang
        self.stop = threading.Event()

    # messaggi verso la GUI
    def log(self, text):
        self.q.put(("log", text))

    def indet(self, label):
        self.q.put(("indet", label))

    def prog(self, overall, frac, label):
        self.q.put(("prog", overall, max(0.0, min(1.0, frac)), label))

    def check(self):
        if self.stop.is_set():
            raise Cancelled

    def run(self):
        try:
            self.pipeline()
        except Cancelled:
            self.q.put(("cancelled",))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    # --- ffmpeg con avanzamento
    def run_ffmpeg(self, args, duration=0, on_frac=None):
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-progress", "pipe:1"] + [str(a) for a in args]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
        known = re.compile(r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time_us|out_time_ms|out_time|"
                           r"dup_frames|drop_frames|speed|progress)=")
        errs = []
        for line in p.stdout:
            if self.stop.is_set():
                p.kill()
                raise Cancelled
            line = line.strip()
            if line.startswith("out_time_us="):
                v = line.split("=", 1)[1]
                if v.isdigit() and duration and on_frac:
                    on_frac(int(v) / 1e6 / duration)
            elif line and not known.match(line):
                errs.append(line)
        p.wait()
        if p.returncode != 0:
            raise RuntimeError("ffmpeg: " + " | ".join(errs[-4:]))

    # --- trascrizione
    def transcribe(self, wav, duration, lang, lo, hi):
        from faster_whisper import WhisperModel
        import srt
        for dev, ctype in (("cuda", "float16"), ("cpu", "int8")):
            try:
                self.indet(f"Caricamento modello {self.model} su {dev.upper()} (al primo uso viene scaricato)")
                self.log(f"Carico il modello Whisper '{self.model}' su {dev.upper()} ({ctype})...")
                MODELS_DIR.mkdir(parents=True, exist_ok=True)
                model = WhisperModel(self.model, device=dev, compute_type=ctype, download_root=str(MODELS_DIR))
                segs, tinfo = model.transcribe(str(wav), language=lang, vad_filter=True, beam_size=5,
                                               condition_on_previous_text=False)
                self.log(f"Lingua audio: {tinfo.language} ({tinfo.language_probability:.0%}). Trascrivo...")
                out = []
                for seg in segs:
                    self.check()
                    text = seg.text.strip()
                    if text:
                        out.append(srt.Subtitle(index=len(out) + 1, start=timedelta(seconds=seg.start),
                                                end=timedelta(seconds=seg.end), content=text))
                    f = seg.end / duration if duration else 0
                    self.prog(lo + (hi - lo) * f, f, f"Trascrizione ({dev.upper()})")
                return out, tinfo.language
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                if dev == "cpu":
                    raise
                self.log(f"GPU non utilizzabile ({type(e).__name__}: {e}). Riprovo su CPU: sara piu lento.")
        return [], lang

    # --- traduzione (Argos Translate, offline)
    def argos_get(self, src):
        """Carica (e al primo uso scarica) i modelli offline src->it (passando da un'altra lingua se serve)."""
        import argostranslate.package as ap
        import argostranslate.translate as at

        # Percorsi: il modello Argos es->en e' difettoso (ripete "mainstre..."), quindi lo spagnolo passa dal portoghese.
        hops = [(src, "pt"), ("pt", "it")] if src == "es" else [(src, "it")]

        def find():
            langs = {l.code: l for l in at.get_installed_languages()}
            steps = []
            for a, b in hops:
                if a not in langs or b not in langs:
                    return None
                t = langs[a].get_translation(langs[b])
                if t is None:
                    return None
                steps.append(t)

            class Chain:
                def translate(self, text):
                    for t in steps:
                        text = t.translate(text)
                    return text
            return Chain()

        tr = find()
        if tr is None:
            name = SRC_LANGS.get(src, (src,))[0]
            self.indet(f"Scarico i modelli di traduzione {name}→italiano (solo la prima volta)")
            self.log(f"Scarico i modelli Argos {src}->it (solo la prima volta, 100-500 MB)...")
            ap.update_package_index()
            have = {(p.from_code, p.to_code): p for p in ap.get_available_packages()}
            installed = {(p.from_code, p.to_code) for p in ap.get_installed_packages()}
            need = []
            for a, b in hops:
                need += [(a, b)] if (a, b) in have else [(a, "en"), ("en", b)]
            for pair in need:
                if pair in installed:
                    continue
                if pair not in have:
                    raise RuntimeError(f"modello {pair[0]}->{pair[1]} non disponibile in Argos")
                self.log(f"  scarico {pair[0]}->{pair[1]}...")
                ap.install_from_path(have[pair].download())
            tr = find()
        if tr is None:
            raise RuntimeError(f"modello di traduzione {src}->it non disponibile (serve internet al primo uso)")
        return tr

    def translate(self, subs, src, lo, hi):
        import srt
        tr = self.argos_get(src)
        total, out, failed = len(subs), [], 0
        for n, s in enumerate(subs, 1):
            self.check()
            parts, dialogue, italic = _prepare(s.content)
            text = s.content
            if parts:
                try:
                    text = _assemble([tr.translate(p).strip() or p for p in parts], dialogue, italic)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    failed += 1
            out.append(srt.Subtitle(index=s.index, start=s.start, end=s.end, content=text))
            if n % 5 == 0 or n == total:
                f = n / total
                self.prog(lo + (hi - lo) * f, f, f"Traduzione {n}/{total}")
        if failed:
            self.log(f"Attenzione: {failed} sottotitoli non tradotti (lasciati in originale).")
        return out

    def pipeline(self):
        import srt
        mkv, info = self.mkv, self.info
        it_srt = mkv.with_suffix(".it.srt")
        want = self.lang if self.lang != "auto" else "en"  # con "Automatica" i sottotitoli incorporati cercati sono inglesi
        sub = None if self.force else best_sub(info["subs"], want)
        src = want if sub is not None else (self.lang if self.lang != "auto" else None)

        if sub is not None:
            en_srt = mkv.with_suffix(f".{want}.srt")
            self.log(f"Uso il sottotitolo {SRC_LANGS[want][0].lower()} incorporato (stream {sub['index']}, {sub['codec']}).")
            self.indet("Estrazione sottotitoli incorporati")
            self.run_ffmpeg(["-i", mkv, "-map", f"0:{sub['index']}", en_srt])
            subs = list(srt.parse(en_srt.read_text(encoding="utf-8", errors="replace")))
            t_lo = 10
            self.prog(10, 1, "Estrazione sottotitoli")
        else:
            self.log("force-whisper attivo: ignoro i sottotitoli incorporati." if self.force
                     else "Nessun sottotitolo testuale utilizzabile: trascrivo l'audio con Whisper.")
            tmp = RUNTIME / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            wav = tmp / "audio.wav"
            try:
                self.log("Estraggo l'audio...")
                self.run_ffmpeg(["-i", mkv, "-map", f"0:a:{self.audio_pos}", "-vn", "-ac", "1", "-ar", "16000", wav],
                                info["duration"], lambda f: self.prog(8 * f, f, "Estrazione audio"))
                subs, detected = self.transcribe(wav, info["duration"], src, 8, 65)
            finally:
                try:
                    wav.unlink()
                except OSError:
                    pass
            if not subs:
                raise RuntimeError("Nessun parlato riconosciuto nell'audio.")
            src = src or detected
            en_srt = mkv.with_suffix(f".{src}.srt")
            en_srt.write_text(srt.compose(subs), encoding="utf-8")
            t_lo = 65

        self.log(f"Salvato: {en_srt.name} ({len(subs)} sottotitoli)")
        if src == "it":
            raise RuntimeError("L'audio \u00e8 gi\u00e0 in italiano: i sottotitoli sono in " + en_srt.name)
        if src not in SRC_LANGS:
            raise RuntimeError(f"Lingua rilevata '{src}' non supportata per la traduzione (supportate: inglese, "
                               f"spagnolo, russo, ucraino). La trascrizione \u00e8 salvata in {en_srt.name}.")
        self.log(f"Traduzione {SRC_LANGS[src][0].lower()} \u2192 italiano con Argos (offline)...")
        out = self.translate(subs, src, t_lo, 100)
        it_srt.write_text(srt.compose(out), encoding="utf-8")
        self.log(f"Salvato: {it_srt.name}")
        self.q.put(("done", str(en_srt), str(it_srt)))


# --- interfaccia -----------------------------------------------------------
BG, PANEL, PANEL2 = "#14161c", "#1e222b", "#2a2f3b"
FG, MUTED, ACCENT, OK, WARN, ERR = "#e6e9ef", "#8b93a3", "#4f8cff", "#3ecf8e", "#f5a623", "#ff6b6b"

MODEL_CARDS = [
    ("small", "small\nVeloce · ~1 GB VRAM\ndownload ~0,5 GB"),
    ("medium", "medium\nBilanciato · ~3 GB VRAM\ndownload ~1,5 GB"),
    ("large-v3", "large-v3\nMigliore · ~5 GB VRAM\ndownload ~3 GB"),
]


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.files, self.info = {}, None
        self.model = tk.StringVar(value="medium")
        self.force = tk.StringVar(value="no")
        self.ontop = tk.BooleanVar(value=True)
        self.indet_on = False
        self.t0 = self.stage_t0 = 0.0
        self.stage_label, self.stage_f0 = "", 0.0
        self.last_out = None

        root.title("Traduzione sottotitoli")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = 820, min(790, sh - 110)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
        root.minsize(740, 600)
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        self.style()
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.scan()
        root.after(120, self.poll)

    # stile
    def style(self):
        ttk, root = self.ttk, self.root
        s = ttk.Style(root)
        s.theme_use("clam")
        f = ("Segoe UI", 10)
        s.configure(".", background=BG, foreground=FG, font=f, borderwidth=0)
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 18), foreground=FG)
        s.configure("Sub.TLabel", foreground=MUTED)
        s.configure("Card.TLabel", background=PANEL, foreground=FG)
        s.configure("CardTitle.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 11))
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        s.configure("Ok.TLabel", background=PANEL, foreground=OK)
        s.configure("Warn.TLabel", background=PANEL, foreground=WARN)
        s.configure("Phase.TLabel", background=PANEL, foreground=FG, font=("Segoe UI Semibold", 11))
        s.configure("Pct.TLabel", background=PANEL, foreground=FG, font=("Segoe UI Semibold", 11))
        s.configure("TCheckbutton", background=BG, foreground=MUTED)
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG, arrowcolor=FG,
                    bordercolor=PANEL2, lightcolor=PANEL2, darkcolor=PANEL2, padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL2), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)], selectbackground=[("readonly", PANEL2)],
              selectforeground=[("readonly", FG)])
        root.option_add("*TCombobox*Listbox.background", PANEL2)
        root.option_add("*TCombobox*Listbox.foreground", FG)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        s.configure("Choice.Toolbutton", background=PANEL2, foreground=FG, padding=(14, 9), anchor="center",
                    justify="center", relief="flat", borderwidth=0)
        s.map("Choice.Toolbutton", background=[("selected", ACCENT), ("active", "#353b4a"), ("disabled", PANEL)],
              foreground=[("selected", "white"), ("disabled", MUTED)])
        s.configure("TButton", background=PANEL2, foreground=FG, padding=(16, 8), relief="flat")
        s.map("TButton", background=[("active", "#353b4a"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background=ACCENT, foreground="white", font=("Segoe UI Semibold", 11),
                    padding=(22, 9))
        s.map("Accent.TButton", background=[("active", "#6aa0ff"), ("disabled", "#2c3a57")],
              foreground=[("disabled", "#8b93a3")])
        s.configure("Danger.TButton", background="#7a2e35", foreground="white")
        s.map("Danger.TButton", background=[("active", "#a03a43"), ("disabled", PANEL)],
              foreground=[("disabled", MUTED)])
        s.configure("Horizontal.TProgressbar", troughcolor=PANEL2, background=ACCENT, bordercolor=PANEL2,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=18)

    def card(self, title):
        ttk = self.ttk
        c = ttk.Frame(self.main, style="Card.TFrame", padding=(16, 12))
        c.pack(fill="x", pady=(0, 10))
        ttk.Label(c, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        return c

    def build(self):
        tk, ttk = self.tk, self.ttk
        self.main = ttk.Frame(self.root, padding=(20, 16, 20, 12))
        self.main.pack(fill="both", expand=True)
        head = ttk.Frame(self.main)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Traduzione sottotitoli", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="Whisper (trascrizione) + Argos Translate (traduzione offline)", style="Sub.TLabel").pack(anchor="w")

        # 1 film
        c = self.card("1 · Film")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.file_cb = ttk.Combobox(row, state="readonly")
        self.file_cb.pack(side="left", fill="x", expand=True)
        self.file_cb.bind("<<ComboboxSelected>>", lambda e: self.on_file())
        self.b_refresh = ttk.Button(row, text="↻", width=3, command=self.scan)
        self.b_refresh.pack(side="left", padx=(8, 0))
        self.b_browse = ttk.Button(row, text="Sfoglia…", command=self.browse)
        self.b_browse.pack(side="left", padx=(8, 0))
        self.lbl_info = ttk.Label(c, text="", style="Muted.TLabel", wraplength=740, justify="left")
        self.lbl_info.pack(anchor="w", pady=(8, 0))
        arow = ttk.Frame(c, style="Card.TFrame")
        arow.pack(fill="x", pady=(8, 0))
        ttk.Label(arow, text="Traccia audio:", style="Card.TLabel").pack(side="left")
        self.audio_cb = ttk.Combobox(arow, state="readonly", width=48)
        self.audio_cb.pack(side="left", padx=(8, 0))
        self.audio_cb.bind("<<ComboboxSelected>>", lambda e: self.on_audio())
        ttk.Label(arow, text="Lingua parlata:", style="Card.TLabel").pack(side="left", padx=(16, 0))
        self.lang_cb = ttk.Combobox(arow, state="readonly", width=11, values=LANG_CHOICES)
        self.lang_cb.set("Automatica")
        self.lang_cb.pack(side="left", padx=(8, 0))
        self.lang_cb.bind("<<ComboboxSelected>>", lambda e: self.show_info())

        # 2 modello
        c = self.card("2 · Modello di trascrizione")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.model_btns = []
        for i, (val, text) in enumerate(MODEL_CARDS):
            b = ttk.Radiobutton(row, text=text, value=val, variable=self.model, style="Choice.Toolbutton")
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            row.columnconfigure(i, weight=1, uniform="m")
            self.model_btns.append(b)
        self.lbl_gpu = ttk.Label(c, text="Controllo la scheda video…", style="Muted.TLabel")
        self.lbl_gpu.pack(anchor="w", pady=(8, 0))

        # 3 sottotitoli
        c = self.card("3 · Il film ha già dei sottotitoli incorporati?")
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x")
        self.force_btns = []
        for i, (val, text) in enumerate((("si", "Sì\nli ignoro e trascrivo l'audio (force-whisper)"),
                                         ("no", "No\nuso quelli inglesi se ci sono, altrimenti trascrivo"))):
            b = ttk.Radiobutton(row, text=text, value=val, variable=self.force, style="Choice.Toolbutton")
            b.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            row.columnconfigure(i, weight=1, uniform="f")
            self.force_btns.append(b)

        # 4 avanzamento
        c = self.card("4 · Avanzamento")
        top = ttk.Frame(c, style="Card.TFrame")
        top.pack(fill="x")
        self.lbl_phase = ttk.Label(top, text="In attesa", style="Phase.TLabel")
        self.lbl_phase.pack(side="left")
        self.lbl_pct = ttk.Label(top, text="0%", style="Pct.TLabel")
        self.lbl_pct.pack(side="right")
        self.bar = ttk.Progressbar(c, maximum=100, mode="determinate")
        self.bar.pack(fill="x", pady=(6, 4))
        self.lbl_time = ttk.Label(c, text="", style="Muted.TLabel")
        self.lbl_time.pack(anchor="w")
        lf = ttk.Frame(c, style="Card.TFrame")
        lf.pack(fill="both", expand=True, pady=(8, 0))
        self.txt = tk.Text(lf, height=6, bg=PANEL2, fg=FG, relief="flat", wrap="word", font=("Consolas", 9),
                           state="disabled", padx=8, pady=6, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(lf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_configure("err", foreground=ERR)
        self.txt.tag_configure("ok", foreground=OK)

        # pulsanti
        foot = ttk.Frame(self.main)
        foot.pack(side="bottom", fill="x", pady=(2, 0), before=self.main.winfo_children()[0])
        self.b_start = ttk.Button(foot, text="▶  Avvia", style="Accent.TButton", command=self.start)
        self.b_start.pack(side="left")
        self.b_cancel = ttk.Button(foot, text="■  Annulla", style="Danger.TButton", command=self.cancel)
        self.b_cancel.pack(side="left", padx=(8, 0))
        self.b_cancel.state(["disabled"])
        self.b_open = ttk.Button(foot, text="Apri cartella", command=self.open_folder)
        self.b_open.pack(side="left", padx=(8, 0))
        ttk.Button(foot, text="Chiudi", command=self.on_close).pack(side="right")
        ttk.Checkbutton(foot, text="Sempre in primo piano", variable=self.ontop,
                        command=lambda: self.root.attributes("-topmost", self.ontop.get())).pack(side="right", padx=12)

        self.inputs = [self.file_cb, self.audio_cb, self.lang_cb, self.b_refresh, self.b_browse] + self.model_btns + self.force_btns
        threading.Thread(target=self._gpu, daemon=True).start()

    def _gpu(self):
        self.q.put(("gpu", gpu_name()))

    # file
    def scan(self):
        self.files = {p.name: p for p in sorted(BASE.iterdir()) if p.suffix.lower() in VIDEO_EXT}
        self.set_files()

    def set_files(self):
        names = list(self.files)
        self.file_cb["values"] = names
        if names:
            cur = self.file_cb.get()
            self.file_cb.set(cur if cur in self.files else names[0])
            self.on_file()
        else:
            self.file_cb.set("")
            self.info = None
            self.audio_cb["values"] = []
            self.audio_cb.set("")
            self.lbl_info.configure(text="Nessun video (.mkv, .mp4, ...) trovato nella cartella: copiane uno qui oppure usa Sfoglia…",
                                    style="Warn.TLabel")
            self.b_start.state(["disabled"])

    def browse(self):
        from tkinter import filedialog
        self.root.attributes("-topmost", False)
        p = filedialog.askopenfilename(title="Scegli un film", filetypes=[("Video", "*.mkv *.mp4 *.m4v *.avi *.mov *.webm"), ("Tutti", "*.*")])
        self.root.attributes("-topmost", self.ontop.get())
        if p:
            path = Path(p)
            self.files[path.name] = path
            self.set_files()
            self.file_cb.set(path.name)
            self.on_file()

    def on_file(self):
        path = self.files.get(self.file_cb.get())
        if not path:
            return
        try:
            info = probe(path)
        except Exception as e:  # noqa: BLE001
            self.info = None
            self.lbl_info.configure(text=f"Impossibile leggere il file: {e}", style="Warn.TLabel")
            self.b_start.state(["disabled"])
            return
        self.info = info
        audio = info["audio"]
        labels = [f"{a['pos'] + 1}: {LANGS.get(a['lang'], a['lang'])} · {a['codec']} {a['ch']}ch"
                  + (f" · {a['title']}" if a["title"] else "") for a in audio]
        self.audio_cb["values"] = labels
        pref = [a for a in audio if iso2(a["lang"])]
        if audio:
            self.audio_cb.current(pref[0]["pos"] if pref else 0)
        self.on_audio(show=False)
        self.show_info()
        self.force.set("no")
        self.b_start.state(["!disabled"] if audio else ["disabled"])

    def on_audio(self, show=True):
        """Imposta la lingua parlata in base alla traccia audio scelta."""
        if self.info and self.info["audio"]:
            k = iso2(self.info["audio"][max(0, self.audio_cb.current())]["lang"])
            self.lang_cb.set(SRC_LANGS[k][0] if k else "Automatica")
        if show:
            self.show_info()

    def cur_lang(self):
        return LANG_BY_NAME.get(self.lang_cb.get(), "auto")

    def show_info(self):
        info = self.info
        if not info:
            return
        lang = self.cur_lang()
        parts = [f"Durata {fmt_time(info['duration'])}"]
        k = iso2(info["audio"][max(0, self.audio_cb.current())]["lang"]) if info["audio"] else None
        if lang != "auto":
            parts.append(f"\u2714 parlato {SRC_LANGS[lang][0].lower()} \u2192 traduzione in italiano")
            ok = True
        elif k:
            parts.append(f"\u2714 audio {SRC_LANGS[k][0].lower()} rilevato")
            ok = True
        else:
            parts.append("\u26a0 lingua dell'audio non indicata: verr\u00e0 riconosciuta da Whisper (supportate: inglese, spagnolo, russo, ucraino)")
            ok = False
        want = lang if lang != "auto" else "en"
        sub = best_sub(info["subs"], want)
        if sub:
            parts.append(f"\u2714 sottotitoli {SRC_LANGS[want][0].lower()} incorporati ({sub['codec']})")
        else:
            n = len(info["subs"])
            parts.append(f"nessun sottotitolo {SRC_LANGS[want][0].lower()} testuale incorporato" + (f" ({n} altri)" if n else ""))
        self.lbl_info.configure(text="  \u00b7  ".join(parts), style="Ok.TLabel" if ok else "Warn.TLabel")

    # esecuzione
    def set_running(self, running):
        for w in self.inputs:
            w.state(["disabled"] if running else ["!disabled"])
        self.b_start.state(["disabled"] if running else ["!disabled"])
        self.b_cancel.state(["!disabled"] if running else ["disabled"])

    def start(self):
        path = self.files.get(self.file_cb.get())
        if not path or not self.info or not self.info["audio"]:
            return
        self.clear_log()
        self.set_running(True)
        self.t0 = time.time()
        self.stage_label = ""
        self.set_prog(0, 0, "Avvio…")
        self.log(f"File: {path.name}  ·  modello: {self.model.get()}  ·  lingua: {self.lang_cb.get()}  ·  force-whisper: {'sì' if self.force.get() == 'si' else 'no'}")
        self.worker = Worker(self.q, path, self.info, max(0, self.audio_cb.current()), self.model.get(),
                             self.force.get() == "si", self.cur_lang())
        self.worker.start()

    def cancel(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop.set()
            self.lbl_phase.configure(text="Annullamento…")
            self.b_cancel.state(["disabled"])

    def open_folder(self):
        target = self.last_out or self.files.get(self.file_cb.get())
        if target:
            subprocess.Popen(["explorer", "/select,", str(target)], creationflags=NOWIN)
        else:
            os.startfile(str(BASE))

    def on_close(self):
        if self.worker and self.worker.is_alive():
            self.root.attributes("-topmost", False)
            from tkinter import messagebox
            if not messagebox.askyesno("Lavoro in corso", "Il lavoro è in corso. Vuoi annullarlo e uscire?"):
                self.root.attributes("-topmost", self.ontop.get())
                return
            self.worker.stop.set()
        self.root.destroy()

    # log / progresso
    def log(self, text, tag=None):
        self.txt.configure(state="normal")
        self.txt.insert("end", time.strftime("%H:%M:%S  ") + text + "\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def set_indet(self, label):
        if not self.indet_on:
            self.bar.configure(mode="indeterminate")
            self.bar.start(12)
            self.indet_on = True
        self.lbl_phase.configure(text=label)
        self.lbl_pct.configure(text="")
        self.stage_label = ""

    def set_prog(self, overall, frac, label):
        if self.indet_on:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.indet_on = False
        self.bar["value"] = overall
        self.lbl_pct.configure(text=f"{overall:.0f}%")
        self.lbl_phase.configure(text=f"{label}  {frac * 100:.0f}%" if frac else label)
        base = label.split(" ")[0]
        if base != self.stage_label:
            self.stage_label, self.stage_t0, self.stage_f0 = base, time.time(), frac
        self.stage_frac = frac

    def tick(self):
        if not (self.worker and self.worker.is_alive()):
            return
        el = time.time() - self.t0
        txt = f"Trascorso {fmt_time(el)}"
        f0, f = self.stage_f0, getattr(self, "stage_frac", 0)
        if self.stage_label and f - f0 > 0.02:
            eta = (time.time() - self.stage_t0) * (1 - f) / (f - f0)
            txt += f"   ·   fine fase ≈ {fmt_time(eta)}"
        self.lbl_time.configure(text=txt)

    def poll(self):
        try:
            while True:
                self.handle(self.q.get_nowait())
        except queue.Empty:
            pass
        self.tick()
        self.root.after(150, self.poll)

    def handle(self, m):
        k = m[0]
        if k == "log":
            self.log(m[1])
        elif k == "indet":
            self.set_indet(m[1])
        elif k == "prog":
            self.set_prog(m[1], m[2], m[3])
        elif k == "gpu":
            if m[1]:
                self.lbl_gpu.configure(text=f"✔ GPU NVIDIA rilevata: {m[1]} — verrà usata automaticamente",
                                       style="Ok.TLabel")
            else:
                self.lbl_gpu.configure(text="⚠ Nessuna GPU NVIDIA rilevata: userò la CPU (più lento, meglio 'small')",
                                       style="Warn.TLabel")
        elif k == "done":
            self.finish(f"Completato in {fmt_time(time.time() - self.t0)}")
            self.set_prog(100, 1, "Completato")
            self.lbl_phase.configure(text="Completato ✔")
            self.last_out = m[2]
            self.log(f"Fatto! Sottotitoli italiani: {Path(m[2]).name}", "ok")
            self.log("Caricalo nel tuo lettore video come sottotitolo (o rinominalo come il film).", "ok")
        elif k == "error":
            self.finish("Errore")
            self.lbl_phase.configure(text="Errore")
            self.log(m[1], "err")
        elif k == "cancelled":
            self.finish("Annullato")
            self.lbl_phase.configure(text="Annullato")
            self.log("Operazione annullata.", "err")

    def finish(self, text):
        if self.indet_on:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.indet_on = False
        self.lbl_time.configure(text=text)
        self.set_running(False)


def main_gui():
    import tkinter as tk
    root = tk.Tk()
    try:
        App(root)
    except Exception:
        traceback.print_exc()
        from tkinter import messagebox
        messagebox.showerror("Errore", traceback.format_exc())
        raise
    root.mainloop()


def main_cli(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mkv = Path(argv[0])
    model = argv[argv.index("--model") + 1] if "--model" in argv else "small"
    info = probe(mkv)
    q = queue.Queue()
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else "auto"
    w = Worker(q, mkv, info, 0, model, "--force" in argv, lang)
    t = threading.Thread(target=w.run)
    t.start()
    while t.is_alive() or not q.empty():
        try:
            m = q.get(timeout=0.5)
        except queue.Empty:
            continue
        if m[0] == "prog":
            print(f"\r[{m[1]:5.1f}%] {m[3]}          ", end="", flush=True)
        else:
            print("\n" + " ".join(str(x) for x in m))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--cli":
        main_cli(sys.argv[2:])
    else:
        main_gui()
