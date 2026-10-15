# Traduzione sottotitoli

Programma per Windows che **crea i sottotitoli in italiano** a partire da un file video (`.mkv`, `.mp4`, ...).
Funziona **in locale e gratis**: non servono chiavi API né account, e dopo il primo avvio funziona anche offline.

1. Se il video contiene già un sottotitolo testuale nella lingua parlata, lo estrae.
2. Altrimenti ascolta l'audio e lo trascrive con **Whisper** (usa la scheda NVIDIA se c'è).
3. Traduce il testo in italiano con **Argos Translate** (offline).
4. Salva due file accanto al video: il sottotitolo originale e quello italiano.

Lingue del parlato supportate: **inglese, spagnolo, russo, ucraino, francese, polacco** → italiano.

| Lingua parlata | Percorso di traduzione | Modelli da scaricare (una volta) |
|---|---|---|
| Inglese | inglese → italiano | ~100 MB |
| Russo, ucraino, francese, polacco | lingua → inglese → italiano | ~100 MB + 100 MB |
| Spagnolo | spagnolo → portoghese → inglese → italiano | ~300 MB in più |

## Requisiti

- Windows 10 o 11 (64 bit)
- Circa **9 GB** di spazio libero (Python, ffmpeg, librerie CUDA e modelli)
- Internet **solo la prima volta** (download di programmi e modelli)
- Scheda **NVIDIA** consigliata (molto più veloce). Senza, funziona su CPU, più lentamente: conviene il modello `small`

## Installazione

Non c'è nulla da installare. Scarica o clona questa cartella e fai doppio click su **`Avvia.bat`**.

Al primo avvio scarica da solo, dentro la cartella `runtime\`, Python (con Tkinter), ffmpeg e le librerie
necessarie. Non tocca il resto del sistema: puoi spostare o copiare l'intera cartella su un altro disco o PC.
I modelli di Whisper e di traduzione vengono scaricati la prima volta che li usi.

## Come si usa

1. Copia il video nella cartella del programma (oppure usa il pulsante **Sfoglia…**).
2. Fai doppio click su **`Avvia.bat`**: si apre la finestra.
3. **Film**: scegli il video. Il programma legge le tracce audio e i sottotitoli incorporati.
4. **Lingua parlata**: di solito si imposta da sola. Con *Automatica* la lingua viene riconosciuta da Whisper.
5. **Modello di trascrizione**:

   | Modello | Velocità | VRAM | Download |
   |---|---|---|---|
   | `small` | veloce | ~1 GB | ~0,5 GB |
   | `medium` (predefinito) | bilanciato | ~3 GB | ~1,5 GB |
   | `large-v3` | più preciso, più lento | ~5 GB | ~3 GB |

6. **Il film ha già dei sottotitoli incorporati?**
   - **Sì** → li ignora e trascrive l'audio (utile se quelli presenti sono scadenti).
   - **No** → usa i sottotitoli testuali della lingua parlata, se ci sono; altrimenti trascrive l'audio.
7. Premi **Avvia**. La finestra mostra fase, percentuale, tempo trascorso e log. **Annulla** ferma il lavoro.
8. Alla fine trovi accanto al video:
   - `film.<lingua>.srt` — sottotitolo originale (es. `film.en.srt`, `film.ru.srt`)
   - `film.it.srt` — **sottotitolo italiano**

### Usare il file `.srt`

Carica `film.it.srt` nel tuo lettore video come sottotitolo esterno (trascinandolo sulla finestra del lettore
mentre il video è in riproduzione) oppure rinominalo con lo stesso nome del video e tienilo nella stessa cartella.

## Da riga di comando

```bash
runtime\python\python.exe mkv2sub_it.py "C:\Film\film.mkv" --model medium --lang auto
```

| Opzione | Significato |
|---|---|
| `--model small\|medium\|large-v3` | modello Whisper (predefinito `small` da CLI) |
| `--lang auto\|en\|es\|ru\|uk\|fr\|pl` | lingua del parlato |
| `--force` | ignora i sottotitoli incorporati e trascrive l'audio |

## Limiti e problemi comuni

- **Sottotitoli "bruciati" nelle immagini** (hardsub) non si possono estrarre: il programma trascrive l'audio, ma
  quelli originali restano visibili nel video.
- La traduzione è automatica: è adatta a seguire il film, ma qualche frase può risultare letterale. Russo, ucraino, francese e polacco
  passano dall'inglese, lo spagnolo dal portoghese.
- Se la lingua rilevata non è tra quelle supportate, viene salvata solo la trascrizione originale.
- La GPU non parte: il programma riprova da solo sulla CPU. Aggiorna il driver NVIDIA se succede sempre.
- Qualcosa non funziona: guarda il file `app.log` nella cartella del programma.
- Primo avvio fallito: controlla la connessione, poi elimina `runtime\` e rilancia `Avvia.bat`.

## Contenuto della cartella

| File | Scopo |
|---|---|
| `Avvia.bat` | avvio con doppio click; al primo uso lancia `setup.ps1` |
| `setup.ps1` | scarica Python, ffmpeg e le librerie in `runtime\` |
| `app.py` | finestra grafica e motore di elaborazione |
| `mkv2sub_it.py` | scorciatoia da riga di comando |
| `prova.mkv` | breve video di prova con voce inglese |
| `CONTESTO.md` | note tecniche per chi sviluppa |

## Componenti e licenze

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (modelli Whisper di OpenAI, MIT),
[Argos Translate](https://github.com/argosopentech/argos-translate) (MIT),
[FFmpeg](https://ffmpeg.org) (build essentials di gyan.dev, GPL), Python (PSF).
