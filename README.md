# Mailbox Polling + Icinga2 Passive Check

Dieses Projekt enthält ein Skript, das:

1. per IMAP ein Postfach abfragt,
2. auf eine erwartete Mail prüft,
3. die Treffer optional löscht,
4. das Ergebnis optional als passiven Service-Check an Icinga2 meldet,
5. optional eine Testmail über `sendmail`, `mail` oder `smtp` versendet.

## Script

`scripts/check_mail_and_notify_icinga.py`

## Python venv

```bash
cd /path/to/check_emails
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
   cp config/settings.env.example config/settings.env
   ```
2. Werte in `config/settings.env` eintragen.
3. Die Datei wird beim Skriptstart automatisch via dotenv geladen.
4. `config/settings.env` ist die Standard-Konfiguration.
5. `MAIL_ACTIVE_CONFIG` ist Pflicht und muss auf eine Match-Criteria-Datei zeigen:
   ```bash
   MAIL_ACTIVE_CONFIG=config/match_criteria_<profil>.env
   ```

## Aufruf

```bash
source .venv/bin/activate

# zeigt nur die Hilfe
./scripts/check_mail_and_notify_icinga.py

# prüft Mailbox + sendet Ergebnis an Icinga
./scripts/check_mail_and_notify_icinga.py check

# prüft nur Mailbox (kein Icinga-Submit)
./scripts/check_mail_and_notify_icinga.py email

# testet nur Icinga-Submit (kein Mailbox-Poll)
./scripts/check_mail_and_notify_icinga.py icinga

# Standard für icinga-Test: UNKNOWN (exit_status=3),
# per Parameter überschreibbar, z. B. OK:
./scripts/check_mail_and_notify_icinga.py icinga --test-exit-status 0 --test-output "OK - manueller Icinga-Test"

# lädt eine alternative vollständige Config (wie settings.env.example aufgebaut)
./scripts/check_mail_and_notify_icinga.py -c config/mailbox_settings.env check

# versendet eine Testmail über den konfigurierten Backend-Weg
./scripts/check_mail_and_notify_icinga.py send

# Backend explizit überschreiben
./scripts/check_mail_and_notify_icinga.py send --send-backend mail
./scripts/check_mail_and_notify_icinga.py send --send-backend smtp

# erstellt aus einer Mail-Quelltext-Vorlage eine Match-Criteria-Config
./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt

# setzt die erzeugte Match-Criteria-Config direkt als Standard in settings.env
./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt -d

# erstellt zusätzlich eine neue vollständige Config aus settings.env.example
./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt --new-config mailbox_settings.env
```

## Alle 5 Minuten per Cron

Cron-Zeile mit aktuellen Pfaden automatisch ausgeben:

```bash
.venv/bin/python ./scripts/check_mail_and_notify_icinga.py --print-cron-line
```

```cron
*/5 * * * * /path/to/check_emails/.venv/bin/python /path/to/check_emails/scripts/check_mail_and_notify_icinga.py check >> /tmp/mail_check.log 2>&1
```

Hinweis:
- `set -a` und `source config/settings.env` sind nicht mehr nötig, da das Skript die Datei per dotenv selbst lädt.
- Mit `--config`/`-c` lädst du eine alternative vollständige Settings-Datei (wie `settings.env.example` aufgebaut).
- `MAIL_ACTIVE_CONFIG` in `config/settings.env` ist Pflicht.
- Der Aufruf über die venv-Python stellt sicher, dass `python-dotenv` in Cron auch wirklich verfügbar ist.

## Profil aus Vorlage erzeugen

Wenn du nicht bei jedem Aufruf manuell Match-Kriterien pflegen willst:

1. Lege in `vorlagen/` eine Datei mit dem vollständigen Mail-Quelltext an
   (Header + Body, nicht nur Header).
2. Vorlage einlesen und Match-Criteria-Profil erzeugen:
   ```bash
   ./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt
   ```
3. Das Skript erstellt standardmäßig eine `.env` in `./config`, deren Name mit `match_criteria_` beginnt.
4. `MAIL_SUBJECT_CONTAINS`, `MAIL_FROM_CONTAINS` und (wenn ermittelbar)
   `MAIL_BODY_CONTAINS` werden aus der Vorlage übernommen.
5. Die erzeugte Datei enthält nur den Block `Match criteria`.
6. Optional als Standard setzen:
   ```bash
   ./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt -d
   ```
7. Optional neue vollständige Settings-Datei aus dem Example erzeugen:
   ```bash
   ./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt --new-config mailbox_settings.env
   ```
8. Optional eigenen Ausgabepfad für die Match-Criteria-Datei setzen:
   ```bash
   ./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt -o config/match_criteria_custom.env
   ```
9. Existierende Match-Criteria-Datei gezielt überschreiben:
   ```bash
   ./scripts/check_mail_and_notify_icinga.py template-config -f ./vorlagen/kvm-web-guh.txt -o config/match_criteria_custom.env --force
   ```

Hinweis: `config/settings.env` ist geschützt und wird von `template-config` nicht als Ausgabeziel überschrieben.

