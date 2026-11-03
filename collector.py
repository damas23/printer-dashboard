"""Collector monitoring printer.

Mengambil data supply/status dari printer, menormalkannya, mengevaluasi
aturan notifikasi, lalu menyimpan hasil ke folder data/.

Hanya memakai standard library Python (tanpa pip install).

Jalankan sekali  : py collector.py --once
Jalankan berkala  : py collector.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
NOTIFY_PATH = os.path.join(DATA_DIR, "notify_state.json")
DISMISSED_PATH = os.path.join(DATA_DIR, "dismissed.json")
STOCK_PATH = os.path.join(DATA_DIR, "stock.json")

# Endpoint REST Fuji Xerox (web UI "wui"). GET, tanpa login.
FX_ENDPOINTS = {
    "about": "/home/api/about",
    "supplies": "/home/api/supplies-info",
    "fault": "/home/api/device-fault-notification",
    "trays": "/home/api/paper-tray",
    "counters": "/home/api/billing-counter",
    "display": "/home/api/home-display-model",
}


# --------------------------------------------------------------------------- #
# Utilitas
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def http_get_json(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": "printer-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def supply_kind(key: str) -> str:
    if key.startswith("TONER"):
        return "toner"
    if key.startswith("DRUM"):
        return "drum"
    if key.startswith("WASTE"):
        return "waste"
    if key.startswith("FUSER") or key.startswith("STAPLE"):
        return "parts"
    if key.startswith("FEED_ROLL") or key.startswith("MAINTENANCE_KIT") or key.startswith("DADF"):
        return "parts"
    return "other"


# Penamaan default mengikuti web UI printer sendiri (diambil dari template bahasa
# device): 'Drum Cartridge ({0})' -> R1..R4, 'Waste Toner Container {0}' -> R5,
# 'Yellow/Black Toner', dst.
FX_DEFAULT_LABELS = {
    "TONER_Y": "Yellow Toner",
    "TONER_M": "Magenta Toner",
    "TONER_C": "Cyan Toner",
    "TONER_K": "Black Toner",
    "DRUM_K": "Drum Cartridge (R1)",
    "DRUM_C": "Drum Cartridge (R2)",
    "DRUM_M": "Drum Cartridge (R3)",
    "DRUM_Y": "Drum Cartridge (R4)",
    "WASTE_TONER_BOX": "Waste Toner Container R5",
    # Part/consumable lain (muncul di model seperti C3530)
    "FUSER": "Fusing Unit",
    "FUSER_WEB": "Fusing and Transfer Module",
    "FEED_ROLL1": "Feed Roller 1",
    "FEED_ROLL2": "Feed Roller 2",
    "FEED_ROLL3": "Feed Roller 3",
    "FEED_ROLL4": "Feed Roller 4",
    "FEED_ROLL_TRAY5": "Tray 5 Feed Roller",
    "MAINTENANCE_KIT1": "Maintenance Kit 1",
    "MAINTENANCE_KIT2": "Maintenance Kit 2",
    "DADF_FEED_ROLL": "DADF Feed Roll",
}

# Urutan tampil: toner (paling dipantau) -> drum -> waste.
FX_ORDER = [
    "TONER_Y", "TONER_M", "TONER_C", "TONER_K",
    "DRUM_K", "DRUM_C", "DRUM_M", "DRUM_Y",
    "WASTE_TONER_BOX",
]


def supply_label(key: str, overrides: dict | None = None) -> str:
    if overrides and key in overrides:
        return overrides[key]
    if key in FX_DEFAULT_LABELS:
        return FX_DEFAULT_LABELS[key]
    colors = {"Y": "Yellow", "M": "Magenta", "C": "Cyan", "K": "Black"}
    parts = key.split("_")
    if len(parts) == 2 and parts[1] in colors:
        return f"{parts[0].title()} {colors[parts[1]]}"
    return key.replace("_", " ").title()


def supply_status(state, life_state, remaining) -> tuple:
    """Kembalikan (teks status, level) memakai wording web UI printer."""
    state = (state or "").upper()
    life = (life_state or "").upper()

    if life in ("EMPTY", "DEPLETED", "NEAR_EMPTY") or state in ("EMPTY", "DEPLETED"):
        return "Replace Now", "critical"
    if remaining is not None and remaining <= 10:
        return "Replace Now", "critical"
    if life == "PREPARATION" or state == "OTHER":
        return "Replace Soon", "warning"
    if remaining is not None and remaining <= 20:
        return "Replace Soon", "warning"
    if state == "READY" or life == "READY" or not (state or life):
        return "OK", "ok"
    return (life_state or state or "OK"), "ok"


def supply_sort_key(item: dict):
    key = item.get("key")
    try:
        return (0, FX_ORDER.index(key))
    except ValueError:
        return (1, key or "")


# --------------------------------------------------------------------------- #
# Collector per tipe perangkat
# --------------------------------------------------------------------------- #
def collect_fujixerox_wui(printer: dict, timeout: int) -> dict:
    base = f"http://{printer['ip']}"
    raw: dict = {}
    for key, path in FX_ENDPOINTS.items():
        try:
            raw[key] = http_get_json(base + path, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
            raw[key] = None

    reachable = raw.get("about") is not None
    about = raw.get("about") or {}
    display = raw.get("display") or {}
    supplies_raw = (raw.get("supplies") or {}).get("Supplies", [])

    web_url = f"http://{printer['ip']}/"
    # URL driver diisi manual di config.json ("driver_url"); kalau kosong,
    # pakai URL yang disetel perangkat bila ada.
    driver_url = (
        printer.get("driver_url")
        or display.get("DownloadWindowsDriverUri")
        or display.get("DownloadOtherDriverUri")
        or None
    )

    supplies = []
    overrides = printer.get("label_map", {}) or {}
    for s in supplies_raw:
        key = s.get("Name", "UNKNOWN")
        rem = _to_int(s.get("Remaining"))
        status_text, status_level = supply_status(s.get("State"), s.get("LifeState"), rem)
        supplies.append(
            {
                "key": key,
                "label": supply_label(key, overrides),
                "kind": supply_kind(key),
                "remaining": rem,
                "page_remaining": _page_remaining(s.get("PageRemaining")),
                "state": s.get("State"),
                "life_state": s.get("LifeState"),
                "status_text": status_text,
                "status_level": status_level,
                "installed": (s.get("DateInstalled") or "")[:10] or None,
                "changeable": s.get("ChangeableType"),
            }
        )
    supplies.sort(key=supply_sort_key)

    trays = []
    for t in (raw.get("trays") or {}).get("PaperTrays", []):
        trays.append(
            {
                "name": t.get("NameId") or t.get("LogicalNumTrayType"),
                "size": t.get("MediumSize"),
                "remaining": _to_int(t.get("Remaining")),
                "status": t.get("Status"),
            }
        )

    faults = []
    fault = raw.get("fault") or {}
    for f in fault.get("FailCodes", []):
        faults.append(
            {
                "code": str(f.get("PrimaryChainLink") or "").replace("-", ""),
                "display": f.get("PrimaryChainLink"),
                "type": f.get("Type"),
                "source": f.get("Source"),
                "at": f.get("DateTime"),
            }
        )

    counters = {}
    for c in (raw.get("counters") or {}).get("UsageCounters", []):
        counters[c.get("DomesticName")] = c.get("Count")

    return {
        "id": printer["id"],
        "name": printer.get("name", printer["id"]),
        "ip": printer["ip"],
        "type": printer.get("type"),
        "reachable": reachable,
        "model": about.get("DevFrndlName"),
        "serial": about.get("SerialNumber"),
        "firmware": about.get("SoftwareVersion"),
        "hostname": about.get("HostName"),
        "status": about.get("DeviceStatus"),
        "system_state": fault.get("SystemState"),
        "product": display.get("ExposingProductName"),
        "web_url": web_url,
        "driver_url": driver_url,
        "supplies": supplies,
        "trays": trays,
        "faults": faults,
        "counters": counters,
        "updated": now_iso(),
    }


def collect_snmp_placeholder(printer: dict, timeout: int) -> dict:
    """Placeholder untuk printer non-Fuji Xerox (HP/Canon/Epson/...).

    Implementasi SNMP memerlukan paket pihak ketiga (mis. pysnmp) atau implementasi
    BER/ASN.1 sendiri. Lihat CONCEPT.md bagian 4 untuk daftar OID Printer MIB.
    """
    return {
        "id": printer["id"],
        "name": printer.get("name", printer["id"]),
        "ip": printer["ip"],
        "type": printer.get("type"),
        "reachable": False,
        "model": None,
        "status": "UNSUPPORTED",
        "supplies": [],
        "trays": [],
        "faults": [],
        "counters": {},
        "web_url": f"http://{printer['ip']}/",
        "driver_url": printer.get("driver_url") or None,
        "note": "Tipe 'snmp' belum diimplementasikan pada prototipe ini.",
        "updated": now_iso(),
    }


def collect_printer(printer: dict, timeout: int) -> dict:
    ptype = printer.get("type", "fujixerox_wui")
    if ptype == "fujixerox_wui":
        return collect_fujixerox_wui(printer, timeout)
    return collect_snmp_placeholder(printer, timeout)


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_remaining(value):
    """PageRemaining bisa berupa angka, 'AT_LEAST_ONE', atau lain-lain."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if text.isdigit():
        return int(text)
    return None


