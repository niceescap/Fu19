# ~/fjc/data/database.py
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Gestion des chemins pour Termux/VPS
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from core.config import DB_CONNECTION_STRING

# Initialisation du moteur SQLAlchemy
# L'argument connect_args n'est nécessaire que pour SQLite (gestion du multi-threading)
if DB_CONNECTION_STRING.startswith("sqlite"):
    engine = create_engine(DB_CONNECTION_STRING, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DB_CONNECTION_STRING)

# Session locale pour exécuter des requêtes (CRUD)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Classe de base dont hériteront nos modèles SQL
Base = declarative_base()

def get_db():
    """Générateur de session pour isoler chaque transaction de manière sécurisée"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
