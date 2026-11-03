# 🖨️ Printer Dashboard

A lightweight, **zero-dependency** dashboard to monitor toner / drum / waste-toner
levels across multiple **Fuji Xerox (ApeosPort)** printers on your LAN — at a glance,
in a single web page.

Built with **Python 3 standard library only** (no `pip install` required).
Data is pulled straight from the printers' built-in REST API (`/home/api/*`) — no SNMP,
no login, no agents on the printers.

> **Status:** working prototype, actively used with 9 printers.

---

## ✨ Features

- **Multi-printer overview** — one card per printer with model, IP, status badge, and
  live supply levels.
- **Percentage-only display** — clean, uniform cards (no page-remaining text).
- **Device-accurate labels & status** — names and states match the printer's own wording
  (`OK` / `Replace Soon` / `Replace Now`), including waste toner.
- **Model-aware supply labels** — C3070/C3570 use `Drum Cartridge (R1..R4)` + `Waste Toner
  Container R5`; C3530/C4030 use `Drum Cartridge (K/C/M/Y)` + `Waste Toner Container`.
- **Quick actions per printer** — **Access Page** (opens the printer's web UI) and
  **Download Driver** (configurable URL, falls back to the device-reported URI).
- **Spare-parts stock panel** — warehouse inventory with **inline editing**
  (add / edit / delete / save), search, live stats, and automatic status coloring.
- **Two themes** — a light/clean theme at `/` and a dark/modern theme at `/v1.html`.
- **Automatic background polling** — refreshes every 60 seconds (configurable).
- **Alert engine** (backend) — rule-based alerts with dedup + cooldown, optional
  **Telegram** notifications.
- **History log** — every poll appended to `data/history.jsonl` for trend analysis.
- **English UI** across both themes.

---

## 🚀 Requirements

- **Python 3.10+** (uses modern type hints like `dict | None`).
- Network access from the host to the printers (same LAN / routable subnet).
- A modern browser.

No third-party packages. Everything runs on `urllib`, `http.server`, `json`, `threading`.

---

## ⚡ Quick Start

```powershell
# 1. Clone
git clone https://github.com/azizovers-idn/printer-dashboard.git
cd printer-dashboard

# 2. Edit config.json and add your printers (see Configuration below)

# 3. (Optional) Test a single collection run
py collector.py --once

# 4. Run the dashboard (background collector starts automatically)
py app.py
```

Then open **<http://localhost:8080>**.

- Light theme → <http://localhost:8080/>
- Dark theme → <http://localhost:8080/v1.html>

---

## 📁 Project Structure

```
printer-dashboard/
├─ app.py              # HTTP server + periodic collector loop (port 8080)
├─ collector.py        # Fetch → normalize → evaluate alerts → notify, stock I/O
├─ config.json         # Printers, thresholds, notification settings
├─ CONCEPT.md          # Full architecture & design notes
├─ web/
│  ├─ index.html       # Light / clean theme  (served at /)
│  └─ v1.html          # Dark / modern theme  (served at /v1.html)
├─ data/               # Runtime data (git-ignored)
│  ├─ state.json       #   current snapshot of all printers
│  ├─ history.jsonl    #   append-only trend log
│  ├─ stock.json       #   spare-parts inventory
│  ├─ dismissed.json   #   dismissed alerts
│  └─ notify_state.json#   notification dedup/cooldown state
└─ .gitignore
```

---

## ⚙️ Configuration (`config.json`)

```jsonc
{
  "poll_interval_seconds": 60,      // how often to poll printers
  "http_timeout_seconds": 10,       // per-request timeout
  "printers": [
    {
      "id": "fx-c3070-01",          // unique key
      "name": "Fuji Xerox C3070 - Site Office",
      "ip": "192.168.10.254",
      "type": "fujixerox_wui",      // "fujixerox_wui" (REST) or "snmp" (fallback)
      "driver_url": "",             // optional: your own download link
      "label_map": {                // optional: override supply labels per printer
        "DRUM_K": "Drum Cartridge (K)",
        "DRUM_M": "Drum Cartridge (M)",
        "DRUM_C": "Drum Cartridge (C)",
        "DRUM_Y": "Drum Cartridge (Y)",
        "WASTE_TONER_BOX": "Waste Toner Container"
      }
    }
  ],
  "thresholds": {
    "toner_low": 20,
    "toner_critical": 10,
    "drum_low": 15,
    "page_remaining_critical": 1000
  },
  "notifications": {
    "cooldown_minutes": 360,
    "telegram": { "enabled": false, "bot_token": "", "chat_id": "" }
  }
}
```

> 💡 **`config.json` in this repo contains example private-LAN IPs.** Replace them with
> your own printers before running. Private ranges (`10.x`, `192.168.x`) are not
> reachable from the internet, but review before publishing your own fork.

`config.json`, `app.py` and `collector.py` changes require a **server restart**.
HTML edits only need a browser refresh (**Ctrl+F5**), since static files are read per request.

---

## 🗂️ Supply Labels & Model Support

Labels are reconstructed to match the printer's own UI wording:

| Model family | Drum labels | Waste toner |
|---|---|---|
| C3070 / C3570 | `Drum Cartridge (R1..R4)` | `Waste Toner Container R5` |
| C3530 / C4030 | `Drum Cartridge (K/C/M/Y)` | `Waste Toner Container` |

Additional consumables mapped automatically (when reported by the device):
`Fusing Unit`, `Feed Roller 1–4`, `Tray 5 Feed Roller`, `Maintenance Kit 1/2`,
`DADF Feed Roll`.

Status wording comes straight from the device: **`OK`** (green) /
**`Replace Soon`** (orange) / **`Replace Now`** (red).

> ⚠️ **Waste toner** reports only a state (no `Remaining` %) on these models — that is a
> hardware limitation, so the card shows the label + status only.

---

## 📦 Spare-Parts Stock

Click **📦 Spare Parts Stock** in the header to open the inventory modal.

- Edit any row inline, **＋ Add Item**, or delete a row — then click **💾 Save**
  (POSTs the full list to the backend).
- Search by part / model / location.
- Status is computed from quantity with a fixed threshold (`STOCK_LOW_THRESHOLD = 2`
  in `collector.py`):

  | Quantity | Status | Color |
  |---|---|---|
  | `0` | Out of Stock | 🔴 red |
  | `1–2` | Low | 🟠 orange |
  | `≥ 3` | In Stock | 🟢 green |

Rows are sorted **Out of Stock → Low → In Stock**.
Data is stored in `data/stock.json` and persists without editing files by hand.

---

## 🔌 REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` , `/index.html` | Light theme dashboard |
| `GET` | `/v1.html` | Dark theme dashboard |
| `GET` | `/api/state` | Current snapshot of all printers |
| `GET` | `/api/collect` | Force an immediate collection run |
| `GET` | `/api/stock` | Current spare-parts inventory |
| `POST` | `/api/stock` | Save inventory — body `{ "items": [ ... ] }` |
| `POST` | `/api/dismiss?key=...` | Dismiss a specific alert |
| `POST` | `/api/restore?key=...` | Restore one alert (omit `key` for all) |

Sample supply object inside `/api/state`:

```json
{
  "key": "TONER_M",
  "label": "Magenta Toner",
  "kind": "toner",
  "remaining": 8,
  "state": "PREPARATION",
  "life_state": "PREPARATION",
  "status_text": "Replace Now",
  "status_level": "critical",
  "installed": true,
  "changeable": true
}
```

---

## 🚨 Alert Rules

| Condition | Level |
|---|---|
| Toner remaining ≤ `toner_low` (20%) | warning |
| Toner remaining ≤ `toner_critical` (10%) or `LifeState = PREPARATION` | critical |
| Drum remaining ≤ `drum_low` (15%) | warning |
| `page_remaining` < `page_remaining_critical` (1000) | critical |
| Waste toner box full | warning |
| Active device fault (non-informational) | critical |
| Printer unreachable (> 3 polls) | critical |

**Anti-spam:** alerts fire only when the condition **changes level** (e.g. warning →
critical) or after a **cooldown** (default 6 hours). Resolved conditions send a
"resolved" message. Dismissed alerts re-appear if the fingerprint (level) changes.

---

## 📨 Telegram Notifications (optional)

1. Create a bot via [@BotFather](https://t.me/BotFather) → get the `bot_token`.
2. Send a message to your bot, then get the `chat_id` (e.g. via `getUpdates`).
3. Update `config.json`:

   ```json
   "telegram": { "enabled": true, "bot_token": "123456:ABC-DEF", "chat_id": "123456789" }
   ```

4. Restart the server.

Notifications are throttled by `cooldown_minutes` to prevent spam.

---

## 🔁 Running Continuously (Windows)

**Option A — Task Scheduler** (runs at startup):

```powershell
schtasks /create /tn "PrinterDashboard" ^
  /tr "py D:\printer-dashboard\app.py" ^
  /sc onstart /rl highest /f
```

**Option B — NSSM** (install as a Windows Service) or run on an always-on
mini-PC / Raspberry Pi located on the same LAN as the printers.

---

## 🧩 Adding Non-Fuji-Xerox Printers (SNMP)

The architecture supports SNMP (Printer MIB, RFC 3805) as a fallback:

1. Set `"type": "snmp"` for the printer in `config.json`.
2. Implement `collect_snmp_placeholder()` in `collector.py` using the OIDs in
   `CONCEPT.md` §4 (e.g. `prtMarkerSuppliesLevel` / `MaxCapacity`).

The most practical approach is `pip install pysnmp` (breaks the "stdlib-only" rule, but
only for this optional module).

---

## 🔒 Security Notes

- Printer REST APIs are accessed **without authentication** — intended for a trusted LAN.
- The dashboard itself has **no authentication**; bind it to `localhost` or a trusted
  network segment (see `HOST` in `app.py`).
- Don't expose port `8080` to the internet as-is.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Card shows **OFFLINE** | Printer IP changed, powered off, or wrong subnet. Ping it from the host. |
| `state.json` stale | Background loop not running — restart `py app.py`. |
| Supply shows no % | Some consumables (e.g. waste toner) report state only — hardware limitation. |
| Edited HTML not showing | Hard refresh: **Ctrl+F5** (static files are re-read per request). |
| Changes to `config.json` ignored | Restart the server (config is read at startup). |

Test a single run without the server:
```powershell
py collector.py --once
```

---

## 🗺️ Roadmap

- [ ] SNMP module for non-Fuji-Xerox printers
- [ ] Re-enable the alerts panel / notifications in the UI
- [ ] Trend charts from `history.jsonl` + CSV export
- [ ] Optional dashboard authentication

---

## 📄 License

No license file yet — add one (e.g. MIT) if you plan to reuse or distribute this project.
