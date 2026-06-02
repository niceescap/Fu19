#!/usr/bin/env python3
"""
metrics_grapher.py — Agent 2 (v9 GPT Biomorphic Edition)

Concept :
────────────────────────────────────────────────────────────
Rosace physiologique biomorphique procédurale.
Le graphe devient une membrane musculaire générative :
- extrusion variable,
- nervures internes,
- ombres simulées,
- gradients physiologiques,
- noyau énergétique central,
- profondeur organique.

Objectifs :
- conserver 100% fidélité des données,
- créer une signature physiologique premium,
- rester FULL Python / Matplotlib / SVG offline.

Sortie :
- SVG ultra stylisé
- compatible pipeline HTML existant
"""

import os
import json
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np

from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIT_OUTPUT_FILE = os.path.join(
    PROJECT_ROOT,
    "data",
    "fit_analysis.json"
)

METRICS_SVG = os.path.join(
    PROJECT_ROOT,
    "data",
    "metrics",
    "rider_metrics_v9.svg"
)

FIG_SIZE = (12, 12)

GRID_GRAY = "#D8DCE2"
TEXT_DARK = "#18202A"

INNER_CORE = 0.18

DURATION_MAP = [
    "60min",
    "45min",
    "30min",
    "15min",
    "10min",
    "5min",
    "2min",
    "1min",
    "45s",
    "30s",
    "15s",
    "10s",
    "5s"
]

# ─────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────

