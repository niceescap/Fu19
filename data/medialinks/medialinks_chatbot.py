# ~/fjc/data/medialinks/medialinks_chatbot.py
import os
import json
import requests
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from data.database import SessionLocal
from data.models import Athlete
from sqlalchemy.orm.attributes import flag_modified

medialinks_bp = Blueprint("medialinks_bp", __name__, template_folder="templates")

from core.config import OR_API_KEY, OR_MODEL, OR_URL, OR_REFERER, OR_APP_TITLE
from data.database import SessionLocal

TRACKING_PARAMS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                   'fbclid', 'gclid', 'si', 'feature', 'pp', 'igshid']

# Prompt système par défaut
DEFAULT_PROMPT = """Tu es l'assistant média d'une application de fiches athlètes.
Ton rôle est d'analyser le message pour y détecter des mentions de réseaux sociaux (Instagram, TikTok, YouTube, Strava) ou des sites web de presse ou de commerce.
Si tu détectes du contenu offensant ou de la suspicion de nudité, tu refuses le lien.
Réponds impérativement au format JSON avec deux clés :
1. "bot_message": Un message court et sympa dans la langue détectée.
2. "extracted_medias": Un tableau d'objets contenant {"platform": "...", "type": "...", "value": "...", "label": "..."}.

Ne renvoie RIEN d'autre que ce JSON."""

# ==============================================================================
# FONCTIONS UTILITAIRES
# ==============================================================================

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

def query_llm(system_prompt, history, user_input):
    """Appelle l'API OpenRouter et retourne TOUJOURS un dict avec bot_message et extracted_medias."""
    if not OR_API_KEY:
        print("[LLM] Clé API absente.")
        return {"bot_message": "Clé API OpenRouter manquante !", "extracted_medias": []}

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": OR_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }
    headers = {
        "Authorization": f"Bearer {OR_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OR_REFERER,
        "X-Title": OR_APP_TITLE,
    }

    try:
        res = requests.post(OR_URL, headers=headers, json=payload, timeout=30)
        print(f"[LLM] Statut HTTP : {res.status_code}")
        if res.status_code == 200:
            content = res.json()['choices'][0]['message']['content']
            print(f"[LLM] Réponse brute : {content[:120]}...")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                print("[LLM] JSON invalide, retour fallback.")
                return {"bot_message": "Le format de la réponse est incorrect.", "extracted_medias": []}
        else:
            print(f"[LLM] Erreur API : {res.text[:200]}")
            return {"bot_message": f"Erreur API ({res.status_code}).", "extracted_medias": []}
    except requests.exceptions.RequestException as e:
        print(f"[LLM] Erreur réseau : {e}")
        return {"bot_message": "Problème réseau avec l'API LLM.", "extracted_medias": []}
    except Exception as e:
        print(f"[LLM] Erreur inattendue : {e}")
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

# ==============================================================================
# ROUTES DU BLUEPRINT — FLUX DIRECT BASE DE DONNÉES (ZÉRO COOKIE SATURATION)
# ==============================================================================