# --------------------------------------------------------------------------- #
# Alert engine
# --------------------------------------------------------------------------- #
def evaluate_alerts(dev: dict, thresholds: dict) -> list[dict]:
    alerts: list[dict] = []

    if not dev.get("reachable"):
        alerts.append(
            {
                "key": "offline",
                "level": "critical",
                "message": f"{dev['name']} tidak merespon ({dev['ip']}).",
            }
        )
        return alerts

    for s in dev.get("supplies", []):
        rem = s.get("remaining")
        kind = s.get("kind")
        label = s.get("label")
        if rem is None:
            continue

        if kind == "toner":
            if rem <= thresholds.get("toner_critical", 10) or s.get("life_state") == "PREPARATION":
                alerts.append(
                    {
                        "key": f"supply:{s['key']}",
                        "level": "critical",
                        "message": f"{dev['name']}: {label} kritis ({rem}%) - ganti sekarang.",
                    }
                )
            elif rem <= thresholds.get("toner_low", 20):
                alerts.append(
                    {
                        "key": f"supply:{s['key']}",
                        "level": "warning",
                        "message": f"{dev['name']}: {label} menipis ({rem}%) - siapkan pengganti.",
                    }
                )
        elif kind == "drum":
            if rem <= thresholds.get("drum_low", 15):
                alerts.append(
                    {
                        "key": f"supply:{s['key']}",
                        "level": "warning",
                        "message": f"{dev['name']}: {label} menipis ({rem}%).",
                    }
                )
        elif kind == "waste":
            if s.get("state") not in (None, "READY"):
                alerts.append(
                    {
                        "key": f"supply:{s['key']}",
                        "level": "warning",
                        "message": f"{dev['name']}: waste toner box perlu perhatian.",
                    }
                )

        pr = s.get("page_remaining")
        if pr is not None and pr < thresholds.get("page_remaining_critical", 1000):
            alerts.append(
                {
                    "key": f"pages:{s['key']}",
                    "level": "critical",
                    "message": f"{dev['name']}: {label} sisa ~{pr} halaman.",
                }
            )

    for t in dev.get("trays", []):
        if t.get("status") == "EMPTY":
            alerts.append(
                {
                    "key": f"tray:{t['name']}",
                    "level": "warning",
                    "message": f"{dev['name']}: tray {t['name']} kosong ({t.get('size')}).",
                }
            )

    for f in dev.get("faults", []):
        if (f.get("type") or "").upper() not in ("INFORMATION",):
            alerts.append(
                {
                    "key": f"fault:{f.get('display')}",
                    "level": "critical",
                    "message": f"{dev['name']}: error {f.get('display')} ({f.get('type')}).",
                }
            )

    return alerts


