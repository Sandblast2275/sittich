# Changelog

## 0.1.0

Erste veröffentlichte Version.

- Wyoming-Server für deutsche Spracherkennung mit parakeet-primeline
  (int8, sherpa-onnx), nur CPU, offline
- Hotwords: Namen der für Assist freigegebenen Entitäten, ihre Aliase sowie
  Räume und Etagen werden aus Home Assistant gelesen (alle 5 Minuten) und
  bevorzugt erkannt
- Fertiges Image von GitHub (ghcr.io) mit eingebautem Modell; Modell und alle
  Python-Pakete werden beim Bau gegen SHA-256-Prüfsummen geprüft
- Automatische Erkennung in Home Assistant (App) bzw. per Zeroconf (Docker)
- Schutz vor überlangem oder fehlerhaftem Audio; Zugangs-Token erscheint nie
  im Log
- Robust gegenüber Home Assistant: Zeitlimit und schneller zweiter Versuch
  beim Laden der Namen, funktioniert auch mit älteren Versionen ohne Etagen
- Watchdog: der Supervisor startet die App neu, wenn sie nicht mehr antwortet
- Beschreibungen der Optionen auf Deutsch und Englisch
