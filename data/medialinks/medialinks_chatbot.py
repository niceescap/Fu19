# ~/fjc/data/medialinks/medialinks_chatbot.py
import os
import json
import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from data.database import SessionLocal
from data.models import Athlete

medialinks_bp = Blueprint("medialinks_bp", __name__, template_folder="templates")

# Configuration Groq
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TRACKING_PARAMS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                   'fbclid', 'gclid', 'si', 'feature', 'pp', 'igshid']

# Prompt système par défaut (contient le mot "JSON" pour satisfaire l'API)
DEFAULT_PROMPT = """Tu es l'assistant média d'une application de fiches athlètes.
Ton rôle est d'analyser le message pour y détecter des mentions de réseaux sociaux (Instagram, TikTok, YouTube, Strava) ou des sites web de presse ou de commerce.
Si tu détectes un site non conforme, du contenu offensant ou de la suspicion de nudité, tu refuses le lien.
Réponds impérativement au format JSON avec deux clés :
1. "bot_message": Un message court et sympa dans la langue détectée.
2. "extracted_medias": Un tableau d'objets contenant {"platform": "...", "type": "...", "value": "...", "label": "..."}.

Ne renvoie RIEN d'autre que ce JSON."""

# --- Fonctions utilitaires ---

def normalize_url(url):
    parsed = urlparse(url)
    query = '&'.join(p for p in parsed.query.split('&') if p.split('=')[0] not in TRACKING_PARAMS)
    path = parsed.path.rstrip('/') or '/'
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, parsed.params, query, ''))

def ensure_scheme(url):
    if not url.startswith(('http://', 'https://')):
        return 'https://' + url
    return url

def resolve_url(url):
    url = ensure_scheme(url)
    parsed = urlparse(url)
    short_domains = ['strava.app.link', 'vm.tiktok.com', 'youtu.be']
    if parsed.netloc in short_domains:
        try:
            resp = requests.get(url, allow_redirects=True, timeout=5, stream=True)
            url = resp.url
        except Exception:
            pass
    return normalize_url(url)

def query_groq(system_prompt, history, user_input):
    """Appelle l'API Groq et retourne TOUJOURS un dict avec bot_message et extracted_medias."""
    if not GROQ_API_KEY:
        print("[Groq] Clé API absente.")
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
        print(f"[Groq] Statut HTTP : {res.status_code}")
        if res.status_code == 200:
            content = res.json()['choices'][0]['message']['content']
            print(f"[Groq] Réponse brute : {content[:120]}...")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                print("[Groq] JSON invalide, retour fallback.")
                return {"bot_message": "Le format de la réponse est incorrect.", "extracted_medias": []}
        else:
            print(f"[Groq] Erreur API : {res.text[:200]}")
            return {"bot_message": f"Erreur API ({res.status_code}).", "extracted_medias": []}
    except requests.exceptions.RequestException as e:
        print(f"[Groq] Erreur réseau : {e}")
        return {"bot_message": "Problème réseau avec l'API Groq.", "extracted_medias": []}
    except Exception as e:
        print(f"[Groq] Erreur inattendue : {e}")
        return {"bot_message": "Oups, petit bug du LLM...", "extracted_medias": []}

