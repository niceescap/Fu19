#!/usr/bin/env python3
"""
avatar_chatbot.py — Avatar FJC (V2 industrialisée, Blueprint Flask)

Intégration : Blueprint monté dans app.py sous le préfixe /avatar/
Accès direct standalone (dev) : python avatar_chatbot.py → http://0.0.0.0:5050

Nouveautés V2 → Blueprint :
- Monté dans app.py principal (plus de serveur séparé)
- athlete_id transmis en paramètre GET à l'ouverture
- /finalize appelle FicheFactory.attach_avatar() et redirige vers la fiche
- Logs internes identifient clairement la V2
"""

import json
import re
import sys
import copy
import shutil
from pathlib import Path
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, redirect, url_for, render_template
from core.config import PROFILES_DIR
import requests

# ── Chemins ───────────────────────────────────────────────────────────────────
AVATAR_DIR  = Path(__file__).parent          # ~/fjc/data/avatar/
USERS_DIR   = AVATAR_DIR / "users"
OUTPUT_DIR  = AVATAR_DIR / "outputs"         # fallback
PRESETS_DIR = AVATAR_DIR / "presets"         # fallback
# ── Intégration projet FJC ────────────────────────────────────────────────────
BASE_FJC = Path(__file__).resolve().parent.parent.parent  # ~/fjc/
if str(BASE_FJC) not in sys.path:
    sys.path.insert(0, str(BASE_FJC))
from core.config import OR_API_KEY, OR_MODEL, OR_URL, OR_REFERER, OR_APP_TITLE
if str(AVATAR_DIR) not in sys.path:
    sys.path.insert(0, str(AVATAR_DIR))
from engine import build_avatar, DEFAULTS, save_config

# ── Blueprint ─────────────────────────────────────────────────────────────────
avatar_bp = Blueprint(
    "avatar",
    __name__,
    url_prefix="/avatar"
)

# ── System prompt V2 ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Tu es un assistant de personnalisation d'avatar cycliste (projet FJC).
Tu disposes de 12 calques : background, sketch, shoes, socks, short, skin, gloves, jersey, helmet, glasses, screen, hairs.
Tu ne connais pas leurs couleurs actue
lles, sauf si on te les indique dans un résumé fourni plus bas.

RÈGLES STRICTES :
1. Tu réponds TOUJOURS avec un objet JSON valide, structuré exactement ainsi :
{
  "message": "Ta phrase amicale en français",
  "changes": {
    "nom_du_calque": "#rrggbb",
    ...
  }
}
2. La clé "changes" ne contient QUE les calques que tu souhaites modifier. Si rien ne change, tu mets un objet vide {}.
3. Tu n'inventes JAMAIS de nouvelles clés à l'intérieur de "changes".
4. Les couleurs sont toujours en hexadécimal minuscule (#rrggbb).
5. Tu réponds dans la langue du premier message de l'utilisateur.
6. Si l'utilisateur cite un personnage (ex: Bart Simpson), tu déduis les couleurs et tu renvoies tous les calques modifiés dans "changes" en un seul message (plus de questions).
7. Tu ne modifies JAMAIS "sketch" ni "background" sauf demande explicite.
8. Tu restes bref et amical."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_valid_hex(color_str: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", color_str))


def extract_json_from_text(text: str) -> dict | None:
    # 1. ```json ... ```
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 2. <JSON>...</JSON>
    match = re.search(r"<JSON>\s*(.*?)\s*</JSON>", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 3. Premier objet JSON brut
    start = text.find('{')
    end   = text.rfind('}')
    if start != -1 and end != -1 and start < end:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    return None


def validate_changes(changes: dict) -> dict:
    valid = {}
    for layer_id, color in changes.items():
        if layer_id in DEFAULTS["layers"] and is_valid_hex(color):
            valid[layer_id] = color.lower()
    return valid


def load_preset(user_id: str) -> dict:
    user_dir  = USERS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    preset_path = user_dir / "current_preset.json"
    if preset_path.exists():
        with open(preset_path, "r", encoding="utf-8") as f:
            return json.load(f)
    preset = copy.deepcopy(DEFAULTS)
    with open(preset_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)
    return preset

def save_preset(user_id: str, preset: dict):
    user_dir = USERS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    with open(user_dir / "current_preset.json", "w", encoding="utf-8") as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)


def apply_changes(preset: dict, changes: dict) -> dict:
    for layer_id, color in changes.items():
        preset["layers"][layer_id]["base_color"] = color
    return preset


def generate_avatar(user_id: str, preset: dict) -> tuple[Path | None, str | None]:
    outputs_dir = USERS_DIR / user_id / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = outputs_dir / f"avatar_{timestamp}.png"
    try:
        avatar = build_avatar(preset)
        avatar.save(output_path, "PNG")
        return output_path, None
    except Exception as e:
        return None, f"Erreur de génération : {e}"


