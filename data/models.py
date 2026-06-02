# ~/fjc/data/models.py
import sys
import datetime
from pathlib import Path
from sqlalchemy import Column, String, Integer, JSON, ForeignKey, Table, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from data.database import Base, engine

# ==============================================================================
# TABLE D'ASSOCIATION (Many-to-Many)
# Lie les utilisateurs aux athlètes avec un rôle spécifique
# ==============================================================================
athlete_owners = Table(
    "athlete_owners",
    Base.metadata,
    Column("user_email", String, ForeignKey("users.email", ondelete="CASCADE"), primary_key=True),
    Column("athlete_id", String, ForeignKey("athletes.id", ondelete="CASCADE"), primary_key=True),
    # Le champ 'role' permettra de distinguer qui est le créateur principal,
    # l'entraîneur, le parent ou l'agent (ex: "creator", "coach", "parent", "agent")
    Column("role", String, default="collaborator")
)

# ==============================================================================
# TABLE UTISATEURS (Parents / Entraîneurs / Agents)
# ==============================================================================
class User(Base):
    """
    Table des Utilisateurs (Gestionnaires des fiches)
    Authentification simplifiée par Magic Link (Pas de mot de passe)
    """
    __tablename__ = "users"

    email = Column(String, primary_key=True, index=True, unique=True)
    
    # Correction : Utilisation de DateTime au lieu de JSON pour le timestamp
    created_at = Column(DateTime, default=datetime.datetime.now)

    # Token temporaire pour le Magic Link
    magic_token = Column(String, index=True, nullable=True)
    magic_token_expires = Column(Integer, nullable=True)

    # Relation Many-to-Many : Un utilisateur gère plusieurs athlètes
    athletes = relationship("Athlete", secondary=athlete_owners, back_populates="owners")


# ==============================================================================
# TABLE ATHLÈTES
# ==============================================================================
class Athlete(Base):
    """
    Table des Athlètes (Fiches publiques certifiées)
    """
    __tablename__ = "athletes"

    # Colonnes SQL Classiques
    id = Column(String, primary_key=True, index=True) # ex: fjc_ath_260519_dupo
    nom = Column(String, index=True, nullable=False)
    prenom = Column(String, nullable=False)
    date_naissance = Column(String, nullable=False)
    sexe = Column(String(1), index=True, nullable=False) # 'M' ou 'F'
    junior_horizon = Column(Integer, index=True, nullable=False)
    nationalite = Column(String(2), index=True, default="FR")
    photo_status = Column(String, default="PENDING")

    # Etat de la fiche athlète
    status = Column(String, default="PUBLIC")  # Valeurs : PUBLIC, HIDDEN

    # Modérateurs de cycle de vie et sécurité (Claim / Transfert / Conflits)
    transfer_token = Column(String, nullable=True)

    # Correction : Utilisation de DateTime au lieu de JSON pour le timestamp
    created_at = Column(DateTime, default=datetime.datetime.now)

    # Relation Many-to-Many : Un athlète peut avoir plusieurs utilisateurs autorisés
    owners = relationship("User", secondary=athlete_owners, back_populates="athletes")

    # --- Subdivisions Complexes (JSON) ---
    uci_id_data = Column(JSON, nullable=False)
    palmares = Column(JSON, default=list)
    donnees_performance = Column(JSON, default=dict)
    medias = Column(JSON, default=dict)
    partenaires = Column(JSON, default=list)


# ==============================================================================
# INITIALISATION DE LA BASE
# ==============================================================================
def init_db():
    print("🔨 Application des fondations SQL évolutives (Multi-Owners Many-to-Many)...")
    Base.metadata.create_all(bind=engine)
    print("✅ Base de données v1.3.1 initialisée (Correction DateTime).")

if __name__ == "__main__":
    init_db()
