#!/usr/bin/env python3
"""
Web app Flask — Sorties du Vendredi
Accessible depuis n'importe quel téléphone via Railway.
"""

import threading
import os
from flask import Flask, jsonify, render_template_string

from sorties_vendredi import (
    get_last_friday, friday_key, fmt_date,
    fetch_releases, load_history, save_history,
    get_last_n_fridays, MAX_HISTORY,
)

app = Flask(__name__)

_lock = threading.Lock()
scan_state = {"running": False, "error": None, "progress": None}

# ── TEMPLATE MOBILE ──────────────────────────────────────────────────────────

TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <title>Sorties du Vendredi</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0e0e0e; color: #f0f0f0;
      font-family: -apple-system, Arial, sans-serif;
      min-height: 100dvh;
      padding-bottom: env(safe-area-inset-bottom, 0);
    }
    .container { max-width: 640px; margin: 0 auto; padding: 28px 18px 80px; }

    /* Header */
    .header { border-bottom: 2px solid #e8ff47; padding-bottom: 20px; margin-bottom: 32px; }
    .header-label { font-family: monospace; font-size: 10px; color: #e8ff47;
      letter-spacing: .22em; text-transform: uppercase; margin-bottom: 6px; }
    .header-title { font-family: Impact, Arial, sans-serif;
      font-size: clamp(40px, 10vw, 64px); line-height: .9; color: #f0f0f0; }
    .header-title span { color: #e8ff47; }

    /* Bouton scan */
    #scan-btn {
      width: 100%; padding: 16px;
      background: #e8ff47; color: #0e0e0e;
      font-family: monospace; font-size: 13px; font-weight: bold;
      letter-spacing: .1em; text-transform: uppercase;
      border: none; border-radius: 6px; cursor: pointer; transition: opacity .2s;
    }
    #scan-btn:disabled { opacity: .4; cursor: not-allowed; }
    #scan-btn.loading { background: #1a1a1a; color: #e8ff47; border: 1px solid #e8ff47; }
    #progress-bar { height: 2px; background: #1e1e1e; border-radius: 1px; margin-top: 10px; overflow: hidden; display: none; }
    #progress-fill { height: 100%; background: #e8ff47; border-radius: 1px; transition: width .4s ease; }
    #status-msg { margin-top: 10px; font-family: monospace; font-size: 11px;
      color: #555; text-align: center; min-height: 18px; }
    #status-msg.error { color: #ff6450; }
    .scan-wrap { margin-bottom: 36px; }

    /* Semaine */
    .week { margin-bottom: 40px; }
    .week-header { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
    .week-title { font-family: Impact, Arial, sans-serif;
      font-size: 20px; letter-spacing: .04em; color: #f0f0f0; }
    .week-title.current { color: #e8ff47; }
    .badge { font-size: 9px; padding: 2px 8px; border-radius: 100px;
      background: rgba(232,255,71,.08); color: #e8ff47;
      border: 1px solid rgba(232,255,71,.2);
      font-family: monospace; text-transform: uppercase; letter-spacing: .05em; }
    .divider { height: 1px; background: linear-gradient(90deg,#2a2a2a,transparent);
      margin: 8px 0 14px; }

    /* Card sortie */
    .release { display: flex; gap: 14px; padding: 14px 0; border-bottom: 1px solid #1e1e1e; }
    .score-circle { flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-family: monospace; font-size: 13px; font-weight: bold; }
    .release-info { flex: 1; min-width: 0; }
    .artist { font-family: monospace; font-size: 10px; color: #e8ff47;
      letter-spacing: 2px; text-transform: uppercase; margin-bottom: 3px; }
    .title { font-size: 15px; font-weight: bold; color: #f0f0f0; margin-bottom: 6px; }
    .type-tag { font-family: monospace; font-size: 9px; background: #1e1e1e;
      color: #777; padding: 2px 7px; border-radius: 3px; display: inline-block; margin-bottom: 8px; }
    .why { font-size: 12px; color: #888; line-height: 1.6; font-style: italic; margin-bottom: 10px; }
    .deezer-btn { font-family: monospace; font-size: 10px; color: #a238ff;
      text-decoration: none; border: 1px solid #a238ff;
      padding: 4px 12px; border-radius: 3px;
      text-transform: uppercase; letter-spacing: 1px; display: inline-block; }

    /* Empty */
    .empty { color: #555; font-size: 13px; padding: 12px 0; }
    .empty-big { text-align: center; padding: 50px 0; }
    .empty-big .icon { font-size: 36px; margin-bottom: 12px; }
    .empty-big p { color: #555; font-family: monospace; font-size: 12px; line-height: 1.8; }

    /* Footer */
    .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #1e1e1e;
      font-family: monospace; font-size: 10px; color: #2a2a2a;
      letter-spacing: .08em; text-transform: uppercase; }

    /* Dots animation */
    @keyframes blink { 0%,80%,100%{opacity:0} 40%{opacity:1} }
    .dots span { animation: blink 1.4s infinite both; }
    .dots span:nth-child(2) { animation-delay: .2s; }
    .dots span:nth-child(3) { animation-delay: .4s; }
  </style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="header-label">Radar musical automatisé</div>
    <div class="header-title">SORTIES<br><span>DU VENDREDI</span></div>
  </div>

  <div class="scan-wrap">
    <button id="scan-btn" onclick="startScan()">⚡ Scanner les 6 derniers vendredis</button>
    <div id="status-msg"></div>
    <div id="progress-bar"><div id="progress-fill" style="width:0%"></div></div>
  </div>

  <div id="weeks">
    {% for w in weeks %}
    <div class="week">
      <div class="week-header">
        <div class="week-title {% if w.current %}current{% endif %}">
          Vendredi {{ w.friday_fmt }}
        </div>
        {% if w.current %}<span class="badge">Cette semaine</span>{% endif %}
      </div>
      <div class="divider"></div>
      {% if w.releases %}
        {% for r in w.releases %}
        <div class="release">
          <div class="score-circle"
            style="background:{{ r.color }}18;border:2px solid {{ r.color }};color:{{ r.color }};">
            {{ r.score }}
          </div>
          <div class="release-info">
            <div class="artist">{{ r.artist }}</div>
            <div class="title">{{ r.title }}</div>
            <div><span class="type-tag">{{ r.type_label }}</span></div>
            <div class="why">{{ r.why }}</div>
            {% if r.deezer_url %}
            <a href="{{ r.deezer_url }}" class="deezer-btn" target="_blank">▶ Deezer</a>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      {% else %}
        <div class="empty">Aucune sortie compatible cette semaine.</div>
      {% endif %}
    </div>
    {% endfor %}

    {% if not weeks %}
    <div class="empty-big">
      <div class="icon">🎸</div>
      <p>Aucun scan encore.<br>Lance le premier scan !</p>
    </div>
    {% endif %}
  </div>

  <div class="footer">
    The Strokes · Bloc Party · Two Door Cinema Club · The Vaccines · Interpol
  </div>
</div>

<script>
let polling = null;

function setStatus(msg, error) {
  const el = document.getElementById('status-msg');
  el.innerHTML = msg;
  el.className = error ? 'error' : '';
}

function setLoading(on) {
  const btn = document.getElementById('scan-btn');
  const bar = document.getElementById('progress-bar');
  btn.disabled = on;
  if (on) {
    btn.className = 'loading';
    btn.innerHTML = 'Scan en cours\u00a0<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
    setStatus('Recherche des sorties via Claude + Deezer…');
    bar.style.display = 'block';
  } else {
    btn.className = '';
    btn.innerHTML = '⚡ Scanner les 6 derniers vendredis';
    bar.style.display = 'none';
    document.getElementById('progress-fill').style.width = '0%';
  }
}

async function startScan() {
  setLoading(true);
  try {
    const res = await fetch('/scan', { method: 'POST' });
    if (res.status === 409) { startPolling(); return; }
    if (!res.ok) throw new Error('Erreur serveur (' + res.status + ')');
    startPolling();
  } catch(e) {
    setLoading(false);
    setStatus('❌ ' + e.message, true);
  }
}

function startPolling() {
  if (polling) clearInterval(polling);
  polling = setInterval(async () => {
    try {
      const { running, error, progress } = await (await fetch('/api/status')).json();
      if (progress) {
        const [cur, tot] = progress.split('/').map(Number);
        document.getElementById('progress-fill').style.width = (cur / tot * 100) + '%';
        setStatus('Vendredi ' + cur + '/' + tot + ' en cours…');
      }
      if (error) {
        clearInterval(polling); setLoading(false);
        setStatus('❌ ' + error, true);
      } else if (!running) {
        clearInterval(polling); setLoading(false);
        setStatus('✅ Scan terminé !');
        setTimeout(() => location.reload(), 900);
      }
    } catch(_) {}
  }, 2000);
}

{% if scan_running %}setLoading(true); startPolling();{% endif %}
</script>
</body>
</html>"""

# ── HELPERS ──────────────────────────────────────────────────────────────────

def _color(score):
    if score >= 80: return '#e8ff47'
    if score >= 65: return '#ffa500'
    return '#ff6450'

def _type_label(t):
    return {'album': '🎵 Album', 'ep': '💿 EP', 'single': '🎤 Single'}.get(t, t)

def _enrich(r):
    return {**r, 'color': _color(r['score']), 'type_label': _type_label(r.get('type', ''))}

# ── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    history  = load_history()
    fridays  = get_last_n_fridays(MAX_HISTORY)
    current  = get_last_friday()
    weeks = []
    for f in fridays:
        key = friday_key(f)
        if key not in history:
            continue
        weeks.append({
            'friday_fmt': fmt_date(f),
            'current':    f == current,
            'releases':   [_enrich(r) for r in history[key]],
        })
    return render_template_string(TEMPLATE, weeks=weeks, scan_running=scan_state['running'])


@app.route('/scan', methods=['POST'])
def trigger_scan():
    with _lock:
        if scan_state['running']:
            return jsonify({'error': 'Scan déjà en cours'}), 409
        scan_state['running'] = True
        scan_state['error']   = None

    def _run():
        try:
            history = load_history()
            fridays = get_last_n_fridays(MAX_HISTORY)
            to_scan = [f for f in fridays if friday_key(f) not in history]
            total   = len(to_scan)

            if total == 0:
                with _lock:
                    scan_state['progress'] = 'already_cached'
            else:
                for i, friday in enumerate(to_scan, 1):
                    with _lock:
                        scan_state['progress'] = f"{i}/{total}"
                    releases = fetch_releases(friday)
                    history[friday_key(friday)] = releases

            valid = {friday_key(f) for f in fridays}
            save_history({k: v for k, v in history.items() if k in valid})
        except Exception as e:
            with _lock:
                scan_state['error'] = str(e)
        finally:
            with _lock:
                scan_state['running'] = False
                scan_state['progress'] = None

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'status': 'started'})


@app.route('/api/status')
def api_status():
    return jsonify(scan_state)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
