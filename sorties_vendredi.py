#!/usr/bin/env python3
"""
🎸 SORTIES DU VENDREDI
Script à lancer avec Claude Code ou via cron chaque vendredi.

Usage :
  python sorties_vendredi.py          → scan + email + sauvegarde JSON
  python sorties_vendredi.py --html   → génère aussi une page web locale
  python sorties_vendredi.py --test   → test sans envoyer d'email

Prérequis :
  pip install anthropic requests

Variables d'environnement à définir :
  ANTHROPIC_API_KEY   → ta clé API Anthropic
  GMAIL_USER          → ton adresse Gmail (expéditeur)
  GMAIL_PASSWORD      → mot de passe d'application Gmail (pas ton vrai mdp)
                        → Génère-le sur : myaccount.google.com/apppasswords
"""

import os
import json
import sys
import smtplib
import argparse
import requests
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import anthropic

# ── CONFIGURATION ────────────────────────────────────────────
RECIPIENT_EMAIL  = "ton@email.com"       # ← ton adresse de réception
HISTORY_FILE     = Path("historique.json")
HTML_FILE        = Path("sorties.html")
MAX_HISTORY      = 6                     # nombre de vendredis conservés
MIN_SCORE        = 65                    # score minimum pour inclure une sortie
MAX_RELEASES     = 8                     # max sorties par semaine

# ── PROFIL MUSICAL ───────────────────────────────────────────
MUSIC_PROFILE = """Tu es un expert en musique indie/post-punk britannique et américain.
Analyse les sorties musicales de la semaine indiquée et sélectionne uniquement
celles qui correspondent à ce profil.

PROFIL :
- Guitares très en avant, sèches, directes, tranchantes
- Production mordante — ni trop lisse, ni trop lo-fi
- Tempo rapide et énergique, morceaux dynamiques
- Sweet spot "Is This It" des Strokes
- Groupes de référence : The Strokes, Interpol, The Killers, Bloc Party, Editors,
  Two Door Cinema Club, The Vaccines, Sunflower Bean, Spoon, Foster the People,
  Arctic Monkeys, Vampire Weekend, Cage The Elephant

EXCLURE absolument :
- Trop lo-fi/punk crasseux (style FIDLAR)
- Trop atmosphérique/lent (style Kaleo)
- Trop monotone/répétitif (style Mac DeMarco)
- Trop vintage/blues rock (style Radio Moscow)
- Trop sombre/gothique (style White Lies)

Réponds UNIQUEMENT en JSON valide (sans markdown) :
{{"releases":[{{"artist":"Nom","title":"Titre","type":"album|ep|single","score":85,"why":"Explication 1-2 phrases"}}]}}

Score = compatibilité avec le profil (1-100).
N'inclure que score >= {min_score}. Maximum {max_releases} sorties. Sois sélectif.
"""

# ── DATES ────────────────────────────────────────────────────
def get_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

def get_last_friday(d: date = None) -> date:
    d = d or date.today()
    # Vendredi le plus récent <= aujourd'hui
    days_since_friday = (d.weekday() + 3) % 7  # lundi=0, vendredi=4
    return d - timedelta(days=days_since_friday)

def friday_key(friday: date) -> str:
    return friday.isoformat()

def fmt_date(d: date) -> str:
    months = ["janvier","février","mars","avril","mai","juin",
              "juillet","août","septembre","octobre","novembre","décembre"]
    return f"{d.day} {months[d.month-1]} {d.year}"

# ── DEEZER ───────────────────────────────────────────────────
def get_deezer_link(artist: str, title: str) -> str | None:
    try:
        q = f"{artist} {title}"
        r = requests.get("https://api.deezer.com/search", params={"q": q, "limit": 1}, timeout=5)
        data = r.json()
        if data.get("data"):
            track = data["data"][0]
            album_id = track.get("album", {}).get("id")
            if album_id:
                return f"https://www.deezer.com/album/{album_id}"
            return f"https://www.deezer.com/track/{track['id']}"
    except Exception as e:
        print(f"  ⚠ Deezer erreur pour [{artist}]: {e}")
    return None

# ── API ANTHROPIC ─────────────────────────────────────────────
def fetch_releases(friday: date) -> list[dict]:
    monday = get_monday(friday)
    prompt = (
        MUSIC_PROFILE.format(min_score=MIN_SCORE, max_releases=MAX_RELEASES)
        + f"\n\nCherche les sorties musicales de la semaine du {fmt_date(monday)} au {fmt_date(friday)}."
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print(f"  → Appel API Anthropic (web search)...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )

    # Extraire le texte JSON de la réponse
    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    # Parser le JSON
    import re
    clean = re.sub(r"```json|```", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        raise ValueError("Pas de JSON dans la réponse Anthropic")

    releases = json.loads(match.group(0)).get("releases", [])
    releases.sort(key=lambda r: r["score"], reverse=True)

    print(f"  ✅ {len(releases)} sorties trouvées — recherche des liens Deezer...")

    for r in releases:
        r["deezer_url"] = get_deezer_link(r["artist"], r["title"])
        print(f"     {'✓' if r['deezer_url'] else '✗'} {r['artist']} — {r['title']}")

    return releases

# ── HISTORIQUE JSON ───────────────────────────────────────────
def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}

def save_history(history: dict):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))

