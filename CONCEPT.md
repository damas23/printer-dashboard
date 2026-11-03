# Konsep: Dashboard Monitoring Printer Terpusat

## 1. Latar belakang & temuan

Printer yang Anda sebutkan (`http://192.168.10.254/`) adalah perangkat **Fuji Xerox**
(web UI-nya memakai framework internal "wui"/`xux`, REST API ber-prefix `/home/api/`).

Hasil probe perangkat:

| Item | Nilai |
|---|---|
| Model | `C3070_SO` (ApeosPort-VII C3070 series) |
| Serial | 382039 |
| Firmware | 21.12.10 |
| Hostname | FF-1C7D224D7203 |
| Status | `SLEEP` |
| Autentikasi API | **Tidak perlu login** untuk `/home/api/*` |

Artinya supply & status bisa dibaca langsung via HTTP tanpa SNMP dan tanpa login.
Ini membuat pembuatan dashboard jadi sangat ringan.

### Endpoint REST yang berguna (GET, tanpa auth)

| Endpoint | Isi |
|---|---|
| `/home/api/about` | model, serial, firmware, hostname, status (`SLEEP`/`READY`), IP |
| `/home/api/supplies-info` | **toner, drum, waste toner box**: `Remaining` (%), `PageRemaining`, `LifeState`, `State`, `DateInstalled` |
| `/home/api/device-fault-notification` | fault yang sedang aktif + chain-link code |
| `/home/api/faulthistory` | riwayat error (chain code, link code, waktu) |
| `/home/api/paper-tray` | isi tiap tray + `Remaining` (%) + `Status` (READY/EMPTY) |
| `/home/api/billing-counter` | counter total/color/BW print-copy-scan-fax |

Contoh data live saat ini (`supplies-info`):

```
DRUM_Y 12%   DRUM_M 12%   DRUM_C 12%   DRUM_K 48%
TONER_Y 49%  TONER_M  8% (LifeState=PREPARATION)  TONER_C 75%  TONER_K 73%
WASTE_TONER_BOX: AT_LEAST_ONE
```

> Catatan penting: **TONER_M tinggal 8% dan `LifeState` = `PREPARATION`** → ini sudah
> masuk kategori kritis. Tray 5 (SMH) `Status=EMPTY`. Ini contoh nyata kenapa
> dashboard + notifikasi otomatis dibutuhkan.

## 2. Tujuan

1. Satu layar untuk memantau **banyak printer** (multi-brand/multi-IP).
2. Melihat **level tinta/toner/drum/waste** + estimasi sisa halaman.
3. **Notifikasi otomatis** saat supply menipis, tray kosong, atau printer error/offline.
4. Riwayat & ekspor untuk keperluan pembelian/refill.

## 3. Arsitektur

```
                 LAN (192.168.10.x)
  ┌──────────┐  ┌──────────┐  ┌──────────┐   (Fuji Xerox: HTTP /home/api/*)
  │ Printer1 │  │ Printer2 │  │ Printer3 │   (Brand lain: SNMP Printer MIB)
  └────┬─────┘  └────┬─────┘  └────┬─────┘
       │             │             │
       └──────┬──────┴──────┬──────┘
              ▼             ▼
     ┌────────────────────────────────┐
     │  COLLECTOR (poll berkala)      │  Python stdlib, tiap 60 detik
     │  - HTTP /home/api (Fuji Xerox) │
     │  - SNMP v1/v2c (fallback)      │
     └──────────────┬─────────────────┘
                    ▼
     ┌────────────────────────────────┐
     │  STORAGE                       │
     │  - state.json (kondisi terkini)│
     │  - history.jsonl (tren)        │
     │  (opsional: SQLite untuk big)  │
     └──────────────┬─────────────────┘
                    ▼
     ┌────────────────────────────────┐
     │  ALERT ENGINE (rules)          │
     │  toner<=20% low, <=10% critical│
     │  tray EMPTY, fault, offline    │
     │  prediksi "habis dalam N hari" │
     │  + dedup / cooldown            │
     └───────┬──────────────┬─────────┘
             ▼              ▼
   ┌──────────────┐  ┌─────────────────────┐
   │ DASHBOARD    │  │ NOTIFIER            │
   │ web, refresh │  │ Telegram / WA / SMTP│
   └──────────────┘  └─────────────────────┘
```

Deploy cukup di **1 PC/mini server/Raspberry Pi** yang selalu nyala dan berada di
jaringan yang sama dengan printer. Windows: jalankan sebagai service (NSSM) atau
Task Scheduler saat startup.

## 4. Cara ambil data per brand

- **Fuji Xerox / Xerox (ApeosPort, Versant, dll)** → HTTP `/home/api/*` (cara tercepat,
  sudah dipakai prototipe ini). Bisa juga lewat SNMP.
- **Brand lain (HP, Canon, Epson, Ricoh, Brother)** → **SNMP v1/v2c**, standar Printer MIB
  (RFC 3805), tidak perlu install apa pun di printer:

| OID | Arti |
|---|---|
| `1.3.6.1.2.1.1.1.0` | `sysDescr` (model) |
| `1.3.6.1.2.1.25.3.2.1.5` | `hrDeviceStatus` (running/warning/down) |
| `1.3.6.1.2.1.43.11.1.1.6` | `prtMarkerSuppliesDescription` (nama supply) |
| `1.3.6.1.2.1.43.11.1.1.8` | `prtMarkerSuppliesMaxCapacity` |
| `1.3.6.1.2.1.43.11.1.1.9` | `prtMarkerSuppliesLevel` (level sekarang) |
| `1.3.6.1.2.1.43.18.1.1.6/.8` | `prtAlertCode` / `prtAlertDescription` (event) |

