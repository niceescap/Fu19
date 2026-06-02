#!/usr/bin/env python3
"""
metrics_grapher.py — FJC Agent 2 (v9 - Tore Fermé / 3 Pales 120°)

Consomme : fit_analysis.json  (par profil athlète)
Produit   : rider_metrics.png (par profil athlète)

Géométrie :
  • Tore fermé = cage universelle de référence (espace-temps courbé)
      - Collerette haute = valeurs extrêmes court (5s)
      - Nœud central    = valeurs longues (60min) → trou noir
      - Surface fermée par-dessous = continuité toroïdale
  • 3 pales à 120° : Puissance (W/kg) / Cadence (rpm) / Vitesse (km/h)
      - Ancrage au centre (60min = r_min)
      - Épanouissement vers la collerette (5s = r_max)
      - Morphologie émergente : bulbe serré (sprinter) ↔ fleur plate (rouleur)

Règle métier FJC :
  Le poids (kg) doit être fourni explicitement — aucune valeur par défaut.
  Si absent : exception levée, aucun PNG généré.

Dépendances : matplotlib, numpy
"""

import json
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
from pathlib import Path


# ==============================================================================
# CONSTANTES GRAPHIQUES
# ==============================================================================

FIG_SIZE        = (12, 12)
DPI             = 150

DARK_TEXT       = "#1A1A2E"
TORE_COLOR      = "#B0B8C8"   # gris bleuté — filet toroïdal
TORE_ALPHA      = 0.38        # plus visible que v8 (était 0.25)
TORE_LW         = 0.9

BLADE_WIDTH     = 0.30        # demi-largeur angulaire des pales
BLADE_STEPS     = 32          # résolution angulaire des pales
RADII_STEPS     = 40          # résolution radiale des pales

# Angles des 3 pales (distribution 120°, sens trigonométrique)
ANGLE_POWER   = np.pi / 2          #  90° — haut
ANGLE_CADENCE = np.pi / 2 - (2 * np.pi / 3)   # -30° — bas-droite
ANGLE_SPEED   = np.pi / 2 + (2 * np.pi / 3)   # 210° — bas-gauche

# Ordre radial : 60min au centre (r petit) → 5s en périphérie (r grand)
DURATION_MAP = [
    "60min", "45min", "30min", "15min", "10min",
    "5min",  "2min",  "1min",  "45s",   "30s",
    "15s",   "10s",   "5s"
]

# Paramètres du tore
TORE_R_MAJOR  = 0.72   # rayon majeur (centre figure → centre tube)
TORE_R_MINOR  = 0.38   # rayon mineur (épaisseur du tube)
TORE_PHI_PTS  = 48     # résolution méridienne (fermeture)
TORE_THETA_PTS = 72    # résolution azimutale

# Échelle Z par métrique (compression verticale pour lisibilité)
SCALE_POWER   = 0.28
SCALE_CADENCE = 0.018
SCALE_SPEED   = 0.075


# ==============================================================================
# CHARGEMENT
# ==============================================================================