# --------------------------------------------------------------------------- #
# Notifier
# --------------------------------------------------------------------------- #
def send_telegram(cfg: dict, text: str) -> bool:
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"[notify] gagal kirim Telegram: {exc}", file=sys.stderr)
        return False


def dispatch_notifications(alerts: list[dict], notify_state: dict, cfg: dict) -> dict:
    """Kirim notifikasi hanya untuk alert baru / setelah cooldown (anti-spam)."""
    cooldown = int(cfg.get("cooldown_minutes", 360)) * 60
    tg = cfg.get("telegram", {})
    now = time.time()

    active_keys = set()
    messages = []
    for a in alerts:
        active_keys.add(a["key"])
        prev = notify_state.get(a["key"], {})
        last = prev.get("last_sent", 0)
        changed = prev.get("level") != a["level"]
        if changed or (now - last) >= cooldown:
            messages.append(a["message"])
            notify_state[a["key"]] = {"last_sent": now, "level": a["level"], "message": a["message"]}

    # alert yang sudah selesai
    for key in list(notify_state.keys()):
        if key not in active_keys:
            notify_state.pop(key, None)

    if messages and tg.get("enabled"):
        send_telegram(tg, "\U0001F5A8\uFE0F Printer Alert\n\n" + "\n".join(f"- {m}" for m in messages))
    return notify_state


