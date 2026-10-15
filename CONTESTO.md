# Contesto del progetto: Traduzione sottotitoli

Note tecniche per chi riprende il lavoro. L'uso da parte dell'utente è nel [README](README.md).

## Obiettivo
Dato un video (`.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.webm`) produrre `film.it.srt`, con tempi sincronizzati, in
modo **portatile, gratuito e offline** (dopo il primo avvio). Lingue sorgente: `en`, `es`, `ru`, `uk`.

## Flusso (`app.py`, classe `Worker.pipeline`)
```
probe (ffprobe) ──► sottotitolo testuale nella lingua parlata?  (se force=No)
        │ sì: ffmpeg -map 0:<stream> film.<lang>.srt
        │ no: ffmpeg estrae audio mono 16 kHz → faster-whisper (CUDA float16, fallback CPU int8)
        ▼
film.<lang>.srt  ──► Argos Translate (<lang> → it) ──► film.it.srt
```
- `probe()` legge audio/sottotitoli con ffprobe; `best_sub()` sceglie il sottotitolo testuale
  (codec in `TEXT_CODECS`: subrip, ass, webvtt, mov_text...). I sottotitoli a immagine (PGS) non sono usati.
- Con lingua "Automatica" cerca sottotitoli inglesi; se non ci sono, Whisper rileva la lingua (`tinfo.language`).
- Lingua non in `SRC_LANGS` → errore chiaro dopo aver salvato la trascrizione. Lingua `it` → nessuna traduzione.
- `_prepare()` / `_assemble()` ripuliscono i tag (`<i>`, `{\an8}`), traducono i dialoghi riga per riga se iniziano con
  trattino, rimandano a capo a 44 caratteri e riapplicano il corsivo. `_fix_accents()` corregge `saro'` → `sarò`.

## Struttura
| File | Ruolo |
|---|---|
| `Avvia.bat` | se manca `runtime\.ready` lancia `setup.ps1`, poi apre `runtime\python\pythonw.exe app.py` |
| `setup.ps1` | scarica Python 3.11.9 (MSI estratti con `msiexec /a`, include Tkinter), ffmpeg, `pip install faster-whisper srt argostranslate nvidia-cublas-cu12 nvidia-cudnn-cu12` |
| `app.py` | GUI tkinter/ttk (tema scuro, sempre in primo piano), `Worker` (thread) e CLI (`--cli`) |
| `mkv2sub_it.py` | wrapper che chiama `app.py --cli` |
| `runtime\` | creata dal setup (~9 GB): `python\`, `ffmpeg\`, `models\` (Whisper, `HF_HOME`), `argos\` (`ARGOS_PACKAGES_DIR`). **Non va nel repository** |
| `prova.mkv` | video di test (voce inglese sintetica, nessun sottotitolo) |

## Scelte e motivi
- **Python da MSI, non "embeddable"/NuGet**: servono Tkinter e Tcl/Tk; gli altri pacchetti non li includono.
- **Librerie CUDA via pip** (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`): nessun CUDA Toolkit di sistema. `_setup_paths()`
  aggiunge le cartelle `nvidia\*\bin` a `PATH`/`add_dll_directory`. Testato su RTX 5060 Ti (Blackwell) con
  ctranslate2 4.8.3.
- **Solo Argos**: Google Translate (via `deep-translator`) dava `429` su questa rete e DeepL richiede una chiave;
  sono stati rimossi. Argos è offline, senza limiti, qualità inferiore ma sufficiente.
- **Percorsi Argos** (`argos_get`): russo e ucraino → inglese → italiano; **spagnolo → portoghese → inglese → italiano**
  perché il modello `es→en` v1.9 è difettoso (ripete "mainstre..." all'infinito, anche riscaricato).
- **GUI non bloccante**: il lavoro gira in `Worker` (thread) e comunica con la GUI tramite `queue` (`poll()` ogni 150 ms).
  Annulla = `threading.Event` controllato nei cicli.
- **`pythonw.exe`**: senza console; gli errori vanno in `app.log`.

## Come provare
```bash
runtime\python\python.exe app.py --cli prova.mkv --model small --lang en
```
Deve creare `prova.en.srt` e `prova.it.srt`. Per russo/ucraino/spagnolo serve un video con quell'audio
(sul PC di sviluppo c'erano solo le voci Windows inglese, italiana e russa).

## Limiti noti
- Hardsub non estraibili; audio in lingue non supportate → solo trascrizione.
- Traduzione riga per riga senza contesto: possibili errori di genere/sfumature.
- Una sola lingua parlata per file; nessuna modalità batch su più file.

## Sviluppi possibili
Altre lingue Argos (fr, de, pt...), elaborazione batch di una cartella, selezione manuale di sottotitoli a immagine
con OCR, traduzione con contesto (frasi unite) o con un modello più grande.