def get_last_n_fridays(n: int = 6) -> list[date]:
    fridays = []
    friday = get_last_friday()
    for _ in range(n):
        fridays.append(friday)
        friday -= timedelta(weeks=1)
    return fridays

# ── EMAIL HTML ────────────────────────────────────────────────
def score_color(score: int) -> str:
    if score >= 80: return "#e8ff47"
    if score >= 65: return "#ffa500"
    return "#ff6450"

def type_label(t: str) -> str:
    return {"album": "🎵 Album", "ep": "💿 EP", "single": "🎤 Single"}.get(t, t)

def build_week_html(friday: date, releases: list[dict]) -> str:
    if not releases:
        return "<p style='color:#555;font-size:13px;'>Aucune sortie compatible cette semaine.</p>"

    cards = ""
    for r in releases:
        sc = score_color(r["score"])
        deezer_btn = (
            f'<a href="{r["deezer_url"]}" style="font-family:monospace;font-size:10px;color:#a238ff;'
            f'text-decoration:none;border:1px solid #a238ff;padding:4px 12px;border-radius:3px;'
            f'text-transform:uppercase;letter-spacing:1px;display:inline-block;">▶ Deezer</a>'
            if r.get("deezer_url") else ""
        )
        cards += f"""
        <tr><td style="padding:14px 0;border-bottom:1px solid #1e1e1e;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td width="48" valign="top">
              <div style="width:40px;height:40px;border-radius:50%;background:{sc}18;
                border:2px solid {sc};text-align:center;line-height:40px;
                font-family:monospace;font-size:14px;font-weight:bold;color:{sc};">{r["score"]}</div>
            </td>
            <td valign="top" style="padding-left:12px;">
              <div style="font-family:monospace;font-size:10px;color:#e8ff47;
                letter-spacing:2px;text-transform:uppercase;margin-bottom:3px;">{r["artist"]}</div>
              <div style="font-size:15px;font-weight:bold;color:#f0f0f0;margin-bottom:6px;">{r["title"]}</div>
              <div style="margin-bottom:8px;">
                <span style="font-family:monospace;font-size:9px;background:#1e1e1e;
                  color:#777;padding:2px 7px;border-radius:3px;">{type_label(r["type"])}</span>
              </div>
              <div style="font-size:12px;color:#888;line-height:1.6;font-style:italic;margin-bottom:10px;">{r["why"]}</div>
              {deezer_btn}
            </td>
          </tr></table>
        </td></tr>"""

    monday = get_monday(friday)
    return f"""
    <div style="margin-bottom:4px;">
      <span style="font-family:monospace;font-size:10px;color:#555;
        border:1px solid #2a2a2a;padding:3px 10px;border-radius:3px;">
        Semaine du {fmt_date(monday)} au {fmt_date(friday)}
      </span>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0">{cards}</table>"""

def build_email_html(friday: date, releases: list[dict]) -> str:
    week_html = build_week_html(friday, releases)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0e0e0e;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0e0e0e;">
<tr><td align="center" style="padding:40px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
  <tr><td style="padding-bottom:24px;border-bottom:2px solid #e8ff47;">
    <div style="font-family:monospace;font-size:10px;color:#e8ff47;letter-spacing:3px;
      text-transform:uppercase;margin-bottom:8px;">Radar musical automatisé</div>
    <div style="font-family:Impact,Arial,sans-serif;font-size:48px;color:#f0f0f0;
      letter-spacing:2px;line-height:1;margin-bottom:10px;">
      SORTIES<br><span style="color:#e8ff47;">DU VENDREDI</span>
    </div>
  </td></tr>
  <tr><td style="padding:18px 0;">{week_html}</td></tr>
  <tr><td style="padding-top:24px;border-top:1px solid #1e1e1e;text-align:center;">
    <div style="font-family:monospace;font-size:10px;color:#333;letter-spacing:1px;text-transform:uppercase;">
      The Strokes · Bloc Party · Two Door Cinema Club · The Vaccines
    </div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