## Match-Logik

- Standardmäßig wird auf `UNSEEN` geprüft.
- `MAIL_SUBJECT_CONTAINS` und optional `MAIL_FROM_CONTAINS` verengen die Suche.
- `MAIL_BODY_CONTAINS` sucht zusätzlich im Mail-Inhalt (Body).
- `MAIL_INCLUDE_SEEN=1` berücksichtigt auch bereits gelesene Mails, mit `0` nur `UNSEEN`.
- Mit `MAIL_DELETE_MATCH=1` werden Treffer nach dem Check gelöscht.

## Icinga-Konfiguration

- Für `check` und `icinga` sind `ICINGA_URL`, `ICINGA_USER`,
  `ICINGA_PASSWORD`, `ICINGA_HOST`, `ICINGA_SERVICE` Pflicht.
- Für Debug-Ausgabe des kompletten API-Calls:
  `ICINGA_DEBUG=1`
- Für reinen Test ohne echten Submit:
  `ICINGA_DRY_RUN=1` (nur zusammen mit Debug sinnvoll).

## Mail-Versand-Konfiguration (`send`)

Der Command `send` prüft den realen Versandweg einer Anwendung. Unterstützte Wege:

- `sendmail` (z. B. PHP `sendmail_path=/usr/sbin/sendmail -t -i`)
- `mail` (z. B. `/usr/bin/mail` aus CLI)
- `smtp` (direkter SMTP-Versand)

Pflicht-/Basiswerte:

- `MAIL_SEND_BACKEND=sendmail|mail|smtp`
- `MAIL_SEND_TO=<zieladresse>`
- `MAIL_SEND_FROM=<absenderadresse>`
- `MAIL_SEND_SUBJECT=<betreff>`
- `MAIL_SEND_BODY=<inhalt>`

Backend-spezifisch:

- `sendmail`: `MAIL_SEND_SENDMAIL_COMMAND` (Standard: `/usr/sbin/sendmail -t -i`)
- `mail`: `MAIL_SEND_MAIL_COMMAND` (Standard: `/usr/bin/mail`)
- `smtp`: `MAIL_SEND_SMTP_HOST`, `MAIL_SEND_SMTP_PORT`, optional
  `MAIL_SEND_SMTP_USER`, `MAIL_SEND_SMTP_PASSWORD`,
  `MAIL_SEND_SMTP_STARTTLS`, `MAIL_SEND_SMTP_SSL`

Beispiele:

```bash
# sendmail
./scripts/check_mail_and_notify_icinga.py send --send-backend sendmail

# mail
./scripts/check_mail_and_notify_icinga.py send --send-backend mail

# smtp
./scripts/check_mail_and_notify_icinga.py send --send-backend smtp --smtp-host smtp.example.net
```

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

Danach in `config/settings.env` setzen:

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

Wichtig: `ICINGA_HOST` und `ICINGA_SERVICE` in deiner `settings.env` müssen
genau auf diese Objekt-Namen passen.

### 3. Config prüfen und Icinga2 neu laden

```bash
sudo icinga2 daemon -C
sudo systemctl reload icinga2
```

### 4. Mail-Checker regelmäßig ausführen

Entweder per Cron (siehe Abschnitt oben) oder per systemd timer auf dem System,
das Zugriff auf IMAP und die Icinga2-API hat.

### 5. Optional: nur Mailbox prüfen, ohne API-Meldung

Wenn der Exit-Code anderweitig verarbeitet wird:

```bash
./scripts/check_mail_and_notify_icinga.py email
```

## Troubleshooting Icinga-Submit

- Das Skript gibt bei erfolgreichem Submit jetzt zusätzlich aus:
  `Icinga submit OK - ...`
- Mit `ICINGA_DEBUG=1` wird ausgegeben:
  Endpoint, JSON-Payload und ein vollständiger `curl`-Befehl zum Nachtesten.
- Wenn HTTP zwar klappt, aber kein Objekt getroffen wird, kommt jetzt ein
  Fehler (`UNKNOWN - Icinga submit failed: ... no results ...`).
- Prüfe in dem Fall zuerst:
  `ICINGA_HOST` und `ICINGA_SERVICE` exakt wie in Icinga2 definiert,
  API-Berechtigung `actions/process-check-result`, und URL `:5665`.

## Exit-Codes

- `check`/`email`:
  - `0`: Matching-Mail gefunden (OK)
  - `2`: Keine Matching-Mail gefunden (CRITICAL)
  - `3`: Technischer Fehler (UNKNOWN)
- `icinga`:
  - `0`: Test-Submit erfolgreich
  - `3`: Technischer Fehler beim Icinga-Submit
- `template-config`:
  - `0`: Match-Criteria-Profil (und optional neue Voll-Config) erfolgreich erzeugt
  - `3`: Technischer Fehler (z. B. Vorlage fehlt, Header fehlt, Ziel existiert, geschützte Datei)
- `send`:
  - `0`: Testmail erfolgreich versendet
  - `3`: Technischer Fehler beim Versand