def get_color_summary(preset: dict) -> str:
    lines = []
    for layer_id in preset["stack_order"]:
        layer = preset["layers"][layer_id]
        lines.append(f"- {layer['label']} ({layer_id}) : {layer['base_color']}")
    return "\n".join(lines)


def load_history(user_id: str) -> list:
    hist_path = USERS_DIR / user_id / "history.json"
    if hist_path.exists():
        with open(hist_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(user_id: str, history: list):
    user_dir = USERS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    if len(history) > 10:
        history = history[-10:]
    with open(user_dir / "history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def call_groq(messages: list) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "temperature": 0.4,
        "max_tokens":  1024
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def get_user_id() -> str:
    """Récupère l'identifiant utilisateur depuis le cookie ou le paramètre GET."""
    user_id = request.cookies.get("user_id")
    if user_id:
        return user_id
    user_id = request.args.get("user")
    if user_id:
        return user_id
    return "default"

def get_athlete_id() -> str | None:
    """Récupère l'athlete_id depuis le paramètre GET ou le corps JSON."""
    athlete_id = request.args.get("athlete_id")
    if athlete_id:
        return athlete_id
    if request.is_json:
        return request.json.get("athlete_id")
    return None


# ── Routes Blueprint ──────────────────────────────────────────────────────────

@avatar_bp.route("/")
def index():
    user_id    = get_user_id()
    athlete_id = request.args.get("athlete_id", "")

    USERS_DIR.mkdir(exist_ok=True)
    (USERS_DIR / user_id).mkdir(exist_ok=True)

    avatar_preview_url = "/avatar/default"   # par défaut
    preset_loaded      = False

    if athlete_id:
        from data.database import SessionLocal
        from data.models import Athlete

        db = SessionLocal()
        try:
            ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
            if ath and ath.photo_status == "AVATAR":
                # Tenter de charger le preset sauvegardé de l'athlète
                preset_path = PROFILES_DIR / athlete_id / "avatar_preset.json"
                if preset_path.exists():
                    with open(preset_path, "r", encoding="utf-8") as f:
                        saved_preset = json.load(f)
                    save_preset(user_id, saved_preset)
                    preset_loaded = True
                # L'aperçu pointera vers l'image actuelle de l'athlète
                avatar_preview_url = f"/avatar/current/{athlete_id}"
        finally:
            db.close()

    if not preset_loaded:
        # Charger le preset par défaut (ou le courant déjà existant pour ce user)
        _ = load_preset(user_id)

    return render_template("avatar_chatbot.html",
                           athlete_id=athlete_id,
                           avatar_preview_url=avatar_preview_url)

@avatar_bp.route("/chat", methods=["POST"])
def chat():
    user_msg = request.json.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "message vide"}), 400
    user_id = get_user_id()
    preset  = load_preset(user_id)
    history = load_history(user_id)

    history.append({"role": "user", "content": user_msg})
    save_history(user_id, history)
    # Contexte LLM réduit
    context = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": "État actuel de l'avatar :\n" + get_color_summary(preset)},
    ]
    for entry in history[-10:]:
        context.append(entry)
    try:
        llm_response_text = call_llm(context)
    except Exception as e:
        error_msg = f"Erreur API LLM : {e}"
        history.append({"role": "assistant", "content": error_msg})
        save_history(user_id, history)
        return jsonify({"message": error_msg, "avatar_url": None})
    history.append({"role": "assistant", "content": llm_response_text})
    save_history(user_id, history)
    data = extract_json_from_text(llm_response_text)
    if not data or "message" not in data:
        return jsonify({"message": llm_response_text, "avatar_url": None})

    message = data.get("message", "")
    changes = validate_changes(data.get("changes", {}))

    if changes:
        apply_changes(preset, changes)
        save_preset(user_id, preset)
        output_path, error = generate_avatar(user_id, preset)
        if error:
            return jsonify({"message": f"{message}\n⚠️ {error}", "avatar_url": None})
        avatar_url = f"/avatar/img/{user_id}/{output_path.name}"
        return jsonify({
            "message":    message,
            "avatar_url": avatar_url,
            "preset":     f"user {user_id}"
        })
    else:
        return jsonify({"message": message, "avatar_url": None})


@avatar_bp.route("/img/<user_id>/<filename>")
def avatar_img(user_id, filename):
    path = USERS_DIR / user_id / "outputs" / filename
    if path.exists():
        return send_file(str(path), mimetype="image/png")
    return "Image non trouvée", 404

