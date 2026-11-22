# ImmichHelper

Fotos in [Immich](https://immich.app) aussortieren und ordnen – mit einer schicken Oberfläche im Browser und auf dem Handy. Läuft als kleiner LXC-Container auf deinem Proxmox-Server, Design wie die [Proxmox Zentrale (BetterProxmoxUI)](https://github.com/Tillhnz/BetterProxmoxUI) und der [FileHelper](https://github.com/Tillhnz/FileHelper).

ImmichHelper arbeitet **ausschließlich über die Immich-API** und fasst nie Dateien auf der NAS an. Dadurch bleibt Immichs Datenbank immer stimmig, und alles Gelöschte landet im **Immich-Papierkorb**. Dort lässt es sich wiederherstellen, bis der Papierkorb geleert wird.

## Was ImmichHelper kann

**Aussortieren**
- **Wischen:** Foto für Foto entscheiden. Links heißt aussortieren, rechts behalten, nach oben Favorit, mit Rückgängig. Aussortiertes wird erst vorgemerkt und dann gesammelt gelöscht. Was du schon gesichtet hast, kommt nicht wieder. Du kannst nach Monat, Ereignis, Vorschlag oder zufällig wischen.
- **Duplikate:** nutzt Immichs eigene Duplikat-Erkennung und schlägt das beste Bild vor (Auflösung, Dateigröße, Infos). Pro Gruppe oder alle auf einmal.
- **Serien:** Fotos, die innerhalb weniger Sekunden aufgenommen wurden und sich stark ähneln. Vorgeschlagen wird das schärfste.
- **Unscharfe Fotos:** verwackelt oder daneben fokussiert. Bewertet wird das schärfste Motiv, deshalb gelten Porträts mit unscharfem Hintergrund trotzdem als scharf. Die Empfindlichkeit lässt sich per Schieberegler anpassen.
- **Fehlaufnahmen:** schwarz (z. B. aus der Hosentasche), einfarbig oder ausgefressen. Nachtfotos mit Lichtern zählen nicht dazu.
- **Screenshots** und **WhatsApp-, Telegram- und Signal-Bilder**
- **Sehr kurze Videos**, die meist aus Versehen gestartet wurden
- **Große Dateien**
- **RAW + JPG** (z. B. Fujifilm `.RAF`): Paare in Immich **stapeln**, RAW-Dateien finden, deren JPG schon gelöscht ist, und beim Löschen eines JPGs das RAW automatisch mitlöschen (abschaltbar)

Favoriten werden nie vorgeschlagen (einstellbar). Alles, was du einmal „behalten“ hast, taucht nicht mehr in den Vorschlägen auf.

**Ordnen**
- **Ereignisse:** Reisen werden über mehrere Tage zusammengefasst (z. B. „Bali · 10.–15. März 2025“), besondere Tage zu Hause einzeln erkannt (z. B. „Samstag, 14. Juni 2025“). Mit einem Tipp legst du daraus ein Album an oder fügst die Fotos einem bestehenden hinzu.
- **Quellen:** nach Kamera bzw. Handy (z. B. „Fujifilm X-S20“), Messenger oder Screenshots
- **Orte:** nach Land und Stadt aus den GPS-Daten
- **Ordner:** nach Speicherort in Immich (nützlich bei externen Bibliotheken)

**Außerdem**
- **Verlauf** mit Wiederherstellen und „Immich-Papierkorb leeren“. Erst nach dem Leeren wird der Platz auf der NAS frei.
- **Anmeldung mit dem Immich-Konto.** Jeder sieht nur seine eigenen Fotos, eigene Benutzer gibt es nicht. Wahlweise geht die Anmeldung auch mit einem API-Schlüssel (z. B. bei OAuth).
- **Schnelle Vorschauen:** Vorschaubilder werden zwischengespeichert, im Arbeitsspeicher und auf der Festplatte des Containers (Standard 192 MB bzw. 1,5 GB, einstellbar mit `IH_THUMB_MEM_MB`/`IH_THUMB_DISK_MB`). Aus dem Speicher kommen sie in wenigen Millisekunden. Beim Wischen werden die nächsten Bilder vorab geladen, und die Bildprüfung im Hintergrund macht Pause, solange du Fotos ansiehst.
- **Liest automatisch neu ein** (Standard: alle 12 Stunden) und prüft dabei nur neue Fotos
- Fürs Handy gemacht, hell und dunkel, alles auf Deutsch

## Installation (eine Zeile)

Auf dem **Proxmox-Server** als `root` ausführen (z. B. *Rechenzentrum → Knoten → Shell*):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/ImmichHelper/main/proxmox/create-lxc.sh)"
```

Das Skript

1. sucht dein Immich (Container oder VM mit „immich“ im Namen, Port 2283) und fragt nach, falls es Immich nicht findet,
2. legt einen kleinen, **unprivilegierten** Debian-Container an (2 Kerne, 1 GB RAM, 4 GB Festplatte, DHCP). Er braucht **keinen Zugriff auf die NAS**.
3. installiert ImmichHelper darin und zeigt am Ende die Adresse an.

Danach `http://<IP-des-Containers>:8080` im Browser öffnen und mit dem **Immich-Konto** anmelden. Beim ersten Anmelden wird die Bibliothek eingelesen. Jedes Foto wird dabei einmal geprüft (Schärfe, Helligkeit, Ähnlichkeit), bei vielen Tausend Fotos dauert das ein paar Minuten. Später kommen nur neue Fotos dazu.

Anpassen per Umgebungsvariablen:

