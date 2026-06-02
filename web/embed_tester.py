import os
import json
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse, urlunparse
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_SNIPPET_ENHANCER_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_PROMPT = """Tu es l'assistant média d'une application de fiches athlètes. Ton rôle est d'analyser le message pour y détecter des mentions de réseaux sociaux (Instagram, TikTok, YouTube, Strava) ou des sites web.

Tu dois impérativement répondre au format JSON strict avec deux clés :
1. "bot_message": Un message court et sympa en français.
2. "extracted_medias": Un tableau d'objets contenant {"platform": "...", "type": "...", "value": "..."}.

Garde en mémoire les anciens médias s'ils ne sont pas modifiés. Ne renvoie RIEN d'autre que le JSON brut."""

state = {
    "system_prompt": DEFAULT_PROMPT,
    "chat_history": [],
    "media_grid": {},
    "frozen": False
}

# --- FONCTIONS UTILITAIRES ---

TRACKING_PARAMS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                   'fbclid', 'gclid', 'si', 'feature', 'pp', 'igshid']

def normalize_url(url):
    """Supprime les paramètres de tracking, met en minuscule et enlève le slash final."""
    parsed = urlparse(url)
    query = '&'.join(
        p for p in parsed.query.split('&')
        if p.split('=')[0] not in TRACKING_PARAMS
    )
    path = parsed.path.rstrip('/') or '/'
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, parsed.params, query, ''))

def ensure_scheme(url):
    """Ajoute https:// si aucun schéma n'est présent."""
    if not url.startswith(('http://', 'https://')):
        return 'https://' + url
    return url

def resolve_url(url):
    """Suit les redirections uniquement pour les liens courts connus, puis normalise."""
    url = ensure_scheme(url)
    parsed = urlparse(url)
    short_domains = ['strava.app.link', 'vm.tiktok.com', 'youtu.be']
    if parsed.netloc in short_domains:
        print(f"[🔍 Resolution] Suivi de la redirection pour : {url}")
        try:
            response = requests.get(url, allow_redirects=True, timeout=5, stream=True)
            final_url = response.url
            return normalize_url(final_url)
        except Exception as e:
            print(f"[⚠️ Erreur] {e}")
    return normalize_url(url)

