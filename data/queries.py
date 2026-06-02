# ~/fjc/data/queries.py
import sys
import time
from pathlib import Path
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from data.models import User, Athlete, athlete_owners

# ==============================================================================
# GESTION DES UTILISATEURS & MAGIC LINKS
# ==============================================================================

def get_or_create_user(db: Session, email: str) -> User:
    """Récupère un utilisateur par son email ou le crée s'il n'existe pas (Friction zéro)"""
    email_clean = email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user:
        user = User(email=email_clean)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def save_magic_token(db: Session, email: str, token: str, lifetime_seconds: int = 900):
    """Enregistre le token du Magic Link et son expiration en BDD"""
    user = get_or_create_user(db, email)
    user.magic_token = token
    user.magic_token_expires = int(time.time()) + lifetime_seconds
    db.commit()

def verify_and_consume_magic_token(db: Session, email: str, token: str) -> bool:
    """Vérifie le token, applique l'usage unique (sécurité) et valide la session"""
    email_clean = email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()
    
    if not user or user.magic_token != token:
        return False
        
    if int(time.time()) > user.magic_token_expires:
        # Token expiré, on nettoie
        user.magic_token = None
        db.commit()
        return False
        
    # Consommation du token pour éviter le Replay (Sécurité)
    user.magic_token = None
    db.commit()
    return True

# ==============================================================================
# GESTION DES ATHLÈTES
# ==============================================================================

def create_athlete_with_owner(db: Session, athlete_record: dict, owner_email: str, role: str = "creator") -> Athlete:
    """
    Insère un athlète en BDD et crée immédiatement sa liaison 
    Many-to-Many avec l'utilisateur (créateur) dans la table d'association.
    """
    # 1. S'assurer que l'utilisateur existe
    user = get_or_create_user(db, owner_email)
    
    # 2. Instancier l'athlète avec le dictionnaire structuré par l'onboarding
    new_athlete = Athlete(
        id=athlete_record["id"],
        nom=athlete_record["nom"],
        prenom=athlete_record["prenom"],
        date_naissance=athlete_record["date_naissance"],
        sexe=athlete_record["sexe"],
        junior_horizon=athlete_record["junior_horizon"],
        nationalite=athlete_record["nationalite"],
        photo_status=athlete_record["photo_status"],
        status="PUBLIC",
        uci_id_data=athlete_record["uci_id_data"],
        palmares=athlete_record["palmares"],
        donnees_performance=athlete_record["donnees_performance"],
        medias=athlete_record["medias"],
        partenaires=athlete_record["partenaires"]
    )
    
    # 3. Lier l'athlète et le user via SQLAlchemy (gère la table intermédiaire automatiquement)
    new_athlete.owners.append(user)
    db.add(new_athlete)
    db.commit()
    
    # 4. Ajustement du rôle spécifique dans la table d'association intermédiaire
    db.execute(
        athlete_owners.update()
        .where(athlete_owners.c.user_email == user.email)
        .where(athlete_owners.c.athlete_id == new_athlete.id)
        .values(role=role)
    )
    db.commit()
    db.refresh(new_athlete)
    return new_athlete

def get_user_dashboard_data(db: Session, user_email: str):
    """Récupère l'utilisateur et la liste de toutes ses fiches athlètes liées"""
    user_clean = user_email.strip().lower()
    return db.query(User).filter(User.email == user_clean).first()
