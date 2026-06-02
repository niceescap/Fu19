# ~/fjc/auth/magic_linker.py
import sys
import secrets
from pathlib import Path
from sqlalchemy.orm import Session

# Alignement strict des chemins pour Termux/VPS
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

# Importations depuis les sources uniques de vérité
from core.config import BASE_URL
from data.queries import save_magic_token, verify_and_consume_magic_token, get_or_create_user

class MagicLinker:
    def __init__(self, base_url: str = BASE_URL):
        # Utilise désormais l'URL centralisée de la configuration par défaut
        self.base_url = base_url
        self.token_lifetime = 900  # 15 minutes en secondes

    def request_login(self, db: Session, email: str) -> str:
        """
        Étape 1 : Le parent/éducateur demande à se connecter.
        Génère un token sécurisé, l'enregistre en BDD et prépare l'URL.
        """
        email_clean = email.strip().lower()

        # S'assurer que le compte User existe
        get_or_create_user(db, email_clean)

        # Génération d'un token cryptographique hautement sécurisé
        token = secrets.token_urlsafe(32)

        # Persistance en base de données
        save_magic_token(db, email_clean, token, self.token_lifetime)

        # Construction de l'URL de redirection magique
        magic_url = f"{self.base_url}/auth/verify?token={token}&email={email_clean}"

        # --- LOGIQUE D'ENVOI (Simulation Console) ---
        print("\n" + "="*60)
        print(f"📩 [SERVEUR EMAIL FJC] Envoi du Magic Link à : {email_clean}")
        print(f"🔗 Lien généré (Valable 15 min) :\n{magic_url}")
        print("="*60 + "\n")

        return magic_url

    def process_landing(self, db: Session, email: str, token: str) -> bool:
        """
        Étape 2 : L'utilisateur a cliqué sur le lien dans son mail.
        Le serveur intercepte les paramètres de l'URL et valide la session.
        """
        # Consommation et vérification du jeton (Sécurité anti-replay)
        is_valid = verify_and_consume_magic_token(db, email, token)

        if is_valid:
            print(f"✅ [AUTH] Session officiellement OUVERTE pour {email}.")
            return True
        else:
            print(f"❌ [AUTH] Échec de connexion pour {email}. Jeton invalide ou expiré.")
            return False


# ==============================================================================
# CRASH TEST INTÉGRÉ EN ENVIRONNEMENT LOCAL
# ==============================================================================
if __name__ == "__main__":
    from data.database import SessionLocal, engine
    from data.models import Base

    print("--- 🛡️ Test d'Authentification Active (Magic Link) ---")
    print(f"[CONFIG] URL racine détectée : {BASE_URL}")

    # Initialisation de la session BDD locale
    Base.metadata.create_all(bind=engine)
    db_session = SessionLocal()

    try:
        # L'instance n'a plus besoin d'argument en dur, elle hérite de core.config
        linker = MagicLinker()
        test_email = "president.club@ffc-provence.fr"

        # 1. Simulation d'une demande de connexion
        print("\n1. Le président du club saisit son email sur le site...")
        url_generee = linker.request_login(db_session, test_email)

        # Extraction du token pour simulation
        import urllib.parse
        parsed_url = urllib.parse.urlparse(url_generee)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        token_intercepte = query_params['token'][0]
        email_intercepte = query_params['email'][0]

        # 2. Simulation du clic sur le lien reçu (Première tentative -> Succès)
        print("2. L'utilisateur ouvre ses mails et clique sur le lien magique...")
        session_active = linker.process_landing(db_session, email_intercepte, token_intercepte)
        print(f"Résultat de l'accès : {'🔓 ACCÈS AUTORISÉ' if session_active else '🔒 ACCÈS REFUSÉ'}")

        # 3. Simulation d'une attaque par rejeu (Deuxième tentative -> Échec)
        print("\n3. Sécurité : Un hacker tente de réutiliser le même lien...")
        replay_attack = linker.process_landing(db_session, email_intercepte, token_intercepte)
        print(f"Résultat de l'accès : {'🔓 ACCÈS AUTORISÉ' if replay_attack else '🔒 ACCÈS REFUSÉ (Protection Replay OK)'}")

    finally:
        db_session.close()