@avatar_bp.route("/default")
def avatar_default():
    default_path = OUTPUT_DIR / "avatar_default.png"
    if not default_path.exists():
        preset = copy.deepcopy(DEFAULTS)
        preset["layers"]["helmet"]["base_color"] = "#ffe000"
        try:
            avatar = build_avatar(preset)
            OUTPUT_DIR.mkdir(exist_ok=True)
            avatar.save(default_path, "PNG")
        except Exception as e:
            return f"Erreur génération défaut : {e}", 500
    response = send_file(str(default_path), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"]        = "no-cache"
    return response

@avatar_bp.route("/current/<athlete_id>")
def avatar_current(athlete_id):
    """
    Renvoie l'avatar actuel de l'athlète s'il existe,
    sinon redirige vers l'image par défaut.
    """
    from data.database import SessionLocal
    from data.models import Athlete

    db = SessionLocal()
    try:
        ath = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if ath and ath.photo_status == "AVATAR":
            avatar_path = PROFILES_DIR / athlete_id / "images" / "avatar.png"
            if avatar_path.exists():
                return send_file(str(avatar_path), mimetype="image/png")
    finally:
        db.close()

    return redirect(url_for("avatar.avatar_default"))

@avatar_bp.route("/finalize", methods=["POST"])
def finalize():
    """
    Finalise l'avatar :
    1. Génère le PNG final
    2. Appelle FicheFactory.attach_avatar() → copie vers le coffre-fort + BDD
    3. Redirige vers /fiche/<athlete_id>

    Paramètres POST JSON attendus :
        { "athlete_id": "fjc_ath_..." }
    """
    user_id    = get_user_id()
    athlete_id = request.json.get("athlete_id") if request.is_json else None
    preset     = load_preset(user_id)

    print(f"🎨 [AVATAR V2] Finalisation — user={user_id} athlete={athlete_id}")

    # 1. Générer le PNG final
    final_png_path = USERS_DIR / user_id / "avatar_final.png"
    try:
        avatar = build_avatar(preset)
        avatar.save(final_png_path, "PNG")
    except Exception as e:
        return jsonify({"status": "ERROR", "message": f"Erreur génération finale : {e}"}), 500

    # Sauvegarder le preset final
    final_preset_path = USERS_DIR / user_id / "final_preset.json"
    with open(final_preset_path, "w", encoding="utf-8") as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)
    # 2. Attacher l'avatar à la fiche si athlete_id fourni
    if athlete_id:
        from data.database import SessionLocal
        from processors.fiche_factory import FicheFactory

        db = SessionLocal()
        try:
            result = FicheFactory.attach_avatar(db, athlete_id, final_png_path)
            print(f"📁 [AVATAR V2] attach_avatar → {result['status']}")
            if result["status"] != "SUCCESS":
                return jsonify({
                    "status":  "ERROR",
                    "message": f"Avatar généré mais non attaché : {result['message']}"
                }), 500
        finally:
            db.close()
    else:
        print("⚠️  [AVATAR V2] Aucun athlete_id — avatar généré mais non attaché à une fiche.")
   
    # Sauvegarde du preset dans le profil de l'athlète
    if athlete_id:
        athlete_preset_path = PROFILES_DIR / athlete_id / "avatar_preset.json"
        athlete_preset_path.parent.mkdir(parents=True, exist_ok=True)
        with open(athlete_preset_path, "w", encoding="utf-8") as f:
            json.dump(preset, f, indent=2, ensure_ascii=False)

    # 3. Purge des fichiers intermédiaires
    default_cache = OUTPUT_DIR / "avatar_default.png"
    if default_cache.exists():
        default_cache.unlink()

    user_outputs = USERS_DIR / user_id / "outputs"
    if user_outputs.exists():
        shutil.rmtree(user_outputs)
        user_outputs.mkdir()

    # 4. Réponse : redirect URL pour le JS
    redirect_url = f"/fiche/{athlete_id}" if athlete_id else "/fiches"
    return jsonify({
        "status":       "SUCCESS",
        "message":      "Avatar créé avec succès !",
        "redirect_url": redirect_url
    })

@avatar_bp.route("/reset", methods=["POST"])
def reset():
    user_id = get_user_id()
    preset  = copy.deepcopy(DEFAULTS)
    save_preset(user_id, preset)
    save_history(user_id, [])
    return jsonify({"message": "Preset réinitialisé aux valeurs par défaut."})


# ── Standalone dev ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    from flask import Flask

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY manquante — vérifie ~/.bashrc")
        sys.exit(1)

    standalone = Flask(__name__)
    standalone.secret_key = "fjc-avatar-dev"
    standalone.register_blueprint(avatar_bp)
    host  = os.environ.get("FLASK_HOST",  "0.0.0.0")
    port  = int(os.environ.get("FLASK_PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    print(f"▶ [AVATAR V2] Standalone → http://{host}:{port}/avatar/")
    standalone.run(host=host, port=port, debug=debug, threaded=True)