def load_analysis(json_path: Path) -> dict:
    """Charge fit_analysis.json — lève FileNotFoundError si absent."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_weight(data: dict) -> float:
    """
    Vérifie que le poids est présent et valide dans le JSON.
    Lève ValueError si absent ou nul — règle métier FJC non négociable.
    """
    weight = data.get("rider_weight_kg")
    if not weight or float(weight) <= 0:
        raise ValueError(
            "❌ Poids athlète manquant dans fit_analysis.json.\n"
            "   Le pipeline metrics nécessite un poids renseigné dans la fiche.\n"
            "   Aucun graphique ne sera généré."
        )
    return float(weight)


# ==============================================================================
# TORE FERMÉ — cage universelle de référence
# ==============================================================================

def build_torus(R: float, r: float, n_phi: int, n_theta: int):
    """
    Génère la surface toroïdale fermée.
    R = rayon majeur, r = rayon mineur.
    Retourne X, Y, Z (arrays 2D pour plot_wireframe / plot_surface).
    """
    phi   = np.linspace(0, 2 * np.pi, n_phi)    # méridien (fermeture tube)
    theta = np.linspace(0, 2 * np.pi, n_theta)  # azimut (tour complet)
    PHI, THETA = np.meshgrid(phi, theta)

    X = (R + r * np.cos(PHI)) * np.cos(THETA)
    Y = (R + r * np.cos(PHI)) * np.sin(THETA)
    Z = r * np.sin(PHI)
    return X, Y, Z


def draw_torus_cage(ax):
    """
    Dessine le filet toroïdal de référence.
    Rendu en wireframe gris — plus visible que v8.
    """
    X, Y, Z = build_torus(
        TORE_R_MAJOR, TORE_R_MINOR,
        TORE_PHI_PTS, TORE_THETA_PTS
    )
    ax.plot_wireframe(
        X, Y, Z,
        rstride=3, cstride=4,
        color=TORE_COLOR,
        alpha=TORE_ALPHA,
        linewidth=TORE_LW
    )


# ==============================================================================
# PALES — géométrie et rendu
# ==============================================================================

def extract_values(data: dict, curve_key: str, sub_key: str) -> np.ndarray:
    """
    Extrait les valeurs d'une courbe dans l'ordre DURATION_MAP.
    Valeur 0.0 si durée absente (capteur non dispo pour cet intervalle).
    """
    curve = data.get(curve_key, {})
    return np.array([
        curve.get(d, {}).get(sub_key, 0.0)
        for d in DURATION_MAP
    ], dtype=float)


def build_petal_mesh(values: np.ndarray, base_angle: float,
                     scale_z: float, r_min: float = 0.12, r_max: float = 1.0):
    """
    Construit la surface d'une pale.

    Géométrie :
      - r_min → 60min (centre, valeur basse)
      - r_max → 5s    (périphérie, valeur haute)
      - Évasement angulaire progressif vers l'extérieur (pale de hors-bord)
      - Z = valeur normalisée × scale_z

    Retourne X, Y, Z (arrays 2D).
    """
    n = len(values)
    radii = np.linspace(r_min, r_max, n)

    # Grille (rayon × largeur angulaire)
    R_grid, W_grid = np.meshgrid(
        radii,
        np.linspace(-BLADE_WIDTH, BLADE_WIDTH, BLADE_STEPS)
    )

    # Évasement : la pale s'élargit vers l'extérieur
    evasement = 0.35 + R_grid * 0.90
    Theta_grid = base_angle + W_grid * evasement

    # Valeurs Z interpolées sur la grille radiale
    val_grid = np.tile(values, (BLADE_STEPS, 1))

    X = R_grid * np.cos(Theta_grid)
    Y = R_grid * np.sin(Theta_grid)
    Z = val_grid * scale_z

    return X, Y, Z


def draw_petal(ax, values: np.ndarray, base_angle: float,
               scale_z: float, cmap, label: str):
    """
    Dessine une pale avec gradient d'opacité cœur→bord.
    Opacité forte au centre (60min) → translucide en périphérie (5s).
    """
    n = len(values)
    radii = np.linspace(0.12, 1.0, n)

    X, Y, Z = build_petal_mesh(values, base_angle, scale_z)

    # Normalisation couleur sur Z
    z_max = Z.max() if Z.max() > 0 else 1.0
    norm_Z = Z / z_max
    colors = cmap(norm_Z)

    # Gradient d'opacité : dense au centre, évanescent en bord
    for r_idx in range(n):
        # radii[0] = r_min (centre, 60min) → opacité max
        # radii[-1] = r_max (bord, 5s)     → opacité min
        opacity = 0.95 - (radii[r_idx] * 0.45)
        colors[:, r_idx, 3] = opacity

    ax.plot_surface(
        X, Y, Z,
        facecolors=colors,
        linewidth=0,
        antialiased=True,
        shade=True
    )

    # Label quadrant
    lx = 1.42 * np.cos(base_angle)
    ly = 1.42 * np.sin(base_angle)
    lz = values[-1] * scale_z   # Z au niveau de la valeur 5s
    ax.text(lx, ly, lz, label,
            color=DARK_TEXT, fontsize=10, fontweight="bold",
            ha="center", va="center")


def draw_petal_labels(ax, values: np.ndarray, base_angle: float,
                      scale_z: float, fmt: str):
    """
    Affiche les étiquettes durée+valeur le long du bord de la pale.
    Stride 2 pour ne pas surcharger.
    """
    n = len(values)
    radii = np.linspace(0.12, 1.0, n)
    label_offset = BLADE_WIDTH * 1.15  # décalage angulaire pour ne pas masquer la pale

    for idx in range(0, n, 2):
        val_str   = f"{values[idx]:{fmt}}"
        label_txt = f"{DURATION_MAP[idx]}\n{val_str}"
        angle     = base_angle + label_offset

        x = radii[idx] * np.cos(angle)
        y = radii[idx] * np.sin(angle)
        z = values[idx] * scale_z * 1.06

        ax.text(x, y, z, label_txt,
                color=DARK_TEXT, fontsize=7, fontweight="700",
                ha="center", va="center",
                bbox=dict(
                    boxstyle="square,pad=0.18",
                    facecolor="white",
                    edgecolor="#DDE4EE",
                    linewidth=0.5,
                    alpha=0.88
                ),
                fontfamily="DejaVu Sans",
                zorder=20)


# ==============================================================================
# MOTEUR PRINCIPAL
# ==============================================================================

def generate_artichoke(data: dict, output_png: Path) -> None:
    """
    Pipeline complet :
      1. Validation poids
      2. Extraction des 3 courbes
      3. Tore de référence
      4. 3 pales 120°
      5. Export PNG

    Lève ValueError si poids absent.
    """
    # ── Validation poids (règle métier FJC) ──────────────────────────────────
    validate_weight(data)   # lève ValueError si absent/nul

    meta = data.get("meta", {})

    # ── Extraction des courbes ────────────────────────────────────────────────
    power_vals   = extract_values(data, "power_curve",   "w_kg")
    cadence_vals = extract_values(data, "cadence_curve", "value")
    speed_vals   = extract_values(data, "speed_curve",   "value")

    has_power   = meta.get("has_power",   False)
    has_cadence = meta.get("has_cadence", False)
    has_speed   = meta.get("has_speed",   False)

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=FIG_SIZE, facecolor="white")
    ax  = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("white")

    # ── 1. Tore fermé de référence ────────────────────────────────────────────
    draw_torus_cage(ax)

    # ── 2. Pale Puissance ─────────────────────────────────────────────────────
    if has_power and power_vals.max() > 0:
        draw_petal(ax, power_vals, ANGLE_POWER, SCALE_POWER,
                   cm.Wistia, "PUISSANCE (W/kg)")
        draw_petal_labels(ax, power_vals, ANGLE_POWER, SCALE_POWER, ".1f")

    # ── 3. Pale Cadence ───────────────────────────────────────────────────────
    if has_cadence and cadence_vals.max() > 0:
        draw_petal(ax, cadence_vals, ANGLE_CADENCE, SCALE_CADENCE,
                   cm.winter, "CADENCE (rpm)")
        draw_petal_labels(ax, cadence_vals, ANGLE_CADENCE, SCALE_CADENCE, ".0f")

    # ── 4. Pale Vitesse ───────────────────────────────────────────────────────
    if has_speed and speed_vals.max() > 0:
        draw_petal(ax, speed_vals, ANGLE_SPEED, SCALE_SPEED,
                   cm.bone, "VITESSE (km/h)")
        draw_petal_labels(ax, speed_vals, ANGLE_SPEED, SCALE_SPEED, ".1f")

    # ── FTP encart ────────────────────────────────────────────────────────────
    ftp = data.get("ftp_w")
    if ftp:
        fig.text(0.85, 0.06,
                 f"FTP\n{ftp} W",
                 ha="center", va="bottom",
                 fontsize=11, fontweight="bold",
                 color=DARK_TEXT,
                 fontfamily="DejaVu Sans",
                 bbox=dict(
                     boxstyle="round,pad=0.4",
                     facecolor="white",
                     edgecolor=DARK_TEXT,
                     linewidth=1.2,
                     alpha=0.95
                 ))

    # ── Scène 3D ──────────────────────────────────────────────────────────────
    ax.view_init(elev=28, azim=-50)
    ax.axis("off")
    ax.set_box_aspect([1, 1, 0.38])

    plt.tight_layout(pad=1.5)

    # ── Export PNG ────────────────────────────────────────────────────────────
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(
        output_png,
        format="png",
        bbox_inches="tight",
        facecolor="white",
        dpi=DPI
    )
    plt.close(fig)
    print(f"✅  rider_metrics.png → {output_png}")


# ==============================================================================
# CLI (tests directs)
# ==============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Génère rider_metrics.png depuis fit_analysis.json"
    )
    parser.add_argument("--input",  required=True, help="Chemin vers fit_analysis.json")
    parser.add_argument("--output", required=True, help="Chemin de sortie rider_metrics.png")
    args = parser.parse_args()

    json_path  = Path(args.input)
    output_png = Path(args.output)

    try:
        data = load_analysis(json_path)
        generate_artichoke(data, output_png)
    except ValueError as e:
        print(e)
        sys.exit(1)
    except FileNotFoundError:
        print(f"❌ Fichier introuvable : {json_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