@medialinks_bp.route("/<athlete_id>", methods=["GET"])
def chatbot_interface(athlete_id):
    """Affiche l'interface du chatbot en lisant l'état réel de la BDD."""
    db = SessionLocal()
    media_list = []
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath and ath.medias and "links" in ath.medias:
            links = ath.medias["links"]
            # Reconstruction de la liste ordonnée selon le champ position
            sorted_items = sorted(links.values(), key=lambda x: x.get("position", 999))
            media_list = [
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
    except Exception as e:
        print(f"❌ Erreur lors du chargement des médias BDD : {e}")
    finally:
        db.close()

    if "chat_history" not in session:
        session["chat_history"] = []

    return render_template("medialinks_chatbot.html",
                           athlete_id=athlete_id,
                           chat_history=session["chat_history"],
                           media_list=media_list)


@medialinks_bp.route("/<athlete_id>/send_message", methods=["POST"])
def send_message(athlete_id):
    """Traite le message, interroge Groq et écrit IMMEDIATEMENT en BDD."""
    user_msg = request.form.get("message", "")
    if not user_msg:
        return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": user_msg})

    # Appel LLM (OpenRouter)
    result = query_llm(DEFAULT_PROMPT, history, user_msg)
    bot_msg = result.get("bot_message", "Analyse terminée.")
    history.append({"role": "assistant", "content": bot_msg})
    session["chat_history"] = history

    # Écriture immédiate des médias extraits en BDD
    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath:
            medias = dict(ath.medias) if ath.medias else {"links": {}, "galerie": []}
            medias.setdefault("links", {})
            current_count = len(medias["links"])

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

                # Détection des doublons directement dans le JSON BDD
                if not any(m.get("url") == val for m in medias["links"].values()):
                    title, thumbnail = None, None
                    if "http" in val:
                        if platform in ["youtube", "tiktok"]:
                            title, thumbnail = fetch_oembed(platform, val)
                            if not title and not thumbnail:
                                title, thumbnail = scrape_open_graph(val)
                        elif platform in ["strava", "site web", "web"]:
                            title, thumbnail = scrape_open_graph(val)
                    
                    label = media.get("label", val)
                    # Clé unique pour le dictionnaire JSON
                    key = f"{media.get('type', 'profile')}_{hashlib.md5(val.encode()).hexdigest()[:8]}"
                    
                    medias["links"][key] = {
                        "url": val,
                        "label": label,
                        "type": media.get("type", "profile"),
                        "platform": platform,
                        "title": title,
                        "thumbnail": thumbnail,
                        "position": current_count
                    }
                    current_count += 1

            ath.medias = medias
            flag_modified(ath, "medias")
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"❌ Erreur lors de l'injection du média en BDD : {e}")
    finally:
        db.close()

    return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))


@medialinks_bp.route("/<athlete_id>/remove/<int:index>", methods=["POST"])
def remove_media(athlete_id, index):
    """Supprime un média directement dans le JSON de la BDD et réindexe les positions."""
    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath and ath.medias and "links" in ath.medias:
            medias = dict(ath.medias)
            # Tri par position pour cibler le bon index
            sorted_links = sorted(medias["links"].items(), key=lambda x: x[1].get("position", 999))
            
            if 0 <= index < len(sorted_links):
                key_to_remove = sorted_links[index][0]
                medias["links"].pop(key_to_remove)
                
                # Réindexation propre pour éviter les trous dans les positions [0, 1, 2...]
                for idx, (key, item) in enumerate(sorted(medias["links"].items(), key=lambda x: x[1].get("position", 999))):
                    medias["links"][key]["position"] = idx
                
                ath.medias = medias
                flag_modified(ath, "medias")
                db.commit()
    except Exception as e:
        db.rollback()
        print(f"❌ Erreur lors de la suppression du média en BDD : {e}")
    finally:
        db.close()
        
    return redirect(url_for("medialinks_bp.chatbot_interface", athlete_id=athlete_id))


@medialinks_bp.route("/<athlete_id>/reorder", methods=["POST"])
def reorder_media(athlete_id):
    """Met à jour les positions suite à un glisser-déposer (Drag & Drop) du Front-End."""
    new_order = request.get_json()
    if not new_order or not isinstance(new_order, list):
        return "", 400

    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath and ath.medias and "links" in ath.medias:
            medias = dict(ath.medias)
            sorted_links = sorted(medias["links"].items(), key=lambda x: x[1].get("position", 999))
            
            for new_pos, old_idx in enumerate(new_order):
                if old_idx < len(sorted_links):
                    key = sorted_links[old_idx][0]
                    medias["links"][key]["position"] = new_pos
            
            ath.medias = medias
            flag_modified(ath, "medias")
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"❌ Erreur lors de la réorganisation en BDD : {e}")
    finally:
        db.close()
    return "", 204


@medialinks_bp.route("/<athlete_id>/validate", methods=["POST"])
def validate_and_save(athlete_id):
    """Clôture la session du chatbot et redirige vers la fiche en édition."""
    # Tout ayant déjà été persisté en base de données au fil de l'eau,
    # on nettoie uniquement l'historique du chat pour alléger le cookie.
    session.pop("chat_history", None)
    flash("✅ Médias synchronisés avec succès sur la fiche.", "success")
    return redirect(url_for("fiche_edit", athlete_id=athlete_id))