def load_analysis():
    with open(FIT_OUTPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ─────────────────────────────────────────────────────────────
# BIOMORPHIC THICKNESS
# ─────────────────────────────────────────────────────────────

def build_biomorphic_blade(
    radii,
    values,
    base_angle,
    width_factor,
    scale_factor
):
    """
    Génère une pale organique avec :
    - épaisseur variable
    - nervures internes
    - extrusion biomorphique
    """

    radial_mesh, width_mesh = np.meshgrid(
        radii,
        np.linspace(-width_factor, width_factor, 36)
    )

    val_mesh = np.tile(values, (36, 1))

    # ─────────────────────────────────────────
    # ÉPAISSEUR VARIABLE
    # ─────────────────────────────────────────

    intensity = val_mesh / (val_mesh.max() + 1e-6)

    dynamic_width = (
        0.25
        + intensity * 0.75
    )

    theta_mesh = (
        base_angle
        + width_mesh
        * dynamic_width
        * (0.35 + radial_mesh * 1.1)
    )

    # ─────────────────────────────────────────
    # COORDONNÉES
    # ─────────────────────────────────────────

    X = radial_mesh * np.cos(theta_mesh)
    Y = radial_mesh * np.sin(theta_mesh)

    # ─────────────────────────────────────────
    # EXTRUSION
    # ─────────────────────────────────────────

    membrane = (
        val_mesh * scale_factor
    )

    # ─────────────────────────────────────────
    # MICRO RELIEF
    # ─────────────────────────────────────────

    micro_relief = (
        np.sin(radial_mesh * 18)
        * 0.015
        * intensity
    )

    Z = membrane + micro_relief

    return X, Y, Z, intensity

# ─────────────────────────────────────────────────────────────
# GLOW
# ─────────────────────────────────────────────────────────────

def add_energy_core(ax):

    theta = np.linspace(0, 2*np.pi, 200)

    for radius, alpha in [
        (0.14, 0.10),
        (0.11, 0.16),
        (0.08, 0.22),
    ]:

        x = radius * np.cos(theta)
        y = radius * np.sin(theta)
        z = np.zeros_like(theta)

        ax.plot(
            x,
            y,
            z,
            color="#00FFD0",
            linewidth=12,
            alpha=alpha
        )

# ─────────────────────────────────────────────────────────────
# SHADOW SYSTEM
# ─────────────────────────────────────────────────────────────

def draw_shadow_surface(ax, X, Y, Z):

    ax.plot_surface(
        X + 0.015,
        Y - 0.02,
        Z - 0.03,
        color="black",
        alpha=0.06,
        linewidth=0,
        shade=False
    )

# ─────────────────────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────────────────────

def generate_biomorphic_signature(data):

    fig = plt.figure(
        figsize=FIG_SIZE,
        facecolor="white"
    )

    ax = fig.add_subplot(
        111,
        projection="3d"
    )

    ax.set_facecolor("white")

    # ─────────────────────────────────────────
    # RADIOLOGY STRUCTURE
    # ─────────────────────────────────────────

    radii = np.linspace(
        INNER_CORE,
        1.0,
        len(DURATION_MAP)
    )

    meta = data.get("meta", {})

    quadrants = {

        "power": {
            "active": meta.get("has_power"),
            "angle": np.pi / 2,
            "label": "PUISSANCE",
            "cmap": cm.YlOrRd,
            "scale": 0.024,
            "key": "power_curve",
            "sub": "w_kg",
            "width": 0.30
        },

        "cadence": {
            "active": meta.get("has_cadence"),
            "angle": 0,
            "label": "CADENCE",
            "cmap": cm.cool,
            "scale": 0.0035,
            "key": "cadence_curve",
            "sub": "value",
            "width": 0.26
        },

        "heart": {
            "active": meta.get("has_heart_rate"),
            "angle": -np.pi / 2,
            "label": "CARDIO",
            "cmap": cm.RdPu,
            "scale": 0.0028,
            "key": "heart_rate_curve",
            "sub": "value",
            "width": 0.24
        },

        "speed": {
            "active": meta.get("has_speed"),
            "angle": np.pi,
            "label": "VITESSE",
            "cmap": cm.cividis,
            "scale": 0.010,
            "key": "speed_curve",
            "sub": "value",
            "width": 0.22
        }
    }

    # ─────────────────────────────────────────
    # ARTICHOKE CAGE
    # ─────────────────────────────────────────

    universal_profile = np.linspace(
        15,
        100,
        len(DURATION_MAP)
    )

    for q in quadrants.values():

        Xg, Yg, Zg, _ = build_biomorphic_blade(
            radii,
            universal_profile,
            q["angle"],
            q["width"] * 1.15,
            q["scale"]
        )

        ax.plot_wireframe(
            Xg,
            Yg,
            Zg,
            rstride=4,
            cstride=3,
            color=GRID_GRAY,
            alpha=0.18,
            linewidth=0.7
        )

    # ─────────────────────────────────────────
    # ENERGY CORE
    # ─────────────────────────────────────────

    add_energy_core(ax)

    # ─────────────────────────────────────────
    # ATHLETE BLOOMS
    # ─────────────────────────────────────────

    for q in quadrants.values():

        if not q["active"]:
            continue

        curve_data = data.get(q["key"], {})

        values = np.array([
            curve_data.get(d, {}).get(q["sub"], 0.0)
            for d in DURATION_MAP
        ])

        X, Y, Z, intensity = build_biomorphic_blade(
            radii,
            values,
            q["angle"],
            q["width"],
            q["scale"]
        )

        # ─────────────────────────────────────
        # SHADOW
        # ─────────────────────────────────────

        draw_shadow_surface(ax, X, Y, Z)

        # ─────────────────────────────────────
        # COLOR ENGINE
        # ─────────────────────────────────────

        norm = Z / (Z.max() + 1e-6)

        colors = q["cmap"](norm)

        # ─────────────────────────────────────
        # OPACITY FALL OFF
        # ─────────────────────────────────────

        for r_idx in range(len(radii)):

            opacity = (
                0.96
                - radii[r_idx] * 0.45
            )

            colors[:, r_idx, 3] = opacity

        # ─────────────────────────────────────
        # SURFACE
        # ─────────────────────────────────────

        ax.plot_surface(
            X,
            Y,
            Z,
            facecolors=colors,
            linewidth=0,
            antialiased=True,
            shade=True
        )

        # ─────────────────────────────────────
        # INTERNAL VEINS
        # ─────────────────────────────────────

        for vein_idx in range(4, 32, 6):

            ax.plot3D(
                X[vein_idx],
                Y[vein_idx],
                Z[vein_idx] + 0.003,
                color="white",
                alpha=0.16,
                linewidth=1.1
            )

        # ─────────────────────────────────────
        # FLOATING LABELS
        # ─────────────────────────────────────

        for idx in range(0, len(DURATION_MAP), 2):

            val = values[idx]

            angle_offset = 0.24

            angle = q["angle"] + angle_offset

            x = radii[idx] * np.cos(angle)
            y = radii[idx] * np.sin(angle)
            z = (
                values[idx] * q["scale"]
                + 0.04
            )

            label = f"{DURATION_MAP[idx]}\n{val:.1f}"

            txt = ax.text(
                x,
                y,
                z,
                label,
                fontsize=7,
                color=TEXT_DARK,
                ha="center",
                va="center",
                fontweight="bold",
                zorder=20
            )

            txt.set_path_effects([
                pe.withStroke(
                    linewidth=3,
                    foreground="white",
                    alpha=0.75
                )
            ])

    # ─────────────────────────────────────────
    # CAMERA
    # ─────────────────────────────────────────

    ax.view_init(
        elev=33,
        azim=-48
    )

    ax.set_box_aspect([
        1,
        1,
        0.45
    ])

    ax.axis("off")

    # ─────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────

    plt.tight_layout()

    os.makedirs(
        os.path.dirname(METRICS_SVG),
        exist_ok=True
    )

    plt.savefig(
        METRICS_SVG,
        format="svg",
        bbox_inches="tight",
        facecolor="white",
        dpi=160
    )

    plt.close(fig)

    print("🚀  Biomorphic Signature v9 GPT générée.")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():

    try:

        data = load_analysis()

        generate_biomorphic_signature(data)

    except Exception as e:

        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    main()
