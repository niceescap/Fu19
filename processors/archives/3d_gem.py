#!/usr/bin/env python3
"""
metrics_grapher.py — Agent 2 (v6 - FJC Biometric Quad-Blade Engine)
Consomme le nouveau fit_analysis.json à haute densité.
Génère :
  • Une rosace de 1 à 4 pétales 3D (disposés en carré / quadrants)
  • Les archétypes théoriques (Rouleur / Sprinteur) en filet gris légendés
  • L'incrustation des valeurs réelles lisibles (un point sur deux pour la clarté)
Design : Fond blanc pur, ombrage hydrodynamique, texte ancré en 3D, sortie SVG.
"""

import os
import sys
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np

# ── Configuration de la structure FJC ────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIT_OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "fit_analysis.json")
METRICS_SVG     = os.path.join(PROJECT_ROOT, "data", "metrics", "rider_metrics.svg")

DARK_TEXT       = "#1A1A2E"
REF_GRAY_LIGHT  = "#D3D3D3"  # Profil Rouleur (Fleur ouverte)
REF_GRAY_DARK   = "#999999"  # Profil Sprinteur (Tulipe fermée)
BLADE_WIDTH     = 0.35       # Largeur géométrique d'un pétale
FIG_SIZE        = (10, 10)   # Carré parfait pour la rosace

# Les 13 intervalles de temps du nouveau fichier JSON dans l'ordre de déploiement (Centre -> Extrême)
DURATION_MAP = ["60min", "45min", "30min", "15min", "10min", "5min", "2min", "1min", "45s", "30s", "15s", "10s", "5s"]

