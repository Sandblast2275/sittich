<p align="center">
  <img src="sittich-logo.svg" width="160" alt="Sittich-Logo">
</p>

# Sittich

**Lokale deutsche Spracherkennung für Home Assistant Assist – ohne Cloud, ohne Grafikkarte.**

*Local German speech-to-text for Home Assistant Assist, CPU only, fully offline.*

Sittich ist eine Home-Assistant-App (früher „Add-on“), die gesprochene Befehle
in Text umwandelt. Sie verwendet **parakeet-primeline**, eine deutsche
Feinabstimmung von NVIDIAs Spracherkennungsmodell `parakeet-tdt-0.6b-v3`, und
läuft über [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) auf der CPU.
Home Assistant spricht mit Sittich über das
[Wyoming-Protokoll](https://github.com/OHF-Voice/wyoming), wie mit den
offiziellen Sprachdiensten.

*Parakeet* ist englisch für Sittich.

> [!IMPORTANT]
> **Dieses Projekt wurde vollständig von einer KI erstellt.**
> Code, Tests, Build-Konfiguration und Dokumentation stammen zu 100 % von
> Claude (Anthropic). Das Projekt wurde automatisiert getestet, 
> aber von keinem menschlichen Entwickler geprüft.
> Bitte prüfe den Code selbst, bevor du ihm vertraust. Nutzung auf eigenes
> Risiko.

## Funktionen

- **Deutsch-optimiert:** Das Modell ist speziell auf deutsche Sprache
  abgestimmt. Zahlen kommen als Ziffern heraus („auf 21 Grad“, „30%“), was
  Home Assistant direkt versteht.
- **Offline:** Das Modell ist im Image enthalten. Die laufende App lädt nichts
  aus dem Internet und sendet nichts hinaus.
- **Nur CPU:** Keine Grafikkarte nötig.
- **Kennt die Namen deiner Geräte:** Sittich liest die Namen der für Assist
  freigegebenen Geräte, ihre Aliase sowie Räume und Etagen aus Home Assistant
  und erkennt sie bevorzugt. Dafür ist nichts zu pflegen (siehe
  [Hotwords](#hotwords)).
- **Einrichtung ohne Konfiguration:** Home Assistant findet die App
  automatisch.

## Leistung

Gemessen auf einer älteren Intel-Laptop-CPU (4 Kerne, 15 W) mit 4 Threads:

| Gesprochen | Erkannt | Rechenzeit |
|---|---|---|
| Schalte das Licht im Wohnzimmer ein. | Schalte das Licht im Wohnzimmer ein. | 445 ms |
| Stelle die Heizung im Badezimmer auf einundzwanzig Grad. | Stelle die Heizung im Badezimmer auf 21 Grad. | 494 ms |
| Dimme die Stehlampe auf dreißig Prozent. | Dimme die Stehlampe auf 30%. | 377 ms |
| Starte einen Timer für zehn Minuten. | Starte einen Timer für zehn Minuten. | 359 ms |

Ein Befehl von 2–3 Sekunden ist damit in etwa 0,3–0,6 Sekunden erkannt. Auch
mit echten Aufnahmen aus unterschiedlicher Entfernung funktionierte die
Erkennung zuverlässig. Seltene Fremdwörter wie „Jalousien“ werden manchmal
falsch geschrieben.

**Bekannte Grenzen**

- Nur Deutsch. Kurze englische Befehle werden zwar oft erkannt, Sittich meldet
  sich bei Home Assistant aber nur als deutscher Dienst.
- Eine Aufnahme wird nach 30 Sekunden abgeschnitten. Für Sprachbefehle reicht
  das, für lange Diktate nicht.

## Voraussetzungen

- Home Assistant OS oder Supervised (für die App), oder ein Linux-Server mit
  Docker (siehe [Docker](#betrieb-mit-docker))
- x86-64-CPU (amd64) mit AVX2
- 4 freie CPU-Kerne, etwa 1,5 GB freier Arbeitsspeicher und 1 GB
  Speicherplatz

> [!TIP]
> Läuft Home Assistant in einer virtuellen Maschine (z. B. Proxmox), stelle
> den CPU-Typ auf `host`. Sonst sieht die VM keine AVX2-Befehle, und die
> Erkennung wird deutlich langsamer.

## Installation

1. In Home Assistant *Einstellungen → Add-ons/Apps → Store* öffnen, oben rechts
   **⋮ → Repositories** wählen und die Adresse dieses GitHub-Repositorys
   eintragen.
2. **Sittich** in der Liste auswählen, **Installieren** und **Starten**.
   Empfohlen: „Beim Booten starten“ und „Watchdog“ einschalten.
3. Im Tab **Protokoll** sollten nach wenigen Sekunden diese Zeilen stehen:
   ```
   Loaded N hotwords from Home Assistant
   Ready on tcp://0.0.0.0:10300
   ```
4. Unter *Einstellungen → Geräte & Dienste* erscheint eine neu entdeckte
   **Wyoming Protocol**-Integration. Auf **Hinzufügen** tippen.
5. Unter *Einstellungen → Sprachassistenten* den Assistenten öffnen und bei
   **Sprache-zu-Text** **Sittich** auswählen, Sprache Deutsch.

Jede Erkennung erscheint im Protokoll der App, z. B.
`2.2 s audio -> 480 ms: Schalte das Licht im Wohnzimmer ein.`

## Optionen

| Option | Standard | Beschreibung |
|---|---|---|
| `threads` | `4` | CPU-Threads für die Erkennung. Mehr als 4 waren in Tests nicht schneller. |
| `hotwords` | an | Namen aus Home Assistant bevorzugt erkennen. Kostet etwa 100 ms pro Befehl. |
| `hotwords_score` | `2.0` | Stärke der Bevorzugung. Zu hohe Werte (z. B. 3) verfälschen andere Wörter. |
| `debug` | aus | Ausführliche Protokolle, inklusive der geladenen Namen. |

## Hotwords

Spracherkennungsmodelle kennen deine Gerätenamen nicht und schreiben
ungewöhnliche Namen oft falsch. Sittich liest deshalb alle 5 Minuten aus Home
Assistant:

- die Namen aller **für Assist freigegebenen** Entitäten und ihre Aliase
- die Namen der Räume und Etagen mit ihren Aliasen

Diese Wörter werden bei der Erkennung bevorzugt (*contextual biasing*). Benennst
du in Home Assistant etwas um, kennt Sittich den neuen Namen nach spätestens
5 Minuten. An Home Assistant selbst ändert Sittich nichts. Schlägt die
Abfrage fehl, erkennt Sittich ohne Hotwords weiter.

## Datenschutz und Sicherheit

**Was das Internet betrifft**

| Wann | Was | Woher |
|---|---|---|
| Installation und Updates | fertiges Image (etwa 1 GB, das Modell nur beim ersten Mal) | GitHub Container Registry |
| Im Betrieb | **nichts** | – |

Die App enthält keine Telemetrie. Audio bleibt nur für die Dauer der Erkennung
im Arbeitsspeicher und wird nie gespeichert. Der erkannte Text steht im
Protokoll der App.

**Rechte der App**

- `homeassistant_api`: nötig, um die Namen für die Hotwords zu lesen. Dieses
  Recht erlaubt technisch vollen Zugriff auf Home Assistant. Feiner lässt es
  sich in Home Assistant nicht einschränken. Sittich nutzt es nur lesend für
  fünf Abfragen (Zustände, Entitäten, Räume, Etagen, Assist-Freigaben), siehe
  [hotwords.py](sittich/wyoming_sittich/hotwords.py).
- `hassio_api`: nur um sich bei Home Assistant als Sprachdienst anzumelden.
- Ein **Watchdog** prüft den Port. Antwortet die App nicht mehr, startet der
  Supervisor sie neu.
- **Keine** Rechte für Host-Netzwerk, Hardware, Docker oder deine
  Konfigurationsdateien. Port 10300 ist nur innerhalb von Home Assistant
  erreichbar.

**Lieferkette**

- Das Modell wird beim Bauen auf eine feste, unveränderliche Version
  festgelegt geladen und jede Datei gegen eine im Code eingetragene
  SHA-256-Prüfsumme geprüft ([model.py](sittich/wyoming_sittich/model.py)).
- Alle Python-Pakete und ihre Abhängigkeiten haben feste Versionen und
  Prüfsummen ([requirements.txt](sittich/requirements.txt)). Passt eine Datei
  nicht, bricht der Bau ab.
- Die GitHub-Actions-Bausteine sind über Commit-Hashes eingebunden.
  Veröffentlichte Versionen werden nie überschrieben.

## Betrieb mit Docker

Ohne Home Assistant OS lässt sich Sittich auch als Container auf einem
Linux-Server betreiben:

```bash
cp .env.example .env    # Home-Assistant-Adresse (IP) und Token eintragen
docker compose up -d --build
docker compose logs -f
```

Für die Hotwords braucht der Container ein langlebiges Zugangs-Token
(*Profil → Sicherheit → Langlebige Zugangs-Token*). Trage die IP-Adresse von
Home Assistant ein, nicht `homeassistant.local`, da der Container keine
mDNS-Namen auflöst. Ohne `.env` läuft Sittich ohne Hotwords.

Durch `network_mode: host` und `--zeroconf` findet Home Assistant den Dienst
automatisch. Falls nicht: *Integration hinzufügen → Wyoming Protocol*, Host =
IP des Servers, Port `10300`.

| Parameter | Standard | Beschreibung |
|---|---|---|
| `--uri` | `tcp://0.0.0.0:10300` | Adresse, auf der der Server lauscht |
| `--threads` | `4` | wie die Option `threads` |
| `--no-hotwords` | – | Hotwords abschalten |
| `--hotwords-score` | `2.0` | wie die Option `hotwords_score` |
| `--ha-url` / `HA_URL` | – | z. B. `http://192.168.1.10:8123` |
| `HA_TOKEN` | – | Zugangs-Token, nur als Umgebungsvariable |
| `--zeroconf [NAME]` | aus | per mDNS ankündigen |
| `--model-dir` | `/app/model` | im Image enthalten; fehlt es, wird es geladen und geprüft |
| `--debug` | aus | ausführliche Protokolle |

## Entwicklung

```
sittich/                  App-Verzeichnis (config.yaml, Dockerfile, Code)
  wyoming_sittich/
    __main__.py           Start, Optionen, Anmeldung bei Home Assistant
    handler.py            Wyoming-Protokoll: Audio empfangen, Text senden
    recognizer.py         Spracherkennung mit sherpa-onnx
    hotwords.py           Namen aus Home Assistant lesen
    model.py              Modell-Download mit Prüfsummen
tests/                    pytest
script/transcribe.py      WAV-Datei an einen laufenden Server schicken
.github/workflows/        Tests, Bau und Veröffentlichung des Images
```

**Tests**

```bash
pip install --require-hashes -r sittich/requirements.txt
pip install pytest
pytest tests
```

Tests mit dem echten Modell laufen, wenn diese Umgebungsvariablen gesetzt sind:

| Variable | Bedeutung |
|---|---|
| `SITTICH_MODEL_DIR` | Ordner mit dem Modell (`python3 sittich/wyoming_sittich/model.py <ordner>` lädt es) |
| `SITTICH_TEST_WAV`, `SITTICH_TEST_TEXT` | Aufnahme und ein Wort, das erkannt werden muss |
| `SITTICH_HOTWORD_WAV`, `SITTICH_HOTWORD` | Aufnahme eines Namens, den erst die Hotwords richtig erkennen |

Eine Aufnahme an einen laufenden Server schicken:

```bash
python3 script/transcribe.py --uri tcp://<server>:10300 aufnahme.wav
```

**Neue Version veröffentlichen**

1. `version` in [sittich/config.yaml](sittich/config.yaml) erhöhen und
   [CHANGELOG.md](sittich/CHANGELOG.md) ergänzen.
2. Auf `main` hochladen. GitHub Actions testet, baut, führt einen Rauchtest aus
   und veröffentlicht `ghcr.io/<owner>/amd64-sittich:<version>`.
3. Erst wenn der Lauf grün ist, zeigt Home Assistant ein funktionierendes
   Update an.

Ohne höhere Versionsnummer baut GitHub nichts.

**Python-Pakete aktualisieren** (mit [uv](https://docs.astral.sh/uv/)):

```bash
uv pip compile sittich/requirements.in -o sittich/requirements.txt --upgrade --generate-hashes --python-version 3.13 --python-platform x86_64-manylinux_2_28 --no-header
```

Danach die Kopfzeile in `requirements.txt` wieder einfügen, die Tests laufen
lassen und eine neue Version veröffentlichen.

**Automatische Hinweise:** [Dependabot](.github/dependabot.yml) schlägt
wöchentlich neue Versionen der GitHub-Actions und des Python-Basis-Images
(Debian 13 „trixie“) als Pull Request vor.

**Eigener Fork:** In [sittich/config.yaml](sittich/config.yaml) bei `image:`
den eigenen GitHub-Namen in Kleinbuchstaben eintragen. Nach dem ersten Bau das
Paket unter *Profil → Packages → amd64-sittich → Package settings* auf
**Public** stellen, sonst kann Home Assistant es nicht laden.

## Lizenz und Danksagung

Der Code steht unter der [MIT-Lizenz](LICENSE).

Das Modell ist nicht Teil dieses Repositorys. Es wird beim Bau des Images
geladen und steht unter [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/):

- [primeLine](https://huggingface.co/primeline/parakeet-primeline): deutsche Feinabstimmung
- [NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3): Basismodell parakeet-tdt-0.6b-v3
- [flozen1981/parakeet-primeline-onnx](https://huggingface.co/flozen1981/parakeet-primeline-onnx): ONNX-Export

Weitere Grundlagen:

- [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0): Laufzeit für das Modell
- [Wyoming](https://github.com/OHF-Voice/wyoming) (MIT): Protokoll zu Home Assistant
- [dictate](https://github.com/winidi/dictate) (MIT): Vorbild für die Wahl des
  Modells und für Teile der Dekodierlogik (Verstärkung leiser Aufnahmen,
  Aufteilen langer Audios)

Sittich ist ein unabhängiges Projekt und steht in keiner Verbindung zu Home
Assistant, Nabu Casa, NVIDIA oder primeLine.