Level dihitung `level/maxcapacity*100`. Beberapa printer hanya memberi level
"unknown" (-2) atau "some remaining" (-3); ditangani di logika.

## 5. Model data (bentuk yang dinormalisasi)

```json
{
  "id": "fx-c3070-01",
  "name": "Fuji Xerox C3070 - Front Office",
  "ip": "192.168.10.254",
  "model": "C3070_SO",
  "status": "SLEEP",
  "reachable": true,
  "updated": "2026-10-30T13:10:00+07:00",
  "supplies": [
    {"key":"TONER_M","label":"Toner Magenta","kind":"toner","remaining":8,"page_remaining":1680,"state":"OTHER","life_state":"PREPARATION","installed":"2026-06-24"},
    {"key":"DRUM_Y","label":"Drum Yellow","kind":"drum","remaining":12,"page_remaining":18840,"state":"READY","life_state":"READY"}
  ],
  "trays": [{"name":"1_TRAY","size":"A4","remaining":25,"status":"READY"}],
  "faults": [{"code":"093-408","type":"INFORMATION","source":"IOT","at":"2026-10-30T12:56:49Z"}],
  "counters": {"PRINT_TOTAL_IMPRESSION":263194}
}
```

`kind` dipetakan: prefix `TONER_` → toner, `DRUM_` → drum, `WASTE_` → waste box.

## 6. Aturan notifikasi (alert rules)

| Kondisi | Level | Pesan |
|---|---|---|
| Toner remaining ≤ 20% | warning | "Toner Magenta 8% – siapkan pengganti" |
| Toner remaining ≤ 10% **atau** `life_state=PREPARATION` | critical | "TONER_M HABIS – ganti sekarang" |
| `page_remaining` < 1000 | critical | estimasi cetak tersisa sedikit |
| Waste toner box penuh | warning | jadwal penggantian |
| Tray `status=EMPTY` | warning | "Tray 5 kosong" |
| `device-fault-notification` aktif (non-informasi) | critical | kode error 093-xxx |
| Printer tidak merespon > 3x poll | critical | "Printer offline" |
| Prediksi dari tren: habis < 3 hari | warning | "Ganti dalam ~N hari" |

Prinsip anti-spam:
- **Dedup**: notifikasi hanya dikirim saat kondisi **berubah** (naik/turun level) atau
  setelah **cooldown** (mis. 6 jam) — bukan setiap polling.
- Kondisi kembali normal → kirim pesan "resolved".
- Jam tenang (quiet hours) opsional untuk warning non-kritis.

## 7. Dashboard (UI)

- **Kartu per printer**: nama, IP, model, status, badge ONLINE/OFFLINE.
- **Nama supply mengikuti wording printer sendiri** (dari template bahasa device):
  `Drum Cartridge (R1..R4)`, `Waste Toner Container R5`, `Yellow Toner`, dst. —
  dipetakan di `FX_DEFAULT_LABELS` (`collector.py`), bisa dioverride per printer
  lewat `label_map` di `config.json`.
- **Status berwording device**: `OK` (hijau), `Replace Soon` (oranye), `Replace Now` (merah).
- **Bar berwarna** untuk tiap supply: hijau (>50), kuning (20–50), oranye (10–20),
  merah (≤10), plus angka % dan sisa halaman.
- **Panel alert** di atas: daftar printer yang butuh perhatian, terurut tingkat bahaya.
- **Panel peringatan di samping** printer (sidebar, sticky) + **Mode Hapus**:
  peringatan bisa dihapus satu per satu. Peringatan yang dihapus tetap hilang
  **hanya selama kondisinya tidak berubah** — begitu ada trigger baru
  (mis. `warning` → `critical`) atau kondisi hilang lalu muncul lagi, peringatan
  otomatis tampil kembali. Tombol **Kembalikan** untuk memunculkan semua.
- **Riwayat**: grafik penurunan level (dari `history.jsonl`) + tombol ekspor CSV.
- **Filter**: cari nama/IP, tampilkan hanya yang bermasalah.
- Auto-refresh tiap 30 detik.

## 8. Teknologi

- **Collector/Server**: Python 3 standard library saja (tanpa `pip install`) →
  `urllib` + `http.server` + `telepot`-style call via `urllib`. Ringan & portabel.
- **Frontend**: satu file HTML/CSS/JS (tanpa build tool).
- **Notifier**: Telegram Bot API (gratis, paling mudah). Alternatif: WhatsApp
  Business/Fonnte, email SMTP, atau webhook ke Slack/Teams.
- **Storage**: JSONL (mudah) → naik ke SQLite bila data besar/pemakaian jangka panjang.

## 9. Prototipe yang sudah dibuat

```
printer-dashboard/
├─ CONCEPT.md          dokumen ini
├─ config.json         daftar printer + ambang + notifikasi
├─ collector.py        ambil data, normalisasi, evaluasi alert, kirim notif
├─ app.py              web server + refresh berkala
├─ web/index.html      dashboard
└─ data/               state.json, history.jsonl (hasil generate)
```

Cara pakai (lihat `README.md`): isi `config.json`, jalankan collector sekali, lalu
`python app.py` dan buka `http://localhost:8080`.

## 10. Langkah lanjut

1. Daftarkan semua printer (IP/nama) di `config.json`.
2. Aktifkan channel notifikasi (Telegram bot token + chat id).
3. (Opsional) tambahkan modul SNMP untuk printer non-Fuji Xerox.
4. Jalankan sebagai service agar jalan terus, lalu pasang di layar/monitor ruang IT.
