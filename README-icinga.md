# Icinga2 Integration (Active Checks für Mail-Versand und Mail-Empfang)

Diese Anleitung beschreibt ausschließlich die Nutzung dieses Projekts mit Icinga2.

## 1. Grundlagen

Das Skript `mail_check.py` unterstützt für Icinga zwei zentrale Active-Check-Use-Cases:

- `send`: triggert aktiv den Testversand einer Mail (Versandprüfung)
- `check --no-icinga-submit`: prüft den Mail-Empfang inklusive JWT-Validierung (Empfangsprüfung)

Beide Commands liefern Plugin-Output und passende Exit-Codes (`0`, `2`, `3`) direkt für Icinga.

Hinweis:
- `check` ohne `--no-icinga-submit` nutzt zusätzlich den passiven API-Submit nach Icinga.
- Für reine Active-Check-Services in Icinga wird `check --no-icinga-submit` empfohlen.
- Alternativ kann das global über `ICINGA_PASSIVE_CHECK=0` gesteuert werden.

## 2. Empfehlung: mindestens 2 Icinga-Instanzen

Empfohlen ist der Betrieb mit mindestens zwei getrennten Icinga-Instanzen:

1. Versand-Instanz
2. Empfangs-Instanz

Warum diese Trennung sinnvoll ist:

- bessere Fehlerlokalisierung (Versandpfad vs. Empfangspfad)
- geringere Blind Spots bei Störungen einer einzelnen Instanz
- klarere Verantwortlichkeit je Monitoring-Pfad

Typisches Muster:

- Instanz A führt den Service für `send` aus.
- Instanz B führt den Service für `check --no-icinga-submit` aus.

## 3. Installation

### 3.1 Projekt bereitstellen

```bash
cd /opt
git clone <repo-url> check_emails
cd check_emails
```

### 3.2 Python-Umgebung aufbauen

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.3 Basiskonfiguration anlegen

```bash
cp config/settings.env.example config/settings.env
```

## 4. Konfiguration

### 4.1 Gemeinsame Basis

In `config/settings.env` müssen mindestens diese Werte gepflegt werden:

- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_MAILBOX`
- `MAIL_CHECK_JWT_SECRET`
- `MAIL_CHECK_JWT_MAX_AGE_SECONDS`
- `MAIL_ACTIVE_CONFIG` (z. B. `config/match_criteria_icingamail_send_test.env`)

Zusätzlich wird eine Match-Criteria-Datei benötigt, z. B.:

`config/match_criteria_icingamail_send_test.env`

mit:

- `MAIL_SUBJECT_CONTAINS`
- `MAIL_FROM_CONTAINS`
- optional `MAIL_BODY_CONTAINS`

### 4.2 Versand-Konfiguration (`send`)

Für den Versandservice in Icinga:

- `MAIL_SEND_BACKEND=sendmail|mail|smtp` (optional, Default `sendmail`)
- `MAIL_SEND_TO` (optional, Fallback: `IMAP_USER`, wenn E-Mail)
- `MAIL_SEND_FROM` (optional, Fallback: `MAIL_FROM_CONTAINS`, sonst `MAIL_SEND_TO`)
- `MAIL_SEND_SUBJECT` (optional)
- `MAIL_SEND_BODY` (optional)

Je nach Backend zusätzlich:

- `MAIL_SEND_SENDMAIL_COMMAND` oder
- `MAIL_SEND_MAIL_COMMAND` oder
- `MAIL_SEND_SMTP_*`

Test lokal:

```bash
./mail_check.py send
```

### 4.3 Empfang-Konfiguration (`check --no-icinga-submit`)

Für den Empfangsservice in Icinga sind die IMAP- und Match-Criteria-Werte entscheidend.
Wenn du den passiven API-Submit global deaktivieren willst, setze:

`ICINGA_PASSIVE_CHECK=0`

Dann reicht auch der Aufruf `check` ohne zusätzliches `--no-icinga-submit`.

Test lokal:

```bash
./mail_check.py check --no-icinga-submit
```

Optional:

- `MAIL_INCLUDE_SEEN=1`, wenn auch gelesene Mails berücksichtigt werden sollen
- `MAIL_DELETE_MATCH=1`, wenn Treffer nach erfolgreichem Check gelöscht werden sollen

## 5. Einrichtung in Icinga2

Die folgenden Beispiele zeigen die Einbindung als Active Checks über `CheckCommand`, `Host` und `Service`.

### 5.1 CheckCommand-Objekte

Beispiel-Datei: `/etc/icinga2/conf.d/mail-heartbeat-commands.conf`

```icinga2
object CheckCommand "mail_heartbeat_send" {
  command = [ "/opt/check_emails/.venv/bin/python", "/opt/check_emails/mail_check.py", "send" ]
}

object CheckCommand "mail_heartbeat_receive" {
  command = [ "/opt/check_emails/.venv/bin/python", "/opt/check_emails/mail_check.py", "check", "--no-icinga-submit" ]
}
```

### 5.2 Host-Objekt

Beispiel-Datei: `/etc/icinga2/conf.d/mail-heartbeat-hosts.conf`

```icinga2
object Host "mail-heartbeat-host" {
  import "generic-host"
  address = "127.0.0.1"
  check_command = "hostalive"
}
```

### 5.3 Service-Objekte

Beispiel-Datei: `/etc/icinga2/conf.d/mail-heartbeat-services.conf`

```icinga2
object Service "mail-heartbeat-send" {
  host_name = "mail-heartbeat-host"
  check_command = "mail_heartbeat_send"
  check_interval = 5m
  retry_interval = 1m
  max_check_attempts = 1
}

object Service "mail-heartbeat-receive" {
  host_name = "mail-heartbeat-host"
  check_command = "mail_heartbeat_receive"
  check_interval = 5m
  retry_interval = 1m
  max_check_attempts = 1
}
```

### 5.4 Icinga-Konfiguration prüfen und neu laden

```bash
sudo icinga2 daemon -C
sudo systemctl reload icinga2
```

## 6. Exit-Codes für Icinga

- `0`: OK
- `2`: CRITICAL (z. B. keine passende Mail gefunden)
- `3`: UNKNOWN (technischer Fehler)