```bash
CTID=151 IMMICH_URL=http://192.168.1.20:2283 bash -c "$(curl -fsSL https://raw.githubusercontent.com/Tillhnz/ImmichHelper/main/proxmox/create-lxc.sh)"
```

| Variable | Standard | Bedeutung |
|---|---|---|
| `CTID` | nächste freie | Container-ID |
| `CT_HOSTNAME` | `immichhelper` | Name des Containers |
| `IMMICH_URL` | wird gesucht | Adresse von Immich im Heimnetz |
| `STORAGE` | `local-lvm`/`local-zfs` | Speicher für die Container-Festplatte |
| `DISK_GB` / `CORES` / `MEMORY_MB` | `4` / `2` / `1024` | Größe |
| `IP` / `GW` / `VLAN` / `BRIDGE` | `dhcp` / – / – / `vmbr0` | Netzwerk |
| `PORT` | `8080` | Port der Oberfläche |
| `NTFY_TOPIC` | – | ntfy-Thema für Update-Nachrichten |
| `DEBIAN` | `12` | Debian-Version der Vorlage |

**Voraussetzung:** Immich ab Version 1.133, also Immich 2.x oder 3.x. Für die Duplikate muss das maschinelle Lernen in Immich laufen (*Verwaltung → Aufträge → Duplikat-Erkennung*).

## Von unterwegs und mit eigener Domain

ImmichHelper selbst spricht nur HTTP im Heimnetz. Für eine Adresse wie `aufraeumen.all-heinzen.de` legst du im **Nginx Proxy Manager** einen Proxy-Host auf `http://<IP-des-Containers>:8080` an (mit SSL). Unter *Einstellungen → Verbindung zu Immich → Adresse für Links* kannst du außerdem die öffentliche Immich-Adresse eintragen (z. B. `https://fotos.all-heinzen.de`). Dann öffnen die Links „In Immich öffnen“ auch unterwegs.

## Updates & Sicherheit (wie bei den anderen Helpern)

- **Dependabot** prüft wöchentlich die Python-Pakete und GitHub Actions. Für Sicherheitslücken gibt es sofort einen eigenen Pull Request (in GitHub unter *Settings → Code security → Dependabot alerts / security updates* einschalten).
- **Automatisch übernommen** werden kleine Updates und Sicherheitskorrekturen, sobald die Tests grün sind. Große Versionssprünge bleiben zum Ansehen liegen.
- **Sicherheitsprüfung** (`pip-audit`) läuft bei jeder Änderung und jeden Morgen.
- **Push-Nachricht** über [ntfy](https://ntfy.sh) bei jeder neuen Version, Sicherheitsupdates mit hoher Priorität. Das Thema trägst du unter *Einstellungen → Benachrichtigungen* ein.

## Aktualisieren & Befehle

- In der Oberfläche (für Immich-Admins): **Einstellungen → System → Aktualisieren**
- Auf dem Proxmox-Host: das Installations-Skript einfach noch einmal ausführen
- Im Container (`pct enter <CTID>`):

| Befehl | Wirkung |
|---|---|
| `immichhelper status` | Verbindung zu Immich und eingelesene Bibliotheken |
| `immichhelper url http://<IP>:2283` | Immich-Adresse ändern |
| `immichhelper update` | neueste Version installieren |
| `immichhelper logs` | Protokoll ansehen |
| `immichhelper logout-all` | alle Anmeldungen beenden |
| `immichhelper uninstall` | entfernen (Fotos in Immich bleiben unberührt) |

Einstellungen stehen in `/etc/immichhelper.env` (danach `immichhelper restart`).

## Sicherheit

- Anmeldung über Immich selbst. ImmichHelper speichert keine Passwörter, nur Immichs Sitzungs-Token (im Container, nur für root lesbar). Beim Abmelden wird die Sitzung auch in Immich beendet.
- Sperre nach 10 Fehlversuchen für 15 Minuten
- Sitzungs-Cookie `HttpOnly`/`SameSite=Strict`, Schutz gegen fremde Seiten (CSRF), strenge Content-Security-Policy
- Gelöscht wird nur in den Immich-Papierkorb. Endgültig löscht erst „Papierkorb leeren“ (mit Rückfrage) oder Immich selbst nach Ablauf der Frist.
- Läuft in einem unprivilegierten Container ohne Zugriff auf die NAS

## Technik

Python (Starlette/Uvicorn) und eine Oberfläche ohne Build-Schritt (Vanilla-JS, gleiche Bausteine wie die Proxmox Zentrale). Eine Kopie der Metadaten liegt in SQLite unter `/var/lib/immichhelper`. So bleiben Gruppieren und Sortieren auch bei großen Bibliotheken schnell. Für die Bildprüfung lädt ImmichHelper Immichs Vorschaubilder und berechnet daraus mit Pillow und NumPy:

- Schärfe: Laplace-Varianz in 4×4 Kacheln, gewertet wird die zweitschärfste Kachel
- Helligkeit: Mittelwert, Streuung und hellste Stellen
- Fingerabdruck für Ähnlichkeit (dHash)

Lokal ausprobieren, auch ohne echtes Immich (mit einem Schein-Immich samt Beispielbibliothek):

```bash
pip install -r backend/requirements-dev.txt
python -m tests.fake_immich &                       # Schein-Immich auf Port 2283, Anmeldung till@example.com / test
IH_STATE_DIR=./data uvicorn backend.app:app --port 8080
# im Browser http://localhost:8080 öffnen, Immich-Adresse: localhost:2283
python -m pytest -q tests                           # Tests gegen die alte (Seiten) und neue (Cursor) Immich-API
```
