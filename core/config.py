# ~/fjc/core/config.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Garantit que ~/fjc/ est dans sys.path quel que soit le répertoire d'exécution
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# ==============================================================================
# 1. ARCHITECTURE DES CHEMINS (PATH MANAGEMENT)
# ==============================================================================
# Dossiers de stockage génériques
DATA_DIR         = BASE_DIR / "data"
STORAGE_DIR      = DATA_DIR / "storage"
ATTESTATIONS_DIR = STORAGE_DIR / "attestations"
PROFILES_DIR     = STORAGE_DIR / "profiles"

# ── Pipeline FIT (Agent 1) ──
FIT_INPUT_DIR        = DATA_DIR / "fit_files"
FIT_OUTPUT_FILE      = DATA_DIR / "fit_analysis.json"
FIT_ACQUISITION_MODE = "directory"
FIT_NO_RECORDS       = False

# ── Sorties métriques (Agent 2 → grapher.py) ──
# Génération de rider_metrics.png via generate_artichoke()
METRICS_DIR = DATA_DIR / "metrics"


# ==============================================================================
# 2. CONFIGURATION DE L'ENVIRONNEMENT (DEV VS PROD)
# ==============================================================================
ENV   = os.environ.get("FJC_ENV", "DEVELOPMENT")
DEBUG = ENV == "DEVELOPMENT"
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# ==============================================================================
# 3. CONFIGURATION DES BASES DE DONNÉES
# ==============================================================================
if ENV == "PRODUCTION":
    DB_CONNECTION_STRING = os.environ.get("DATABASE_URL", "")
else:
    DB_FILE = DATA_DIR / "app.db"
    DB_CONNECTION_STRING = f"sqlite:///{DB_FILE}"
# ==============================================================================
# 4. CONFIGURATION DE LA SÉCURITÉ ET DES SESSIONS
# ==============================================================================
SECRET_KEY    = os.environ.get(
    "FJC_SECRET_KEY",
    "dev-secret-key-ultra-locale-pour-termux-12345"
)
BCRYPT_ROUNDS = 12 if ENV == "PRODUCTION" else 4


# ==============================================================================
# 5. CONFIGURATION DES AGENTS EXTERNES (IA & SCRAPING)
# ==============================================================================

# ── Groq (groq.com) — LLM API ──────────────────────────────────────────────
#
#   Pour obtenir ta clé : https://console.groq.com/keys
#
#   La clé ne doit JAMAIS apparaître dans ce fichier.
#   Elle se place une seule fois dans ton environnement shell :
#
#     Sur Termux / Linux — ajoute cette ligne dans ~/.bashrc ou ~/.profile :
#       export GROQ_API_KEY="gsk_xxxxxxxxxxxxxxxxxxxx"
#
#     Puis recharge le shell :
#       source ~/.bashrc
#
#     Pour vérifier que la variable est bien visible :
#       echo $GROQ_API_KEY
#
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL       = "llama-3.3-70b-versatile"
GROQ_MAX_RETRIES = 3


# ── Limites fichiers ───────────────────────────────────────────────────────
MAX_CONTENT_LENGTH       = 16 * 1024 * 1024   # 16 Mo
ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg"}
ALLOWED_FIT_EXTENSIONS   = {"fit"}


# ==============================================================================
# 6. SÉCURITÉ JURIDIQUE & RETENTION (RGPD)
# ==============================================================================
ARCHIVE_RETENTION_YEARS = 15


# ==============================================================================
# 7. CONFIGURATION WEB ET TEMPLATES
# ==============================================================================
BASE_URL = os.environ.get("BASE_URL", "https://proto.fu19.org")

WEB_DIR       = BASE_DIR / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR    = WEB_DIR / "static"

# Création automatique des répertoires Web
for directory in [TEMPLATES_DIR, STATIC_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
