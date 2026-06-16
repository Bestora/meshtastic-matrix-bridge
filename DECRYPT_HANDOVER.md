# Handover: Meshtastic-MQTT-Decrypt (für die Matrix-Bridge)

**Stand:** 2026-06-16
**Kontext:** Die Telegram-Fork dieses Projekts (`mqtt-meshtastic-telegram-bridge`)
wurde aus diesem Matrix-Repo kopiert. Beim Live-Betrieb sind im
**Decrypt-Pfad mehrere Bugs** aufgefallen und in der Fork gefixt worden. Dieses
Dokument übergibt die Erkenntnisse + die exakten Änderungen, damit sie hier
(Matrix) übernommen werden können. **Die `mqtt_client.py` ist in beiden Repos
identisch**, die Diffs unten passen also direkt.

> TL;DR: Die wichtigste Sache ist **Fix 1 (Nonce)**. Ohne ihn schlägt *jede*
> Entschlüsselung fehl, und es kommen nur Pakete durch, die ein Gateway bereits
> *entschlüsselt* zu MQTT hochlädt (MQTT-Option „Encryption" = aus).

---

## 1. Symptome, die wir gesehen haben

| Symptom | Ursache |
|--------|---------|
| Nur ein Gateway pro Nachricht, obwohl Malla 2+ zeigt | Pakete von Gateways mit „Encryption AN" werden verschlüsselt hochgeladen und scheitern beim Entschlüsseln → verworfen. Nur „Encryption AUS"-Gateways (decoded Upload) kommen durch. |
| `Failed to decrypt … Invalid key size (8) for AES` | Konfigurierter `MESHTASTIC_CHANNEL_PSK` ist kein gültiger AES-Key (muss 16/24/32 Byte sein). |
| `Failed to decrypt … 'meshtastic.protobuf.Data': Wire format was corrupt` | Key-Größe ok, aber **Nonce falsch gebaut** → Keystream falsch → Klartext ist Müll. **(Fix 1)** |
| Manche Node-Namen werden nie aufgelöst | `_node_id_to_str` füllt nicht auf 8 Hex-Stellen auf → Mismatch zu `gateway_id`. **(Fix 2)** |
| Gateway-Pakete fehlen ganz / Channel-Decrypt-Spam | Abo-Topic zu eng bzw. fehlender Channel-Guard vor dem Entschlüsseln. **(Fix 3 + Config)** |

---

## 2. So funktioniert die Meshtastic-MQTT-Entschlüsselung

- Ein Gateway lädt jedes Paket als `ServiceEnvelope` (Protobuf) zu MQTT hoch.
  Im enthaltenen `MeshPacket` ist entweder das Feld **`decoded`** (Klartext) oder
  **`encrypted`** gesetzt — abhängig von der MQTT-Option **„Encryption Enabled"**
  des jeweiligen Gateways:
  - **AN**  → `encrypted` ist gesetzt → die Bridge muss selbst entschlüsseln.
  - **AUS** → `decoded` ist gesetzt → die Bridge liest direkt.
- Verschlüsselung: **AES-CTR** mit dem Channel-PSK als Key.
- **Nonce / Initial-Counter-Block (16 Byte), Little-Endian:**
  ```
  Byte  0–7 : packet.id   (als 64-Bit LE; die oberen 4 Byte sind 0)
  Byte  8–15: packet.from  (Node-ID als LE; obere 4 Byte sind 0 bei 32-Bit-IDs)
  ```
  Äquivalent in Python:
  ```python
  nonce = packet.id.to_bytes(8, "little") + getattr(packet, "from").to_bytes(8, "little")
  ```
- **Key (PSK):** base64-dekodiert, muss **16, 24 oder 32 Byte** ergeben.
  - LongFast/Default-Channel: `1PG7OiApB1nwvP+rz05pAQ==` (16 Byte, AES-128).
  - **Achtung:** Der 1-Byte-Kurzschlüssel `AQ==` funktioniert **nicht** — die
    Firmware expandiert ihn intern zum Default-Key; dieser Code macht das
    **nicht**. Immer den vollen Base64-Key eintragen.

---

## 3. Die Fixes (Diffs für `mqtt_client.py`)

### Fix 1 — Nonce-Konstruktion  ⬅️ kritisch

Aktuell (ca. Z. 245–264):

```python
            # Nonce Construction (Meshtastic 1.2+ usually)
            # ...
            packet_id_bytes = packet.id.to_bytes(4, byteorder='little')
            from_id_bytes = getattr(packet, 'from').to_bytes(4, byteorder='little')
            # ...
            nonce_iv = packet_id_bytes + from_id_bytes + (b'\x00' * 8)

            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce_iv), backend=default_backend())
```

Problem: `from` landet bei **Byte 4** statt Byte 8 → falscher Keystream.

Neu:

```python
            # Meshtastic AES-CTR nonce / initial counter block (16 bytes):
            #   bytes 0-7  : packet id    (64-bit little-endian; high 4 bytes are 0)
            #   bytes 8-15 : from node id (little-endian; high 4 bytes are 0 for 32-bit ids)
            nonce_iv = packet.id.to_bytes(8, "little") + getattr(packet, "from").to_bytes(8, "little")

            cipher = Cipher(algorithms.AES(key), modes.CTR(nonce_iv), backend=default_backend())
```

### Fix 2 — Node-ID auf 8 Hex-Stellen padden

`_node_id_to_str` ist **doppelt** definiert (Z. 228–230 **und** 283–285) und
beide Versionen sind fehlerhaft. Beide ersetzen (das Duplikat darf entfernt
werden):

```python
    def _node_id_to_str(self, node_id):
        # Convert integer node_id to !Hex string
        return "!" + hex(node_id)[2:]
```

durch:

```python
    def _node_id_to_str(self, node_id):
        # "!" + 8 zero-padded hex digits, matching the firmware/gateway_id
        # convention so NODEINFO and gateway lookups use the same key
        # (otherwise names never resolve for ids with a leading 0 nibble).
        return "!" + format(node_id & 0xFFFFFFFF, "08x")
```

Hintergrund: `gateway_id` aus dem `ServiceEnvelope` kommt schon `!`+8-stellig
(z. B. `!0abc1234`). NODEINFO würde sonst unter `!abc1234` gespeichert → der
Name wird beim Gateway-Lookup nie gefunden.

### Fix 3 — Channel-Guard vor dem Entschlüsseln + Diagnose (robustness)

Damit man breit abonnieren kann (alle Gateways erfassen), ohne Decrypt-Spam von
Fremd-Channels, und um Mehrfach-Empfänge im Log zu sehen.

`_on_message`: Topic mitgeben

```python
            channel_name = self._extract_channel_name(msg.topic)
            self._process_service_envelope(se, channel_name, msg.topic)
```

`_process_service_envelope(self, se, channel_name: str)` →
`_process_service_envelope(self, se, channel_name: str, topic: str = "")`, und der
Dispatch-Block (aktuell Z. 136–144):

```python
        allowed = config.MESHTASTIC_CHANNELS
        is_our_channel = channel_name in allowed or str(packet.channel) in allowed

        if is_our_channel:
            logger.info(
                f"MQTT RX: packet={packet.id} gateway={gateway_id} "
                f"channel={channel_name} hops={hop_count} rssi={rssi} topic={topic}"
            )
        else:
            logger.debug(f"MQTT RX (foreign channel '{channel_name}'): packet={packet.id} topic={topic}")

        if packet.HasField("decoded"):
            # Decoded packets (incl. NODEINFO from any channel) handled directly;
            # the bridge applies the channel filter for text/reactions.
            self._handle_decoded_packet(packet, stats, channel_name)
        elif packet.HasField("encrypted") and config.MESHTASTIC_CHANNEL_PSK:
            # Only decrypt our own channel(s); foreign channels use different keys.
            if is_our_channel or channel_name == "Unknown":
                self._try_decrypt(packet, stats, channel_name)
            else:
                logger.debug(f"Skipping decrypt for foreign channel '{channel_name}' (packet {packet.id})")
```

---

## 4. Konfiguration / Betrieb

- **Ein Channel pro Instanz.** In der `.env`:
  - MeshSH:   `MESHTASTIC_CHANNELS=MeshSH`   + `MESHTASTIC_CHANNEL_PSK=<32-Byte-MeshSH-Base64-Key>`
  - LongFast: `MESHTASTIC_CHANNELS=LongFast` + `MESHTASTIC_CHANNEL_PSK=1PG7OiApB1nwvP+rz05pAQ==`
- **Breites Abo**, damit alle Gateways erfasst werden (Channel-Filter sortiert danach):
  `MQTT_TOPIC=msh/EU_868/#`  (das `/#` wird ohnehin automatisch angehängt).
- Den **echten PSK niemals** in `.env.example`/Git committen — nur Platzhalter.
- paho-mqtt 2.x: `mqtt.Client()` ohne `CallbackAPIVersion` läuft, gibt aber eine
  DeprecationWarning aus (harmlos). Bei Bedarf:
  `mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)`.

---

## 5. Verifikation

Lokaler Sanity-Check der Nonce + AES-CTR-Round-Trip (so in der Fork validiert):

```python
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from meshtastic import mesh_pb2, portnums_pb2

pid, frm = 0x11223344, 0xAABBCCDD
nonce = pid.to_bytes(8, "little") + frm.to_bytes(8, "little")
assert len(nonce) == 16
assert nonce[0:4] == pid.to_bytes(4, "little") and nonce[4:8] == b"\x00"*4
assert nonce[8:12] == frm.to_bytes(4, "little") and nonce[12:16] == b"\x00"*4

key = base64.b64decode("1PG7OiApB1nwvP+rz05pAQ==")          # 16 bytes
d = mesh_pb2.Data(); d.portnum = portnums_pb2.TEXT_MESSAGE_APP; d.payload = b"Test"
ct = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend()).encryptor()
blob = ct.update(d.SerializeToString()) + ct.finalize()
de = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend()).decryptor()
out = mesh_pb2.Data(); out.ParseFromString(de.update(blob) + de.finalize())   # parst sauber
print(out.portnum, out.payload)
```

Im Live-Betrieb nach dem Übernehmen der Fixes im Log erwarten:
```
Successfully decrypted packet <id>
Processing Packet <id> ... via gateway <!gw> ...
```
für Gateways mit „Encryption AN", und ein Edit der bestehenden Nachricht
(zweites Gateway), sobald ein weiteres Envelope desselben Pakets ankommt.

---

## 6. Referenz: entsprechende Commits in der Telegram-Fork

(Repo `mqtt-meshtastic-telegram-bridge`, Branch `main`)

- `6d397ec` — fix: Correct Meshtastic AES-CTR decryption nonce construction  *(Fix 1)*
- `ba1e7df` — fix: Zero-pad node id to 8 hex digits  *(Fix 2)*
- `70a271b` — feat: Per-reception MQTT diagnostics + guarded decryption  *(Fix 3)*

Diese betreffen ausschließlich `mqtt_client.py` und sind unabhängig von der
Telegram/Matrix-Frontend-Schicht — also direkt auf dieses Repo anwendbar.