def scrape_open_graph(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = (soup.find("meta", property="og:title") or {}).get("content")
            image = (soup.find("meta", property="og:image") or {}).get("content")
            return title, image
    except Exception:
        pass
    return None, None

def fetch_oembed(platform, url):
    if platform == "youtube":
        endpoint = f"https://www.youtube.com/oembed?url={url}&format=json"
    elif platform == "tiktok":
        endpoint = f"https://www.tiktok.com/oembed?url={url}"
    else:
        return None, None
    try:
        resp = requests.get(endpoint, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("title"), data.get("thumbnail_url")
    except Exception:
        pass
    return None, None

# --- Routes du Blueprint ---

@medialinks_bp.route("/<athlete_id>", methods=["GET"])
def chatbot_interface(athlete_id):
    # Si la session ne contient pas encore de media_list, on la remplit depuis la BDD
    if "media_list" not in session:
        db = SessionLocal()
        try:
            ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
            if ath and ath.medias and "links" in ath.medias:
                links = ath.medias["links"]
                # Trier par position
                sorted_items = sorted(links.values(), key=lambda x: x.get("position", 999))
                session["media_list"] = [
                    {
                        "url": item.get("url"),
                        "label": item.get("label", ""),
                        "type": item.get("type", "autre"),
                        "platform": item.get("platform"),
                        "title": item.get("title"),
                        "thumbnail": item.get("thumbnail"),
                    }
                    for item in sorted_items
                ]
            else:
                session["media_list"] = []
        except Exception as e:
            print(f"Erreur chargement médias existants : {e}")
            session["media_list"] = []
        finally:
            db.close()

    if "chat_history" not in session:
        session["chat_history"] = []

    return render_template("medialinks_chatbot.html",
                           athlete_id=athlete_id,
                           chat_history=session["chat_history"],
                           media_list=session["media_list"])

@medialinks_bp.route("/<athlete_id>/send_message", methods=["POST"])
def send_message(athlete_id):
    user_msg = request.form.get("message", "")
    if not user_msg:
        return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": user_msg})

    result = query_groq(DEFAULT_PROMPT, history, user_msg)  # retourne toujours un dict
    bot_msg = result.get("bot_message", "Analyse terminée.")
    history.append({"role": "assistant", "content": bot_msg})
    session["chat_history"] = history

    # Traitement des médias extraits
    media_list = session.get("media_list", [])
    for media in result.get("extracted_medias", []):
        val = media.get("value", "").strip()
        if not val:
            continue
        platform = media.get("platform", "").lower()
        if platform in ["site web", "web"] and not val.startswith(("http://", "https://")):
            val = "https://" + val

        if "http" in val:
            val = resolve_url(val)
        else:
            val = val.lower()

        # Éviter doublons
        if not any(m.get("url") == val for m in media_list):
            title, thumbnail = None, None
            if "http" in val:
                if platform in ["youtube", "tiktok"]:
                    title, thumbnail = fetch_oembed(platform, val)
                    if not title and not thumbnail:
                        title, thumbnail = scrape_open_graph(val)
                elif platform in ["strava", "site web", "web"]:
                    title, thumbnail = scrape_open_graph(val)
            media_list.append({
                "url": val,
                "label": media.get("label", val),
                "type": media.get("type", "profile"),
                "platform": platform,
                "title": title,
                "thumbnail": thumbnail
            })

    session["media_list"] = media_list
    return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))

@medialinks_bp.route("/<athlete_id>/remove/<int:index>", methods=["POST"])
def remove_media(athlete_id, index):
    media_list = session.get("media_list", [])
    if 0 <= index < len(media_list):
        media_list.pop(index)
        session["media_list"] = media_list
    return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))

@medialinks_bp.route("/<athlete_id>/reorder", methods=["POST"])
def reorder_media(athlete_id):
    new_order = request.get_json()
    if new_order and isinstance(new_order, list):
        media_list = session.get("media_list", [])
        try:
            media_list = [media_list[i] for i in new_order]
            session["media_list"] = media_list
        except IndexError:
            pass
    return "", 204

@medialinks_bp.route("/<athlete_id>/validate", methods=["POST"])
def validate_and_save(athlete_id):
    from data.database import SessionLocal
    from data.models import Athlete
    from sqlalchemy.orm.attributes import flag_modified

    media_list = session.get("media_list", [])
    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath:
            new_links = {}
            for idx, item in enumerate(media_list):
                key = f"{item.get('type','autre')}_{item.get('label','')}"
                new_links[key] = {
                    "url": item["url"],
                    "label": item.get("label", ""),
                    "type": item.get("type", "autre"),
                    "position": idx,
                    "platform": item.get("platform"),
                    "title": item.get("title"),
                    "thumbnail": item.get("thumbnail")
                }
            medias = dict(ath.medias) if ath.medias else {"links": {}, "galerie": []}
            medias["links"] = new_links
            ath.medias = medias
            flag_modified(ath, "medias")
            db.commit()
            flash("✅ Médias sauvegardés.", "success")
    except Exception as e:
        db.rollback()
        flash(f"❌ Erreur : {str(e)}", "error")
    finally:
        db.close()

    # Nettoyer la session
    session.pop("chat_history", None)
    session.pop("media_list", None)
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))