# ── PAGE WEB LOCALE ───────────────────────────────────────────
def build_web_page(history: dict, fridays: list[date]) -> str:
    weeks_html = ""
    for friday in fridays:
        key = friday_key(friday)
        if key not in history:
            continue
        releases = history[key]
        is_current = (friday == get_last_friday())
        cur_style = "color:#e8ff47;" if is_current else "color:#f0f0f0;"
        badge = '<span style="font-size:10px;padding:2px 8px;border-radius:100px;background:rgba(232,255,71,.08);color:#e8ff47;border:1px solid rgba(232,255,71,.2);margin-left:10px;font-family:monospace;text-transform:uppercase;letter-spacing:.05em;">Cette semaine</span>' if is_current else ""
        week_content = build_week_html(friday, releases)
        weeks_html += f"""
        <div style="margin-bottom:40px;">
          <div style="display:flex;align-items:center;margin-bottom:4px;">
            <div style="font-family:Impact,Arial,sans-serif;font-size:22px;letter-spacing:.04em;{cur_style}">
              Vendredi {fmt_date(friday)}
            </div>{badge}
          </div>
          <div style="height:1px;background:linear-gradient(90deg,#2a2a2a,transparent);margin:8px 0 14px;"></div>
          {week_content}
        </div>"""

    return f"""<!DOCTYPE html><html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sorties du Vendredi</title>
</head>
<body style="margin:0;padding:28px 20px 60px;background:#0e0e0e;color:#f0f0f0;font-family:Arial,sans-serif;">
<div style="max-width:780px;margin:0 auto;">
  <div style="padding-bottom:22px;border-bottom:1px solid #2a2a2a;margin-bottom:32px;">
    <div style="font-family:monospace;font-size:10px;color:#e8ff47;letter-spacing:.22em;text-transform:uppercase;margin-bottom:6px;">
      Radar musical automatisé
    </div>
    <div style="font-family:Impact,Arial,sans-serif;font-size:clamp(40px,8vw,68px);line-height:.9;color:#f0f0f0;">
      SORTIES<br><span style="color:#e8ff47;">DU VENDREDI</span>
    </div>
  </div>
  {weeks_html}
  <div style="margin-top:40px;padding-top:16px;border-top:1px solid #1e1e1e;font-family:monospace;font-size:10px;color:#2a2a2a;letter-spacing:.08em;text-transform:uppercase;">
    The Strokes · Bloc Party · Two Door Cinema Club · The Vaccines · Interpol
  </div>
</div>
</body></html>"""

# ── ENVOI EMAIL ───────────────────────────────────────────────
def send_email(friday: date, releases: list[dict], test: bool = False):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_PASSWORD")

    if not gmail_user or not gmail_pass:
        print("  ⚠ GMAIL_USER ou GMAIL_PASSWORD non définis — email non envoyé.")
        return

    subject = f"🎸 Sorties du vendredi {fmt_date(friday)} — {len(releases)} nouveautés"
    html_body = build_email_html(friday, releases)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    if test:
        print(f"  [TEST] Email prêt : {subject}")
        return

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, RECIPIENT_EMAIL, msg.as_string())
    print(f"  📧 Email envoyé à {RECIPIENT_EMAIL}")

# ── MAIN ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Sorties du Vendredi")
    parser.add_argument("--html", action="store_true", help="Génère aussi sorties.html")
    parser.add_argument("--test", action="store_true", help="Test sans envoyer d'email")
    parser.add_argument("--force", action="store_true", help="Rescan même si déjà en cache")
    args = parser.parse_args()

    if "ANTHROPIC_API_KEY" not in os.environ:
        print("❌ ANTHROPIC_API_KEY non définie.")
        print("   Export: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    friday = get_last_friday()
    key = friday_key(friday)
    history = load_history()

    print(f"\n🎸 SORTIES DU VENDREDI — {fmt_date(friday)}")
    print("─" * 50)

    if key in history and not args.force:
        print(f"  ✓ Déjà en cache. Utilise --force pour rescanner.")
        releases = history[key]
    else:
        print(f"  → Scan de la semaine du {fmt_date(get_monday(friday))} au {fmt_date(friday)}...")
        releases = fetch_releases(friday)
        history[key] = releases

        # Garder seulement les MAX_HISTORY derniers vendredis
        fridays = get_last_n_fridays(MAX_HISTORY)
        valid_keys = {friday_key(f) for f in fridays}
        history = {k: v for k, v in history.items() if k in valid_keys}
        save_history(history)
        print(f"  💾 Historique sauvegardé dans {HISTORY_FILE}")

    if releases:
        send_email(friday, releases, test=args.test)
    else:
        print("  Aucune sortie compatible cette semaine.")

    if args.html:
        fridays = get_last_n_fridays(MAX_HISTORY)
        page = build_web_page(history, fridays)
        HTML_FILE.write_text(page)
        print(f"  🌐 Page web générée : {HTML_FILE.resolve()}")

    print("\n✅ Terminé.\n")

if __name__ == "__main__":
    main()
