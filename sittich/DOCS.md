# Sittich

Lokale deutsche Spracherkennung für Assist mit dem Modell parakeet-primeline
(nur CPU, offline).

> **Hinweis:** Diese App wurde vollständig von einer KI (Claude, Anthropic)
> erstellt und nicht von einem menschlichen Entwickler geprüft. Nutzung auf
> eigenes Risiko.

## Erster Start

Das Modell ist im Image enthalten, die App lädt nichts aus dem Internet. Im
Log erscheint nach wenigen Sekunden `Ready on tcp://0.0.0.0:10300`. Home Assistant meldet den
Dienst dann als neu entdeckte **Wyoming Protocol**-Integration. Diese
hinzufügen und im Sprachassistenten unter *Sprache-zu-Text* **sittich**
auswählen.

## Optionen

- **threads**: CPU-Threads für die Erkennung. 4 ist meist am schnellsten,
  mehr Threads bringen in der Regel nichts.
- **hotwords**: Namen der für Assist freigegebenen Entitäten, ihre Aliase
  sowie Räume und Etagen aus Home Assistant werden bevorzugt erkannt (alle
  5 Minuten aktualisiert). Kostet etwa 100 ms pro Befehl.
- **hotwords_score**: Stärke der Bevorzugung. 2.0 hat sich bewährt; zu hohe
  Werte verfälschen andere Wörter.
- **debug**: ausführliche Logs, inklusive der geladenen Namen.

Jede Erkennung wird mit Dauer und Text geloggt, z. B.
`2.0 s audio -> 360 ms: Starte einen Timer für zehn Minuten.`

## Ressourcen

Etwa 0,7–1 GB RAM. Das Image ist etwa 1 GB groß; bei Updates sollte das
Modell (640 MB) nicht erneut heruntergeladen werden.

## Lizenz

Modell: CC-BY-4.0 (primeLine, NVIDIA). Runtime: sherpa-onnx (Apache-2.0).
