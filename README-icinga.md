# Icinga2 Integration (Mail Heartbeat Check)

Diese Anleitung beschreibt ausschließlich die Nutzung von `mail_check.py` mit Icinga2.

## 1. Grundlagen

`mail_check.py` deckt zwei Active-Check-Use-Cases ab:

- `send`: aktiver Testversand einer Mail (Versandpfad)
- `check`: aktiver Empfangs-Check (Mailbox + JWT-Validierung)

Wichtige Betriebsarten für `check`:

- `check --no-icinga-submit`: nur lokaler Plugin-Output (typischer Active Check)
- `check` mit `ICINGA_PASSIVE_CHECK=1`: zusätzlicher passiver Submit zur Icinga-API
- `check` mit `ICINGA_PASSIVE_CHECK=0`: kein passiver Submit

## 2. Empfehlung: mindestens 2 Icinga-Instanzen

Empfohlen sind mindestens zwei getrennte Instanzen:

1. Instanz A für `send` (Versand)
2. Instanz B für `check` (Empfang)

Vorteile:

- klare Trennung von Versand- und Empfangsfehlern
- weniger Blind Spots bei Ausfall einer Instanz
- bessere Nachvollziehbarkeit im Incident-Fall

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

Für beide Pfade (`send` und `check`) ist relevant:

- `MAIL_CHECK_JWT_SECRET`
- optional `MAIL_CHECK_JWT_MAX_AGE_SECONDS`

Nur für Empfang (`check`/`email`) zusätzlich erforderlich:

- `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_MAILBOX`
- `MAIL_ACTIVE_CONFIG` (z. B. `config/match_criteria_icingamail_send_test.env`)
- Match-Criteria-Datei mit `MAIL_SUBJECT_CONTAINS`, `MAIL_FROM_CONTAINS`, optional `MAIL_BODY_CONTAINS`

Hinweis: `send` benötigt **kein** `MAIL_ACTIVE_CONFIG`.

### 4.2 Versand-Konfiguration (`send`)

Optionale Send-Werte (mit Defaults/Fallbacks):

- `MAIL_SEND_BACKEND=sendmail|mail|smtp` (Default: `sendmail`)
- `MAIL_SEND_TO` (Fallback: `IMAP_USER`, wenn E-Mail-Adresse)
- `MAIL_SEND_FROM` (Fallback: `MAIL_FROM_CONTAINS`, sonst `MAIL_SEND_TO`)
- `MAIL_SEND_SUBJECT` (Default: `IcingaMail: Send test`)
- `MAIL_SEND_BODY` (Default: `IcingaMail Send test`)

Backend-spezifisch:

- `sendmail`: `MAIL_SEND_SENDMAIL_COMMAND` (Default: `/usr/sbin/sendmail -t -i`)
- `mail`: `MAIL_SEND_MAIL_COMMAND` (Default: `/usr/bin/mail`)
- `smtp`: `MAIL_SEND_SMTP_HOST` (Pflicht), plus `MAIL_SEND_SMTP_*`

Wichtig bei `sendmail`:

- Envelope-From wird aus `MAIL_SEND_FROM` per `-f` gesetzt.
- Wenn Postfix-Absenderrechte eingeschränkt sind, muss der Absender serverseitig erlaubt sein.

`send` liefert Perfdata für Icinga:

- `send_command_seconds`
- `send_message_bytes`

Lokaler Test:

```bash
./mail_check.py send
```

### 4.3 Empfang-Konfiguration (`check`)

Für reine Active Checks empfohlen:

```bash
./mail_check.py check --no-icinga-submit
```

Alternativ global über Setting:

```bash
ICINGA_PASSIVE_CHECK=0
```

Dann reicht:

```bash
./mail_check.py check
```

Optionale Empfangssteuerung:

- `MAIL_INCLUDE_SEEN=1`
- `MAIL_DELETE_MATCH=1`

### 4.4 Passive API-Konfiguration (nur wenn benötigt)

Nur nötig, wenn `check` zusätzlich passiv submitten soll:

- `ICINGA_URL`
- `ICINGA_USER`
- `ICINGA_PASSWORD`
- `ICINGA_HOST`
- `ICINGA_SERVICE`
- optional `ICINGA_VERIFY_TLS`, `ICINGA_DEBUG`, `ICINGA_DRY_RUN`

## 5. Einrichtung in Icinga2

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

### 5.4 Konfiguration prüfen und neu laden

```bash
sudo icinga2 daemon -C
sudo systemctl reload icinga2
```

## 6. Exit-Codes

- `0`: OK
- `2`: CRITICAL
- `3`: UNKNOWN