def query_groq(system_prompt, history, user_input):
    if not GROQ_API_KEY:
        return {"bot_message": "Clé API Groq manquante !", "extracted_medias": []}

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    try:
        res = requests.post(GROQ_URL, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            content = res.json()['choices'][0]['message']['content']
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                print(f"⚠️ Réponse non-JSON : {content}")
                return {"bot_message": "Le LLM a répondu dans un format inattendu.", "extracted_medias": []}
    except Exception as e:
        print(f"❌ Erreur Groq: {e}")
    return {"bot_message": "Oups, petit bug réseau avec le cerveau LLM...", "extracted_medias": []}

# --- ENRICHISSEMENT DES APERÇUS ---

def scrape_open_graph(url):
    """Extrait le titre et l'image d'une page via ses balises Open Graph."""
    print(f"[🌐 Scraping OG] Tentative sur : {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find("meta", property="og:title") or soup.find("meta", property="twitter:title")
            image_tag = soup.find("meta", property="og:image") or soup.find("meta", property="twitter:image")
            title = title_tag["content"] if title_tag else (soup.title.string if soup.title else None)
            image = image_tag["content"] if image_tag else None
            return title, image
    except Exception as e:
        print(f"[⚠️ Erreur Scraping] {e}")
    return None, None

def fetch_oembed(platform, url):
    """Interroge les points de terminaison oEmbed officiels (YouTube, TikTok)."""
    if platform == "youtube":
        endpoint = f"https://www.youtube.com/oembed?url={url}&format=json"
    elif platform == "tiktok":
        endpoint = f"https://www.tiktok.com/oembed?url={url}"
    else:
        return None, None

    print(f"[📡 oEmbed] Requête vers l'API officielle pour : {url}")
    try:
        response = requests.get(endpoint, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("title"), data.get("thumbnail_url")
    except Exception as e:
        print(f"[⚠️ Erreur oEmbed] {e}")
    return None, None

# --- STYLISATION DES CARTES ---

def get_platform_style(item):
    platform = item.get("platform", "").lower()
    media_type = item.get("type", "").lower()
    url_or_handle = item.get("url_or_handle", "")
    title = item.get("title")
    thumbnail = item.get("thumbnail")

    styles = {
        "strava": {"bg": "#fc4c02", "icon": "🧡", "label": "Strava " + media_type.capitalize()},
        "youtube": {"bg": "#ff0000", "icon": "▶️", "label": "YouTube " + media_type.capitalize()},
        "tiktok": {"bg": "#010101", "icon": "🎵", "label": "TikTok " + media_type.capitalize()},
        "instagram": {"bg": "#e1306c", "icon": "📸", "label": "Instagram " + media_type.capitalize()}
    }
    fallback = {"bg": "#3f3f46", "icon": "🌐", "label": "Site Web / Média"}
    style = styles.get(platform, fallback)

    display_title = title if title else url_or_handle.replace("https://", "").replace("www.", "")
    if len(display_title) > 35:
        display_title = display_title[:32] + "..."

    thumb_html = ""
    if thumbnail:
        thumb_html = f'<div class="card-thumb" style="background-image: url(\'{thumbnail}\'); height: 100px; background-size: cover; background-position: center;"></div>'

    return f"""
    <a href="{url_or_handle}" target="_blank" class="media-card" style="border-top: 4px solid {style['bg']};">
        {thumb_html}
        <div class="card-badge" style="background: {style['bg']};">
            {style['icon']} {style['label']}
        </div>
        <div class="card-content">
            <div class="card-title">{display_title}</div>
            <div class="card-sub">Type : {media_type}</div>
        </div>
    </a>
    """

# --- GABARIT HTML ---

def get_html_template():
    grid_json = json.dumps({"status": "frozen" if state["frozen"] else "active",
                            "media_grid": list(state["media_grid"].values())},
                           indent=4, ensure_ascii=False)

    chat_html = ""
    for msg in state["chat_history"]:
        style = "background: #2563eb; align-self: flex-end; color: #fff;" if msg["role"] == "user" else "background: #1f1f1f; align-self: flex-start;"
        chat_html += f'<div class="bubble" style="{style}">{msg["content"]}</div>'

    cards_html = ""
    for item in state["media_grid"].values():
        cards_html += get_platform_style(item)

    disabled = "disabled" if state["frozen"] else ""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MediaBot Lab - Rendu Fiche</title>
    <style>
        body {{ font-family: 'Segoe UI', sans-serif; background: #0f0f12; color: #e4e4e7; margin: 0; padding: 10px; display: flex; height: 100vh; box-sizing: border-box; gap: 10px; }}
        .panel {{ background: #18181c; border-radius: 8px; padding: 15px; display: flex; flex-direction: column; border: 1px solid #2f2f37; overflow: hidden; }}
        .left {{ flex: 4; min-width: 320px; }}
        .right {{ flex: 6; min-width: 400px; }}
        textarea {{ background: #111114; color: #ffca28; border: 1px solid #3f3f46; border-radius: 6px; padding: 8px; font-family: monospace; resize: none; height: 80px; margin-bottom: 5px; }}
        .chat-box {{ background: #111114; border: 1px solid #3f3f46; border-radius: 6px; flex: 1; display: flex; flex-direction: column; padding: 10px; overflow-y: auto; gap: 8px; margin-bottom: 10px; }}
        .bubble {{ padding: 8px 12px; border-radius: 12px; max-width: 85%; word-wrap: break-word; font-size: 14px; }}
        .input-row {{ display: flex; gap: 8px; }}
        input[type="text"] {{ flex: 1; background: #111114; border: 1px solid #3f3f46; color: #fff; padding: 10px; border-radius: 6px; }}
        button {{ background: #2563eb; color: #fff; border: none; padding: 10px 15px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
        button:hover {{ background: #1d4ed8; }}
        .btn-reset {{ background: #dc2626; }}

        .preview-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; overflow-y: auto; flex: 1; padding-right: 5px; margin-bottom: 15px; }}
        .media-card {{ background: #1f1f23; border-radius: 6px; text-decoration: none; color: #fff; display: flex; flex-direction: column; transition: transform 0.2s, background 0.2s; border: 1px solid #2d2d34; overflow: hidden; }}
        .media-card:hover {{ transform: translateY(-3px); background: #26262b; border-color: #4b4b56; }}
        .card-thumb {{ width: 100%; height: 100px; background-size: cover; background-position: center; }}
        .card-badge {{ padding: 4px 8px; font-size: 11px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; gap: 4px; }}
        .card-content {{ padding: 12px; display: flex; flex-direction: column; justify-content: space-between; flex: 1; }}
        .card-title {{ font-size: 13px; font-weight: 600; line-height: 1.4; color: #f4f4f5; word-break: break-all; }}
        .card-sub {{ font-size: 11px; color: #a1a1aa; margin-top: 6px; }}

        pre {{ background: #09090b; color: #22c55e; padding: 10px; border-radius: 6px; font-family: monospace; font-size: 11px; overflow: auto; max-height: 150px; margin: 0; }}
        h3 {{ margin: 0 0 10px 0; color: #f4f4f5; border-bottom: 1px solid #2f2f37; padding-bottom: 5px; font-size: 16px; }}
    </style>
</head>
<body>
    <div class="panel left">
        <h3>⚙️ Prompt Système</h3>
        <form action="/update_prompt" method="POST" style="display:flex; flex-direction:column; margin-bottom:10px;">
            <textarea name="prompt" {disabled}>{state["system_prompt"]}</textarea>
            <button type="submit" style="background:#4b5563; padding:5px 10px; font-size:12px;" {disabled}>Sauvegarder le Prompt</button>
        </form>

        <h3>💬 Chatbot Média</h3>
        <div class="chat-box">
            {chat_html}
        </div>
        <form action="/send_message" method="POST" class="input-row">
            <input type="text" name="message" placeholder="Colle tes liens ici..." required {disabled}>
            <button type="submit" {disabled}>Envoyer</button>
        </form>
    </div>

    <div class="panel right">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 10px; border-bottom: 1px solid #2f2f37; padding-bottom: 5px;">
            <h3 style="margin:0; border:none;">👀 Aperçu Bas de Fiche (Media Grid)</h3>
            <form action="/reset" method="POST" style="margin:0;">
                <button type="submit" class="btn-reset">🛑 FIN / RESET</button>
            </form>
        </div>

        <div class="preview-grid">
            {cards_html}
        </div>

        <h3>🗂️ Sortie JSON brute</h3>
        <pre>{grid_json}</pre>
    </div>

    <script>
        const cb = document.querySelector('.chat-box');
        cb.scrollTop = cb.scrollHeight;
    </script>
</body>
</html>
"""

# --- SERVEUR WEB ---

class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(get_html_template().encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = parse_qs(post_data)

        if self.path == "/update_prompt" and not state["frozen"]:
            state["system_prompt"] = params.get("prompt", [DEFAULT_PROMPT])[0]

        elif self.path == "/send_message" and not state["frozen"]:
            user_msg = params.get("message", [""])[0]
            state["chat_history"].append({"role": "user", "content": user_msg})

            response_json = query_groq(state["system_prompt"], state["chat_history"], user_msg)

            bot_text = response_json.get("bot_message", "Analyse effectuée.")
            state["chat_history"].append({"role": "assistant", "content": bot_text})

            for media in response_json.get("extracted_medias", []):
                val = media.get("value", "").strip()
                if not val:
                    continue

                platform = media.get("platform", "").lower()
                if platform in ["site web", "web"] and not val.startswith(("http://", "https://")):
                    val = "https://" + val

                if val not in state["media_grid"]:
                    if "http" in val:
                        val = resolve_url(val)  # résolution + normalisation
                    else:
                        val = val.lower()

                    title, thumbnail = None, None
                    if "http" in val:
                        if platform in ["youtube", "tiktok"]:
                            # Essayer d'abord oEmbed (vidéos), sinon fallback scraping OG (profils)
                            title, thumbnail = fetch_oembed(platform, val)
                            if not title and not thumbnail:
                                print(f"[⚠️ oEmbed échoué, tentative scraping OG pour : {val}]")
                                title, thumbnail = scrape_open_graph(val)
                        elif platform in ["strava", "site web", "web"]:
                            title, thumbnail = scrape_open_graph(val)
                        # Instagram : pas d'aperçu, on garde title/thumbnail à None

                    state["media_grid"][val] = {
                        "platform": media.get("platform"),
                        "type": media.get("type"),
                        "url_or_handle": val,
                        "title": title,
                        "thumbnail": thumbnail
                    }

        elif self.path == "/reset":
            if not state["frozen"] and len(state["chat_history"]) > 0:
                state["frozen"] = True
                state["chat_history"].append({"role": "assistant", "content": "🏁 Session figée. Vos tuiles médias sont prêtes ! Re-cliquez pour effacer."})
            else:
                state["chat_history"] = []
                state["media_grid"] = {}
                state["frozen"] = False
                state["system_prompt"] = DEFAULT_PROMPT

        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

if __name__ == "__main__":
    PORT = 8070
    print(f"🚀 Lab de maquetage enrichi démarré sur http://localhost:{PORT}")
    server = HTTPServer(("", PORT), WebServerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Fermeture du lab.")
        server.server_close()
