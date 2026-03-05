# Beitragen zu `check_mail`

Diese Regeln definieren den Standard-Workflow für die Zusammenarbeit über GitHub.

## Branch-Strategie

- Niemals direkt auf `main` arbeiten.
- Pro Aufgabe einen eigenen Branch anlegen.
- Benennung:
  - Feature: `feat/<kurze-beschreibung>`
  - Bugfix: `fix/<kurze-beschreibung>`
  - Doku: `docs/<kurze-beschreibung>`
  - Chore: `chore/<kurze-beschreibung>`

Beispiele:
- `feat/send-command-timeout`
- `fix/imap-search-criteria`
- `docs/update-icinga-readme`

## Commits

- Kleine, logisch getrennte Commits.
- Commit-Nachrichten immer auf Deutsch.
- Empfehlung für Format:
  - `feat: smtp-timeout im send-command ergänzen`
  - `fix: imap-fehler bei leerem body abfangen`
  - `docs: anleitung für icinga-submit präzisieren`

## Pull Requests

- PRs möglichst klein halten.
- PR früh als Draft öffnen, sobald Feedback sinnvoll ist.
- Vor dem PR lokal prüfen:
  - `source .venv/bin/activate`
  - `pytest`
- Im PR klar beschreiben:
  - Was wurde geändert?
  - Warum wurde es geändert?
  - Welche Risiken/Nebenwirkungen gibt es?
  - Wie wurde getestet?

## Review-Regeln

- Kein Merge ohne Review (mindestens eine Freigabe).
- Fokus im Review:
  - Verhalten/Regressionen
  - Fehlerszenarien
  - Lesbarkeit und Wartbarkeit
  - Testabdeckung

## Merge-Regeln

- Nur mergen, wenn CI grün ist.
- Bevorzugt **Squash Merge**, damit `main` übersichtlich bleibt.
- PR-Titel sollte den Squash-Commit sinnvoll beschreiben.

## `main` aktuell halten

- Branch regelmäßig mit `main` synchronisieren.
- Teamweit einheitlich entweder `rebase` oder `merge` verwenden.
- Empfehlung: `rebase`, um eine lineare Historie zu behalten.
