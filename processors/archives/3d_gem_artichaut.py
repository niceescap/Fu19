#!/usr/bin/env python3
"""
metrics_grapher.py — Agent 2 (v8 - Artichaut Cage Edition)
Consomme fit_analysis.json.
Génère :
  • Une rosace fusionnée (60min au cœur) avec opacité concentrée.
  • Couleurs : Puissance (Jaune), Cadence (Bleu/Cyan), Cardio (Magenta), Vitesse (Noir).
  • Labels épurés (sans unité) et décalés angulairement.
  • Une trame fixe universelle en filet gris simulant la cage de l'artichaut.
Design : Fond blanc pur, conformité Matplotlib stricte, sortie SVG.
"""

import os
import sys
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np

# ── Configuration des chemins d'accès FJC ────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIT_OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "fit_analysis.json")
METRICS_SVG     = os.path.join(PROJECT_ROOT, "data", "metrics", "rider_metrics.svg")

DARK_TEXT       = "#1A1A2E"
GRID_GRAY       = "#D0D0D0"  # Grille de l'artichaut universelle
BLADE_WIDTH     = 0.32       
FIG_SIZE        = (10, 10)

# Ordre d'épanouissement : du cœur (60min) vers l'extérieur (5s)
DURATION_MAP = ["60min", "45min", "30min", "15min", "10min", "5min", "2min", "1min", "45s", "30s", "15s", "10s", "5s"]

def load_analysis():
    with open(FIT_OUTPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def build_fused_mesh(radii, values, base_angle, width_factor, scale_factor):
    """Génère la géométrie d'une pale ancrée au cœur central."""
    R_mesh, Width_mesh = np.meshgrid(radii, np.linspace(-width_factor, width_factor, 26))
    val_mesh = np.tile(values, (26, 1))
    
    # Évasement en éventail depuis le centre
    Theta_mesh = base_angle + Width_mesh * (0.4 + R_mesh * 0.8)
    
    X = R_mesh * np.cos(Theta_mesh)
    Y = R_mesh * np.sin(Theta_mesh)
    Z = val_mesh * scale_factor
    return X, Y, Z

def generate_artichoke_helix(data):
    fig = plt.figure(figsize=FIG_SIZE, facecolor="white")
    ax = fig.add_subplot(111, projection='3d')
    ax.set_facecolor("white")
    
    radii = np.linspace(0.15, 1.0, len(DURATION_MAP))
    meta = data.get("meta", {})
    
    # Configuration de la charte graphique v8 (unités intégrées aux titres)
    quadrants = {
        "power":      {"active": meta.get("has_power"),      "angle": np.pi/2,  "label": "PUISSANCE (W/kg)", "cmap": cm.Wistia,   "scale": 0.25, "key": "power_curve", "sub": "w_kg", "fmt": ".1f"},
        "cadence":    {"active": meta.get("has_cadence"),    "angle": 0.0,      "label": "CADENCE (rpm)",    "cmap": cm.winter,   "scale": 0.02, "key": "cadence_curve", "sub": "value", "fmt": ".0f"},
        "heart_rate": {"active": meta.get("has_heart_rate"), "angle": -np.pi/2, "label": "CARDIO (bpm)",     "cmap": cm.RdPu,     "scale": 0.02, "key": "heart_rate_curve", "sub": "value", "fmt": ".0f"},
        "speed":      {"active": meta.get("has_speed"),      "angle": np.pi,    "label": "VITESSE (km/h)",   "cmap": cm.bone,     "scale": 0.08, "key": "speed_curve", "sub": "value", "fmt": ".1f"}
    }
    
    # ── 1. Génération de la Cage Artichaut (Trame fixe commune) ──────────────
    # Base de référence universelle linéaire pour créer une structure symétrique englobante
    universal_profile = np.linspace(20, 100, len(DURATION_MAP))
    
    for name, q in quadrants.items():
        # Même si le capteur n'est pas actif pour le coureur, on dessine la trame fixe 
        # pour conserver la structure "artichaut complet" immuable sur toutes les fiches
        Xg, Yg, Zg = build_fused_mesh(radii, universal_profile, q["angle"], BLADE_WIDTH * 1.25, q["scale"])
        ax.plot_wireframe(Xg, Yg, Zg, rstride=5, cstride=4, color=GRID_GRAY, alpha=0.25, linewidth=0.7)

    # ── 2. Déploiement des pétales réels de l'athlète ────────────────────────
    for name, q in quadrants.items():
        if not q["active"]:
            continue
            
        curve_data = data.get(q["key"], {})
        values = np.array([curve_data.get(d, {}).get(q["sub"], 0.0) for d in DURATION_MAP])
        
        # Construction géométrique
        Xa, Ya, Za = build_fused_mesh(radii, values, q["angle"], BLADE_WIDTH, q["scale"])
        
        # Rendu du gradient d'opacité (Concentration vers le cœur)
        norm_Z = Za / (Za.max() if Za.max() > 0 else 1)
        colors_matrix = q["cmap"](norm_Z)
        
        for r_idx in range(len(radii)):
            opacity = 0.98 - (radii[r_idx] * 0.50) # Perte de densité progressive vers l'extérieur
            colors_matrix[:, r_idx, 3] = opacity   

        ax.plot_surface(Xa, Ya, Za, facecolors=colors_matrix, linewidth=0, antialiased=True, shade=True)
        
        # Libellé du quadrant avec son unité incluse
        ax.text(1.35 * np.cos(q["angle"]), 1.35 * np.sin(q["angle"]), values[-1] * q["scale"], 
                q["label"], color=DARK_TEXT, fontsize=10, fontweight="bold", ha="center", va="center")

        # Placement décalé des étiquettes épurées (Valeur seule sans unité, Stride 2)
        label_angle_offset = 0.30  
        
        for idx in range(0, len(DURATION_MAP), 2):
            val_str = f"{values[idx]:{q['fmt']}}"
            label_text = f"{DURATION_MAP[idx]}\n{val_str}" # Format épuré : "5s\n16.6"
            
            current_label_angle = q["angle"] + label_angle_offset
            
            x_pos = radii[idx] * np.cos(current_label_angle)
            y_pos = radii[idx] * np.sin(current_label_angle)
            z_pos = values[idx] * q["scale"] + (Za.max() * 0.04)
            
            ax.text(x_pos, y_pos, z_pos, label_text, color=DARK_TEXT,
                    fontsize=7, fontweight="700", ha="center", va="center",
                    bbox=dict(boxstyle="square,pad=0.2", facecolor="white", edgecolor="#EAF0F6", linewidth=0.5, alpha=0.85),
                    fontfamily="DejaVu Sans", zorder=20)

    # ── Configuration de la scène 3D ─────────────────────────────────────────
    ax.view_init(elev=32, azim=-45)
    ax.axis('off')
    ax.set_box_aspect([1, 1, 0.42])
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(METRICS_SVG), exist_ok=True)
    plt.savefig(METRICS_SVG, format="svg", bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    print(f"🚀  Moteur FJC v8 exécuté : Trame fixe artichaut + Pétales épurés.")

def main():
    try:
        data = load_analysis()
        generate_artichoke_helix(data)
    except Exception as e:
        print(f"❌ Erreur lors du rendu de la signature biométrique : {e}")

if __name__ == "__main__":
    main()
