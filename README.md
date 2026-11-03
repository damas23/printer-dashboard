# Printer Dashboard

Dashboard monitoring supply (toner/drum/waste) + notifikasi untuk banyak printer.

Prototipe ini **tanpa dependensi** — hanya Python 3 standard library.

## Isi

| File | Fungsi |
|---|---|
| `CONCEPT.md` | Konsep & arsitektur lengkap |
| `config.json` | Daftar printer, ambang batas, konfigurasi notifikasi |
| `collector.py` | Ambil data → normalisasi → evaluasi alert → (opsional) kirim notifikasi |
| `app.py` | Web server dashboard + collector berkala |
| `web/index.html` | Tampilan dashboard |
| `data/` | `state.json`, `history.jsonl` (hasil otomatis) |

## Cara pakai

1. **Isi daftar printer** di `config.json` (`id`, `name`, `ip`, `type`).
   Saat ini berisi contoh: Fuji Xerox C3070 di `192.168.10.254`.

2. **Tes ambil data sekali:**
   ```powershell
   py collector.py --once
   ```

3. **Jalankan dashboard** (collector otomatis jalan tiap 60 detik):
   ```powershell
   py app.py
   ```
   Buka <http://localhost:8080>

Di halaman dashboard:
- **Panel Peringatan** ada di samping kanan, sejajar dengan kartu printer.
- Tombol **Mode Hapus** (kanan atas) → memunculkan tombol ✕ pada tiap peringatan
  untuk menghapusnya. Peringatan yang dihapus akan **muncul lagi** kalau kondisinya
  berubah (trigger baru) atau setelah hilang lalu terulang.
- Tombol **Kembalikan** memunculkan lagi semua peringatan yang dihapus.

## Notifikasi Telegram

1. Buat bot via [@BotFather](https://t.me/BotFather) → dapat `bot_token`.
2. Chat bot Anda, lalu ambil `chat_id` (mis. via `getUpdates`).
3. Di `config.json`:
   ```json
   "telegram": { "enabled": true, "bot_token": "123:ABC", "chat_id": "456" }
   ```
Notifikasi hanya dikirim saat kondisi berubah atau lewat cooldown (default 6 jam)
untuk mencegah spam.

## Menjalankan terus-menerus (Windows)

Opsi termudah tanpa install apa pun — **Task Scheduler**:

```powershell
schtasks /create /tn "PrinterDashboard" /tr "py C:\Users\MuhammadAziz\printer-dashboard\app.py" ^
  /sc onstart /rl highest /f
```

Alternatif: NSSM (jalankan sebagai Windows Service) atau simpan di mini PC/Raspberry Pi.

## Menambah printer non-Fuji Xerox

Set `type` menjadi `snmp` di `config.json` lalu implementasikan pembacaan SNMP di
`collect_snmp_placeholder()` (`collector.py`) — daftar OID Printer MIB ada di
`CONCEPT.md` bagian 4. Cara paling praktis: `pip install pysnmp`.
