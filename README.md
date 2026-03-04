# Mailbox Polling + Icinga2 Passive Check

Dieses Projekt enthält ein Skript, das:

1. per IMAP ein Postfach abfragt,
2. auf eine erwartete Mail prüft,
3. die Treffer optional löscht,
4. das Ergebnis optional als passiven Service-Check an Icinga2 meldet.

## Script

`scripts/check_mail_and_notify_icinga.py`

## Python venv

```bash
cd /home/patric/apache/projekte/check_emails
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Zum Verlassen der venv:

```bash
deactivate
```

## Konfiguration

1. Beispiel kopieren:
   ```bash
   cp config/mail_check.env.example config/mail_check.env
   ```
2. Werte in `config/mail_check.env` eintragen.

## Aufruf

```bash
source .venv/bin/activate
set -a
source config/mail_check.env
set +a

./scripts/check_mail_and_notify_icinga.py
```

## Alle 5 Minuten per Cron

```cron
*/5 * * * * cd /home/patric/apache/projekte/check_emails && set -a && . ./config/mail_check.env && set +a && ./scripts/check_mail_and_notify_icinga.py >> /tmp/mail_check.log 2>&1
```

## Match-Logik

- Standardmäßig wird auf `UNSEEN` geprüft.
- `MAIL_SUBJECT_CONTAINS` und optional `MAIL_FROM_CONTAINS` verengen die Suche.
- Optional kann ein kompletter Header als Vorlage genutzt werden:
  `MAIL_HEADER_TEMPLATE_FILE=/.../diverses/mail_header.txt`.
- Welche Header daraus in die Suche einfließen, steuerst du mit
  `MAIL_TEMPLATE_HEADERS` (CSV), z. B. `Subject,From,To,Return-Path,X-KasLoop`.
- Bei Header-Vorlage werden `From`/`To`/`Return-Path` automatisch auf die reine
  E-Mail-Adresse normalisiert, damit IMAP-SEARCH keine `BAD`-Fehler wegen
  Leerzeichen erzeugt.
- Mit `MAIL_DELETE_MATCH=1` werden Treffer nach dem Check gelöscht.

## Icinga Benachrichtigung (optional)

- Standard: `MAIL_NOTIFY_ICINGA=1` (Benachrichtigung aktiv).
- Deaktivieren mit `MAIL_NOTIFY_ICINGA=0` oder CLI-Flag `--no-notify-icinga`.
- Wenn Benachrichtigung aktiv ist, sind `ICINGA_URL`, `ICINGA_USER`,
  `ICINGA_PASSWORD`, `ICINGA_HOST`, `ICINGA_SERVICE` Pflicht.
- Für Debug-Ausgabe des kompletten API-Calls:
  `MAIL_DEBUG_ICINGA=1`
- Für reinen Test ohne echten Submit:
  `MAIL_ICINGA_DRY_RUN=1` (nur zusammen mit Debug sinnvoll).

## Einbindung in Icinga2

### 1. API-User für passive Check-Results anlegen

Datei z. B. `/etc/icinga2/conf.d/api-users.conf`:

```icinga2
object ApiUser "mail-check-api" {
  password = "CHANGE_ME"
  permissions = [
    "actions/process-check-result",
    "objects/query/Host",
    "objects/query/Service"
  ]
}
```

Danach in `config/mail_check.env` setzen:

```bash
ICINGA_URL=https://<icinga-master>:5665
ICINGA_USER=mail-check-api
ICINGA_PASSWORD=CHANGE_ME
```

### 2. Host + Service für passive Ergebnisse definieren

Datei z. B. `/etc/icinga2/conf.d/mail-heartbeat.conf`:

```icinga2
object Host "my-mail-check-host" {
  import "generic-host"
  address = "127.0.0.1"
  check_command = "hostalive"
}

object Service "mail-heartbeat" {
  host_name = "my-mail-check-host"
  check_command = "dummy"
  enable_active_checks = false
  enable_passive_checks = true
  max_check_attempts = 1
  check_interval = 5m
  retry_interval = 1m
}
```

Wichtig: `ICINGA_HOST` und `ICINGA_SERVICE` in deiner `mail_check.env` müssen
genau auf diese Objekt-Namen passen.

### 3. Config prüfen und Icinga2 neu laden

```bash
sudo icinga2 daemon -C
sudo systemctl reload icinga2
```

### 4. Mail-Checker regelmäßig ausführen

Entweder per Cron (siehe Abschnitt oben) oder per systemd timer auf dem System,
das Zugriff auf IMAP und die Icinga2-API hat.

### 5. Optional: nur lokal prüfen, ohne API-Meldung

Wenn der Exit-Code anderweitig verarbeitet wird:

```bash
MAIL_NOTIFY_ICINGA=0
```

## Troubleshooting Icinga-Submit

- Das Skript gibt bei erfolgreichem Submit jetzt zusätzlich aus:
  `Icinga submit OK - ...`
- Mit `MAIL_DEBUG_ICINGA=1` wird ausgegeben:
  Endpoint, JSON-Payload und ein vollständiger `curl`-Befehl zum Nachtesten.
- Wenn HTTP zwar klappt, aber kein Objekt getroffen wird, kommt jetzt ein
  Fehler (`UNKNOWN - Icinga submit failed: ... no results ...`).
- Prüfe in dem Fall zuerst:
  `ICINGA_HOST` und `ICINGA_SERVICE` exakt wie in Icinga2 definiert,
  API-Berechtigung `actions/process-check-result`, und URL `:5665`.

## Exit-Codes

- `0`: Matching-Mail gefunden (OK)
- `2`: Keine Matching-Mail gefunden (CRITICAL)
- `3`: Technischer Fehler (UNKNOWN)