# --------------------------------------------------------------------------- #
# Dismiss (mode hapus) + re-trigger
# --------------------------------------------------------------------------- #
def alert_fingerprint(alert: dict) -> str:
    """Identitas kondisi. Bila berubah (mis. warning -> critical) dianggap
    'trigger baru', sehingga alert yang sudah dihapus muncul kembali."""
    return str(alert.get("level") or "")


def apply_dismissals(alerts: list, dismissed: dict) -> None:
    """Tandai alert yang masih dihapus; buang dismissal bila kondisi hilang/berubah."""
    active = {a["key"]: a for a in alerts}
    for key in list(dismissed.keys()):
        rec = dismissed.get(key) or {}
        a = active.get(key)
        if a is None or rec.get("fp") != alert_fingerprint(a):
            dismissed.pop(key, None)  # kondisi hilang / berubah -> trigger baru
    for a in alerts:
        a["dismissed"] = a["key"] in dismissed


def dismiss_alert(key: str) -> dict:
    state = load_json(STATE_PATH, {"alerts": []})
    dismissed = load_json(DISMISSED_PATH, {})
    target = next((a for a in state.get("alerts", []) if a.get("key") == key), None)
    dismissed[key] = {"fp": alert_fingerprint(target or {}), "at": now_iso()}
    save_json(DISMISSED_PATH, dismissed)
    for a in state.get("alerts", []):
        if a.get("key") == key:
            a["dismissed"] = True
    save_json(STATE_PATH, state)
    return state


def restore_alert(key=None) -> dict:
    dismissed = load_json(DISMISSED_PATH, {})
    if key is None:
        dismissed = {}
    else:
        dismissed.pop(key, None)
    save_json(DISMISSED_PATH, dismissed)
    state = load_json(STATE_PATH, {"alerts": []})
    for a in state.get("alerts", []):
        a["dismissed"] = a.get("key") in dismissed
    save_json(STATE_PATH, state)
    return state


# --------------------------------------------------------------------------- #
# Stok spare part (gudang)
# --------------------------------------------------------------------------- #
STOCK_FIELDS = ("part", "code", "model", "location")


