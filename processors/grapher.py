#!/usr/bin/env python3
"""
metrics_grapher.py — Agent 2 (v8 - Artichaut Cage Edition)
Importable : load_analysis(path) -> dict
             generate_artichoke(data, output_path) -> None
"""
import os
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
import numpy as np
from io import BytesIO
from PIL import Image


# ── Constantes ───────────────────────────────────────────
DARK_TEXT    = "#1A1A2E"
GRID_GRAY    = "#D0D0D0"
BLADE_WIDTH  = 0.32
FIG_SIZE     = (12, 12)
DURATION_MAP = ["60min", "45min", "30min", "15min", "10min", "5min", "2min", "1min", "45s", "30s", "15s", "10s", "5s"]


def load_analysis(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_fused_mesh(radii, values, base_angle, width_factor, scale_factor):
    R_mesh, Width_mesh = np.meshgrid(radii, np.linspace(-width_factor, width_factor, 26))
    val_mesh = np.tile(values, (26, 1))
    Theta_mesh = base_angle + Width_mesh * (0.4 + R_mesh * 0.8)
    X = R_mesh * np.cos(Theta_mesh)
    Y = R_mesh * np.sin(Theta_mesh)
    Z = val_mesh * scale_factor
    return X, Y, Z


def generate_artichoke(data, output_path):
    fig = plt.figure(figsize=FIG_SIZE, facecolor="none")
    ax = fig.add_subplot(111, projection='3d')
    ax.set_facecolor("none")

    radii = np.linspace(0.15, 1.0, len(DURATION_MAP))
    meta = data.get("meta", {})

    quadrants = {
        "power":      {"active": meta.get("has_power"),      "angle": np.pi/2,  "label": "PUISSANCE (W/kg)", "cmap": cm.Wistia,   "scale": 0.25, "key": "power_curve",      "sub": "w_kg",  "fmt": ".1f"},
        "cadence":    {"active": meta.get("has_cadence"),    "angle": 0.0,      "label": "CADENCE (rpm)",    "cmap": cm.winter,   "scale": 0.02, "key": "cadence_curve",    "sub": "value", "fmt": ".0f"},
        "heart_rate": {"active": meta.get("has_heart_rate"), "angle": -np.pi/2, "label": "CARDIO (bpm)",     "cmap": cm.RdPu,     "scale": 0.02, "key": "heart_rate_curve", "sub": "value", "fmt": ".0f"},
        "speed":      {"active": meta.get("has_speed"),      "angle": np.pi,    "label": "VITESSE (km/h)",   "cmap": cm.bone,     "scale": 0.08, "key": "speed_curve",      "sub": "value", "fmt": ".1f"},
    }

    # ── Trame fixe ────────────────────────────────────────
    universal_profile = np.linspace(20, 100, len(DURATION_MAP))
    for q in quadrants.values():
        Xg, Yg, Zg = build_fused_mesh(radii, universal_profile, q["angle"], BLADE_WIDTH * 1.25, q["scale"])
        ax.plot_wireframe(Xg, Yg, Zg, rstride=5, cstride=4, color=GRID_GRAY, alpha=0.25, linewidth=0.7)

    # ── Pétales de l'athlète ──────────────────────────────
    for q in quadrants.values():
        if not q["active"]:
            continue

        curve_data = data.get(q["key"], {})
        values = np.array([curve_data.get(d, {}).get(q["sub"], 0.0) for d in DURATION_MAP])
        Xa, Ya, Za = build_fused_mesh(radii, values, q["angle"], BLADE_WIDTH, q["scale"])

        norm_Z = Za / (Za.max() if Za.max() > 0 else 1)
        colors_matrix = q["cmap"](norm_Z)
        for r_idx in range(len(radii)):
            opacity = 0.98 - (radii[r_idx] * 0.50)
            colors_matrix[:, r_idx, 3] = opacity

        ax.plot_surface(Xa, Ya, Za, facecolors=colors_matrix, linewidth=0, antialiased=True, shade=True)

        # Label principal
        ax.text(1.11 * np.cos(q["angle"]), 1.11 * np.sin(q["angle"]), values[-1] * q["scale"],
                q["label"], color=DARK_TEXT, fontsize=10, fontweight="bold", ha="center", va="center")

        # Étiquettes de durée
        label_angle_offset = 0.30
        for idx in range(0, len(DURATION_MAP), 2):
            val_str = f"{values[idx]:{q['fmt']}}"
            label_text = f"{DURATION_MAP[idx]}\n{val_str}"
            current_label_angle = q["angle"] + label_angle_offset
            x_pos = radii[idx] * np.cos(current_label_angle)
            y_pos = radii[idx] * np.sin(current_label_angle)
            z_pos = values[idx] * q["scale"] + (Za.max() * 0.04)
            ax.text(x_pos, y_pos, z_pos, label_text, color=DARK_TEXT,
                    fontsize=7, fontweight="700", ha="center", va="center",
                    bbox=dict(boxstyle="square,pad=0.2", facecolor="white", edgecolor="#EAF0F6", linewidth=0.5, alpha=0.85),
                    fontfamily="DejaVu Sans", zorder=20)

    # ── Scène et export ───────────────────────────────────
    ax.view_init(elev=32, azim=-45)
    ax.axis('off')
    ax.set_box_aspect([1, 1, 0.42])
    plt.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    buf = BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight",
                facecolor="none", transparent=True, dpi=150)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGBA")
    img.save(str(output_path), format="PNG")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_id")
    args = parser.parse_args()

    from pathlib import Path
    profile_dir = Path("data/storage/profiles") / args.profile_id
    input_json = profile_dir / "fit_analysis.json"
    output_png = profile_dir / "metrics" / "rider_metrics.png"
    output_png.parent.mkdir(parents=True, exist_ok=True)

    data = load_analysis(str(input_json))
    generate_artichoke(data, str(output_png))
    print(f"✅ Généré : {output_png}")
