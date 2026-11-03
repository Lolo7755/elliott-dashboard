"""
Telegram-Nachricht nach jedem Lauf.

Benötigt zwei GitHub-Secrets (Settings -> Secrets and variables -> Actions):
  TELEGRAM_TOKEN    = Token deines Bots von @BotFather
  TELEGRAM_CHAT_ID  = deine Chat-ID (z. B. über @userinfobot)
Fehlen die Secrets, wird einfach nichts gesendet.
"""
from __future__ import annotations

import html
import json
import os
import urllib.request

KAUF = ("In Zone", "In Zone (unten)", "Nachkaufbereich")
VERKAUF = ("Ziel 1 erreicht", "Ziel 2 erreicht")
DOT = {"gruen": "🟢", "orange": "🟠", "rot": "🔴"}


def _line(r: dict) -> str:
    cur = r.get("currency") or ""
    kurs = f"{r['kurs']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{DOT.get(r['ampel'], '')} <b>{html.escape(r['name'])}</b> {kurs} {cur}: {html.escape(r['signal'])}"


def build_message(results: list[dict], gesamt: dict, url: str | None) -> str:
    changed = [r for r in results if r.get("status_vorher") and r["status"] != r["status_vorher"]]
    kauf = [r for r in changed if r["status"] in KAUF]
    verkauf = [r for r in changed if r["status"] in VERKAUF]
    gekippt = [r for r in changed if r["status"] == "Abwärtstrend"]
    termine = sorted(
        (r for r in results
         if r["status"] in KAUF and (r.get("termine") or {}).get("earnings_in_tagen") is not None
         and r["termine"]["earnings_in_tagen"] <= 7),
        key=lambda r: r["termine"]["earnings_in_tagen"])

    parts = ["<b>📈 Elliott-Dashboard – Abendupdate</b>"]
    if kauf:
        parts.append("\n<b>Neu im Kaufbereich</b>\n" + "\n".join(_line(r) for r in kauf))
    if verkauf:
        parts.append("\n<b>Ziel erreicht – Teilverkauf</b>\n" + "\n".join(_line(r) for r in verkauf))
    if gekippt:
        parts.append("\n<b>Szenario gekippt</b>\n" + "\n".join(_line(r) for r in gekippt))
    if termine:
        parts.append("\n<b>⚠️ Earnings bald (Aktie in Zone)</b>\n" + "\n".join(
            f"• {html.escape(r['name'])}: {r['termine']['earnings']} (in {r['termine']['earnings_in_tagen']} Tagen)"
            for r in termine))
    if not (kauf or verkauf or gekippt):
        parts.append("\nKeine neuen Signale heute.")
    in_zone = sum(r["status"] in KAUF for r in results)
    q = gesamt.get("quote_pct")
    parts.append(f"\n{in_zone} Aktien aktuell im Kaufbereich · Trefferquote {q if q is not None else '–'} %")
    if url:
        parts.append(f'<a href="{url}">Dashboard öffnen</a>')
    msg = "\n".join(parts)
    return msg if len(msg) < 4000 else msg[:3990] + "\n…"


def send(results: list[dict], gesamt: dict) -> None:
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram: keine Secrets gesetzt – keine Nachricht gesendet")
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    url = None
    if "/" in repo:
        owner, name = repo.split("/", 1)
        url = f"https://{owner.lower()}.github.io/{name}/"
    body = json.dumps({"chat_id": chat, "text": build_message(results, gesamt, url),
                       "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("Telegram:", r.status)
    except Exception as e:  # Benachrichtigung darf den Lauf nie abbrechen
        print("Telegram-Fehler:", e)