def _clean_stock_item(raw) -> dict | None:
    """Normalisasi satu baris stok; kembalikan None jika bahan kosong."""
    if not isinstance(raw, dict):
        return None
    item = {f: str(raw.get(f) or "").strip() for f in STOCK_FIELDS}
    if not item["part"]:
        return None  # baris tanpa nama bahan diabaikan
    for f in ("qty", "min"):
        try:
            item[f] = int(raw.get(f) or 0)
        except (TypeError, ValueError):
            item[f] = 0
    return item


def save_stock(data) -> dict:
    """Simpan seluruh daftar stok ke data/stock.json."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {"ok": False, "error": "Format tidak valid: 'items' harus berupa list."}
    items = [it for it in (_clean_stock_item(r) for r in data["items"]) if it]
    payload = {"updated": datetime.now().strftime("%Y-%m-%d"), "items": items}
    save_json(STOCK_PATH, payload)
    return {"ok": True, **payload}


# --------------------------------------------------------------------------- #
# Orkestrasi
# --------------------------------------------------------------------------- #
def run_once(config: dict) -> dict:
    timeout = int(config.get("http_timeout_seconds", 10))
    thresholds = config.get("thresholds", {})
    notify_cfg = config.get("notifications", {})
    notify_state = load_json(NOTIFY_PATH, {})

    state = {"updated": now_iso(), "printers": [], "alerts": []}
    for printer in config.get("printers", []):
        dev = collect_printer(printer, timeout)
        alerts = evaluate_alerts(dev, thresholds)
        dev["alerts"] = alerts
        state["printers"].append(dev)
        state["alerts"].extend(alerts)

    dismissed = load_json(DISMISSED_PATH, {})
    apply_dismissals(state["alerts"], dismissed)
    save_json(DISMISSED_PATH, dismissed)

    visible = [a for a in state["alerts"] if not a.get("dismissed")]
    notify_state = dispatch_notifications(visible, notify_state, notify_cfg)
    save_json(NOTIFY_PATH, notify_state)
    save_json(STATE_PATH, state)

    # riwayat untuk tren (append-only)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as fh:
        for dev in state["printers"]:
            fh.write(
                json.dumps(
                    {
                        "ts": state["updated"],
                        "id": dev["id"],
                        "supplies": [
                            {"key": s["key"], "remaining": s["remaining"]} for s in dev["supplies"]
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Printer supply collector")
    parser.add_argument("--once", action="store_true", help="jalankan satu kali lalu keluar")
    args = parser.parse_args()

    config = load_json(CONFIG_PATH, None)
    if not config:
        print(f"Config tidak ditemukan/tidak valid: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    if args.once:
        state = run_once(config)
        for dev in state["printers"]:
            status = "OK" if dev["reachable"] else "OFFLINE"
            print(f"[{status}] {dev['name']} ({dev['ip']}) model={dev.get('model')} status={dev.get('status')}")
            for s in dev["supplies"]:
                pct = f"{s['remaining']}%" if s["remaining"] is not None else "-"
                print(f"    - {s['label']:<24} {s['status_text']:<13} {pct:>5}  sisa: {s['page_remaining']}")
        visible = [a for a in state["alerts"] if not a.get("dismissed")]
        hidden = len(state["alerts"]) - len(visible)
        print(f"\nAlert aktif: {len(visible)}" + (f" (+{hidden} dihapus)" if hidden else ""))
        for a in visible:
            print(f"    [{a['level']}] {a['message']}")
        return

    interval = int(config.get("poll_interval_seconds", 300))
    print(f"Collector jalan tiap {interval} detik. Tekan Ctrl+C untuk berhenti.")
    while True:
        try:
            state = run_once(config)
            print(f"[{now_iso()}] poll selesai, {len(state['alerts'])} alert")
        except Exception as exc:  # noqa: BLE001 - collector harus tetap hidup
            print(f"[{now_iso()}] error: {exc}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    main()