def load_analysis():
    with open(FIT_OUTPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ── Générateur de profils d'archétypes adaptatifs ────────────────────────────
def get_archetypes(metric_name, values):
    """Génère les limites théoriques adaptées à l'échelle de chaque métrique."""
    v_max = max(values) if max(values) > 0 else 1.0
    
    if metric_name == "power":  # Profils types basés sur les W/kg
        rouleur = np.array([5.5, 5.8, 6.0, 6.2, 6.4, 6.5, 6.8, 7.2, 8.0, 9.5, 11.0, 13.0, 15.0])
        sprinteur = np.array([3.5, 3.6, 3.8, 4.0, 4.2, 4.5, 5.5, 7.5, 10.0, 12.0, 18.0, 20.0, 23.0])
    elif metric_name == "cadence":
        rouleur = np.array([85, 88, 90, 92, 94, 95, 96, 98, 100, 102, 105, 108, 110])
        sprinteur = np.array([92, 95, 100, 102, 105, 110, 115, 120, 122, 125, 130, 132, 135])
    elif metric_name == "heart_rate":
        rouleur = np.array([140, 145, 150, 160, 162, 165, 170, 175, 180, 182, 185, 186, 188])
        sprinteur = np.array([142, 146, 152, 162, 164, 185, 190, 192, 193, 194, 196, 197, 198])
    else:  # Speed
        rouleur = np.array([26, 26, 27, 30, 31, 31.5, 32, 33, 34, 36, 38, 40, 41])
        sprinteur = np.array([25, 25, 26, 28, 29, 30.0, 31, 33, 35, 38, 41, 42, 44])
        
    return rouleur, sprinteur

# ── Construction géométrique 3D du maillage ──────────────────────────────────
def build_quadrant_mesh(radii, values, center_angle, width_factor, scale_factor):
    """Calcule la matrice 3D d'un pétale orientée vers un angle précis (0, pi/2, pi, -pi/2)."""
    R_mesh, Width_mesh = np.meshgrid(radii, np.linspace(-width_factor, width_factor, 24))
    val_mesh = np.tile(values, (24, 1))
    
    # Orientation du maillage selon le quadrant attribué
    Theta_mesh = center_angle + Width_mesh * (1.1 - R_mesh * 0.4)
    
    X = R_mesh * np.cos(Theta_mesh)
    Y = R_mesh * np.sin(Theta_mesh)
    Z = val_mesh * scale_factor
    return X, Y, Z

# ── Tracé principal de la Rosace ─────────────────────────────────────────────
def generate_biometric_rosace(data):
    fig = plt.figure(figsize=FIG_SIZE, facecolor="white")
    ax = fig.add_subplot(111, projection='3d')
    ax.set_facecolor("white")
    
    radii = np.linspace(0.15, 1.0, len(DURATION_MAP))
    meta = data.get("meta", {})
    
    # Configuration des quadrants d'affichage (Carré : Haut, Droite, Bas, Gauche)
    quadrants = {
        "power":      {"active": meta.get("has_power"),      "angle": np.pi/2,  "label": "Puissance (W/kg)", "cmap": cm.plasma, "scale": 0.30,  "key": "power_curve", "sub": "w_kg", "fmt": ".1f"},
        "cadence":    {"active": meta.get("has_cadence"),    "angle": 0.0,      "label": "Cadence (RPM)",    "cmap": cm.viridis, "scale": 0.02,  "key": "cadence_curve", "sub": "value", "fmt": ".0f"},
        "heart_rate": {"active": meta.get("has_heart_rate"), "angle": -np.pi/2, "label": "Cardio (BPM)",     "cmap": cm.magma,   "scale": 0.02,  "key": "heart_rate_curve", "sub": "value", "fmt": ".0f"},
        "speed":      {"active": meta.get("has_speed"),      "angle": np.pi,    "label": "Vitesse (km/h)",   "cmap": cm.coolwarm,"scale": 0.10,  "key": "speed_curve", "sub": "value", "fmt": ".1f"}
    }
    
    # Flags pour éviter les doublons de légendes d'archétypes dans le conteneur global
    legend_added = {"rouleur": False, "sprinteur": False}

    for name, q in quadrants.items():
        if not q["active"]:
            continue
            
        # Extraction des valeurs réelles lues par l'agent
        curve_data = data.get(q["key"], {})
        values = np.array([curve_data.get(d, {}).get(q["sub"], 0.0) for d in DURATION_MAP])
        
        # Calcul des structures fantômes
        ref_r, ref_s = get_archetypes(name, values)
        
        # 1. Tracé Archétype Rouleur (Filet Large)
        Xr, Yr, Zr = build_quadrant_mesh(radii, ref_r, q["angle"], BLADE_WIDTH * 1.3, q["scale"])
        lbl_r = "Réf. Rouleur (Fleur)" if not legend_added["rouleur"] else ""
        ax.plot_wireframe(Xr, Yr, Zr, rstride=5, cstride=3, color=REF_GRAY_LIGHT, alpha=0.15, linewidth=0.5, label=lbl_r)
        legend_added["rouleur"] = True
        
        # 2. Tracé Archétype Sprinteur (Filet Serré)
        Xs, Ys, Zs = build_quadrant_mesh(radii, ref_s, q["angle"], BLADE_WIDTH * 0.9, q["scale"])
        lbl_s = "Réf. Sprinteur (Tulipe)" if not legend_added["sprinteur"] else ""
        ax.plot_wireframe(Xs, Ys, Zs, rstride=5, cstride=3, color=REF_GRAY_DARK, alpha=0.20, linewidth=0.5, label=lbl_s)
        legend_added["sprinteur"] = True
        
        # 3. Tracé du Pétale Réel de l'Athlète
        Xa, Ya, Za = build_quadrant_mesh(radii, values, q["angle"], BLADE_WIDTH, q["scale"])
        ax.plot_surface(Xa, Ya, Za, facecolors=q["cmap"](Za / (Za.max() if Za.max() > 0 else 1)), 
                        linewidth=0, antialiased=True, shade=True, alpha=0.95)
        
        # 4. Marquage du titre du quadrant à l'extrémité externe
        ax.text(1.3 * np.cos(q["angle"]), 1.3 * np.sin(q["angle"]), values[-1] * q["scale"], 
                q["label"], color=DARK_TEXT, fontsize=10, fontweight="bold", ha="center", va="center")

        # 5. Incrustation des étiquettes numériques réelles le long du fil de crête
        # Stride de 2 (on affiche un point sur deux pour éviter toute surcharge visuelle)
        for idx in range(0, len(DURATION_MAP), 2):
            val_str = f"{values[idx]:{q['fmt']}}"
            label_text = f"{DURATION_MAP[idx]}\n{val_str}"
            
            x_pos = radii[idx] * np.cos(q["angle"])
            y_pos = radii[idx] * np.sin(q["angle"])
            z_pos = values[idx] * q["scale"] + (Za.max() * 0.04) # Flottement au-dessus de la pale
            
            ax.text(x_pos, y_pos, z_pos, label_text, color=DARK_TEXT,
                    fontsize=7, fontweight="600", ha="center", va="bottom",
                    bbox=dict(boxstyle="square,pad=0.15", facecolor="white", edgecolor="none", alpha=0.8),
                    fontfamily="DejaVu Sans", zorder=15)

    # ── Caméra et rendu final pour effet de sortie d'écran uniforme ──────────
    ax.view_init(elev=28, azim=-45) # Angle asymétrique parfait pour voir l'élévation des 4 quadrants
    ax.axis('off')
    ax.set_box_aspect([1, 1, 0.45])
    
    # Intégration de la légende des archétypes en haut à gauche
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0), fontsize=9, frameon=False)
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(METRICS_SVG), exist_ok=True)
    plt.savefig(METRICS_SVG, format="svg", bbox_inches="tight", facecolor="white", dpi=150)
    plt.close(fig)
    print(f"✅  Rosace biométrique 4 pétales exportée en SVG avec succès.")

def main():
    try:
        data = load_analysis()
        generate_biometric_rosace(data)
    except Exception as e:
        print(f"❌ Erreur lors de la génération : {e}")

if __name__ == "__main__":
    main()
