#!/usr/bin/env python3
"""
metrics_grapher.py — Agent 2 (v6)
Signature physiologique premium à partir de fit_analysis.json (format v2).
Génère :
  • un SVG polaire ultra‑soigné (courbes, FTP, valeurs W/kg)
  • un snippet HTML complet avec jauge cardio repensée
Dépendances : matplotlib, numpy, scipy
"""

import os
import sys
import json
import math
import argparse
import textwrap
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.interpolate import PchipInterpolator
    from matplotlib.patheffects import withStroke
except ImportError as e:
    sys.exit(f"❌  Dépendance manquante : {e}. pip install matplotlib numpy scipy")

# ── Rendre la racine du projet importable ────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from core.config import FIT_OUTPUT_FILE, METRICS_SVG, METRICS_HTML
except ImportError:
    FIT_OUTPUT_FILE = PROJECT_ROOT / "data" / "fit_analysis.json"
    METRICS_SVG     = PROJECT_ROOT / "data" / "metrics" / "rider_metrics.svg"
    METRICS_HTML    = PROJECT_ROOT / "data" / "metrics" / "rider_metrics_snippet.html"

# ── Constantes graphiques ────────────────────────────────────────────────────
DARK_TEXT       = "#1A1A2E"
RED_PMAX        = "#C0392B"
GREEN_TORQUE    = "#27AE60"
BLUE_CADENCE    = "#2980B9"
FILL_GREEN      = "#2ECC71"
GRID_COLOR      = "#E0E0E0"
FIG_SIZE        = (8, 8)

# Plafonds & offset
CEIL_POWER   = 0.96
CEIL_TORQUE  = 0.72
CEIL_CADENCE = 0.52
INNER_OFFSET = 0.22
GAMMA        = 0.55

# ── Angles physiologiques (degrés horaires) ──────────────────────────────────
DURATION_ANGLES_DEG = {
    5:    20,
    15:   42,
    30:   75,
    60:   115,
    300:  165,
    900:  230,
    1800: 270,
    3600: 320,
}
DURATION_ANGLES = {dur: math.radians(deg) for dur, deg in DURATION_ANGLES_DEG.items()}

# ── Chargement des données ───────────────────────────────────────────────────
def load_analysis(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ── Extraction structurée ────────────────────────────────────────────────────
def prepare_spiral_data(data: dict):
    power_curve = data.get("power_curve")
    cadence_curve = data.get("cadence_curve")

    available = set()
    if power_curve:
        available.update(power_curve.keys())
    if cadence_curve:
        available.update(cadence_curve.keys())
    if not available:
        raise ValueError("Aucune courbe de puissance ni cadence disponible.")

    ordered = []
    for dur, angle in sorted(DURATION_ANGLES.items(), key=lambda x: x[1]):
        lbl = f"{dur}s" if dur < 60 else (f"{dur//60}min" if dur % 60 == 0 else f"{dur/60:.1f}min")
        if lbl in available:
            ordered.append((dur, angle, lbl))

    theta     = [angle for _, angle, _ in ordered]
    labels    = [lbl   for _, _, lbl    in ordered]
    durations = [dur   for dur, _, _ in ordered]

    p_wkg   = []
    torque  = []
    cadence = []

    for dur, angle, lbl in ordered:
        if power_curve and lbl in power_curve:
            pt = power_curve[lbl]
            p_wkg.append(pt["w_kg"])
            torque.append(pt.get("torque_nm", 0.0))
        else:
            p_wkg.append(None)
            torque.append(None)

        if cadence_curve and lbl in cadence_curve:
            cadence.append(cadence_curve[lbl]["rpm_avg"])
        else:
            cadence.append(0.0)

    has_power = power_curve is not None and len(power_curve) > 0
    return theta, p_wkg, torque, cadence, has_power, labels, durations

# ── Échelle stylisée ─────────────────────────────────────────────────────────
def stylized_scale(v, vmax, ceil=1.0, gamma=GAMMA, inner=INNER_OFFSET):
    if vmax <= 0:
        return inner
    return inner + ((v / vmax) ** gamma) * (ceil - inner)

def apply_scale(values, vmax, ceil):
    return [stylized_scale(v, vmax, ceil) if v is not None else INNER_OFFSET for v in values]

# ── Interpolation Pchip ──────────────────────────────────────────────────────
def pchip_smooth(theta, radii, num_points=100):
    if len(theta) < 2:
        return theta, radii
    sort_idx = np.argsort(theta)
    t_sorted = np.array(theta)[sort_idx]
    r_sorted = np.array(radii)[sort_idx]
    _, uidx = np.unique(t_sorted, return_index=True)
    t_unique = t_sorted[uidx]
    r_unique = r_sorted[uidx]
    if len(t_unique) < 2:
        return t_unique, r_unique
    try:
        interp = PchipInterpolator(t_unique, r_unique)
        t_smooth = np.linspace(t_unique.min(), t_unique.max(), num_points)
        r_smooth = interp(t_smooth)
        r_smooth = np.clip(r_smooth, 0, None)
        return t_smooth, r_smooth
    except Exception:
        return theta, radii

# ── Graphique polaire premium ────────────────────────────────────────────────
def draw_spiral_chart(theta, p_vals, torque_vals, cadence_vals,
                      has_power, ftp_w, labels, durations,
                      weight_kg, output_svg: Path):
    # Normalisation stylisée
    max_cad = max(cadence_vals) if cadence_vals else 0.0
    radii_cad = apply_scale(cadence_vals, max_cad, CEIL_CADENCE)

    radii_p = None
    radii_t = None
    if has_power:
        valid_p = [v for v in p_vals if v is not None]
        valid_t = [v for v in torque_vals if v is not None]
        if valid_p and valid_t:
            max_p = max(valid_p)
            max_t = max(valid_t)
            radii_p = apply_scale(p_vals, max_p, CEIL_POWER)
            radii_t = apply_scale(torque_vals, max_t, CEIL_TORQUE)

    # Lissage
    ts_cad, rs_cad = pchip_smooth(theta, radii_cad)
    if has_power and radii_p and radii_t:
        ts_p, rs_p = pchip_smooth(theta, radii_p)
        ts_t, rs_t = pchip_smooth(theta, radii_t)

    # Figure
    fig, ax = plt.subplots(figsize=FIG_SIZE, subplot_kw={"projection": "polar"}, facecolor="#FAFAFA")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # Grille atténuée (pointillés fins)
    ax.set_rgrids([0.25, 0.5, 0.75, 1.0], labels=[])
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.4, linestyle="dotted", alpha=0.4)
    ax.set_xticks(theta)
    ax.set_xticklabels([])
    ax.spines["polar"].set_visible(False)
    ax.tick_params(axis="both", which="both", length=0)

    # Glow
    glow = withStroke(linewidth=4, foreground='white', alpha=0.6)

    # Tracé des courbes
    # Cadence (toujours)
    sizes = [max(80 / d, 25) for d in durations]
    ax.plot(ts_cad, rs_cad, color=BLUE_CADENCE, linewidth=3.8, solid_capstyle="round", path_effects=[glow], zorder=5)
    ax.scatter(theta, radii_cad, s=sizes, color=BLUE_CADENCE, edgecolors='white', linewidth=1.2, zorder=6, label="Cadence")

    if has_power and radii_p and radii_t:
        ax.plot(ts_p, rs_p, color=RED_PMAX, linewidth=3.8, solid_capstyle="round", path_effects=[glow], zorder=3)
        ax.scatter(theta, radii_p, s=sizes, color=RED_PMAX, edgecolors='white', linewidth=1.2, zorder=4, label="Pmax")

        ax.plot(ts_t, rs_t, color=GREEN_TORQUE, linewidth=3.8, solid_capstyle="round", path_effects=[glow], zorder=1)
        ax.scatter(theta, radii_t, s=sizes, color=GREEN_TORQUE, edgecolors='white', linewidth=1.2, zorder=2, label="Couple")

        # Halo énergétique multicouche
        for alpha in np.linspace(0.02, 0.18, 8):
            ax.fill_between(ts_p, rs_p, rs_t, color=FILL_GREEN, alpha=alpha, zorder=0)

    # ── Valeurs W/kg clés ────────────────────────────────────────────────────
    if has_power and radii_p:
        # Déterminer les durées à afficher (5s, 1min, 5min)
        for target_dur, target_label in [(5, "5s"), (60, "1min"), (300, "5min")]:
            if target_label in labels:
                idx = labels.index(target_label)
                if p_vals[idx] is not None and not np.isnan(p_vals[idx]):
                    # Position : angle original, rayon = radii_p[idx] + léger décalage
                    angle_point = theta[idx]
                    radius_point = radii_p[idx] + 0.05  # petit offset radial
                    x = radius_point * math.cos(angle_point)
                    y = radius_point * math.sin(angle_point)
                    # Choix du décalage pour éviter la collision
                    ax.text(angle_point, radius_point + 0.02, f"{p_vals[idx]:.1f}", ha='center', va='bottom',
                            fontsize=6.5, fontweight='bold', color=RED_PMAX, alpha=0.85,
                            fontfamily='DejaVu Sans', zorder=10,
                            bbox=dict(facecolor='white', edgecolor='none', alpha=0.5, pad=1, boxstyle='round,pad=0.15'))

    # ── Labels d’intervalles ─────────────────────────────────────────────────
    for angle, label, dur in zip(theta, labels, durations):
        # Taille différenciée selon la durée (courtes = plus visibles)
        if dur <= 60:
            fontsize = 9.5
            weight = 'bold'
            color = DARK_TEXT
        else:
            fontsize = 7.5
            weight = 'normal'
            color = '#666666'
        ax.text(angle, 1.06, label, ha='center', va='center',
                fontsize=fontsize, fontweight=weight, color=color,
                fontfamily='DejaVu Sans')

    ax.set_ylim(0, 1.08)

    # ── Légende compacte (style HUD) ─────────────────────────────────────────
    legend_elements = [
        plt.Line2D([0], [0], color=BLUE_CADENCE, lw=3, solid_capstyle='round', label='Cadence'),
    ]
    if has_power:
        legend_elements += [
            plt.Line2D([0], [0], color=RED_PMAX, lw=3, solid_capstyle='round', label='Pmax'),
            plt.Line2D([0], [0], color=GREEN_TORQUE, lw=3, solid_capstyle='round', label='Couple'),
        ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.1, 1.08),
              fontsize=7.5, frameon=False, handlelength=1.2, handletextpad=0.5)

    # ── FTP Block (capsule en haut à gauche de la figure) ────────────────────
    if ftp_w:
        # Calcul W/kg si poids disponible
        wkg_str = ""
        if weight_kg and weight_kg > 0:
            wkg = ftp_w / weight_kg
            wkg_str = f"\n{wkg:.1f} W/kg"
        bbox_props = dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=DARK_TEXT,
                          linewidth=1.2, alpha=0.9)
        fig.text(0.02, 0.97, f"FTP\n{ftp_w} W{wkg_str}", ha="left", va="top",
                 fontsize=11, fontweight="bold", color=DARK_TEXT,
                 bbox=bbox_props, fontfamily="DejaVu Sans")

    plt.tight_layout(pad=3)
    plt.savefig(output_svg, format="svg", bbox_inches="tight",
                facecolor="#FAFAFA", edgecolor="none", dpi=150)
    plt.close(fig)
    print(f"✅  SVG enregistré → {output_svg}")

# ── Snippet HTML premium ─────────────────────────────────────────────────────
def generate_html_snippet(svg_path: Path, data: dict) -> str:
    with open(svg_path, "r", encoding="utf-8") as f:
        svg = f.read().replace('<?xml version="1.0" encoding="utf-8"?>', "").strip()

    cardio = data.get("cardio_profile")
    if cardio:
        cursor = cardio["cursor"]
        cursor_pct = int(cursor * 100)
        fc_max = cardio.get("fc_max_observed", "—")
        fc_accel = cardio.get("fc_acceleration_bpm_min", "—")
        zone_haute = cardio.get("zone_haute_pct", "—")
        # label cardio
        if cursor > 0.6:
            cardio_label = "Full Gaz"
        elif cursor > 0.4:
            cardio_label = "Puncher"
        elif cursor > 0.2:
            cardio_label = "Tempo"
        else:
            cardio_label = "Diesel"
    else:
        cursor_pct = 50
        fc_max = fc_accel = zone_haute = "—"
        cardio_label = "Inconnu"

    has_power = data.get("has_power", True)

    snippet = textwrap.dedent(f"""\
    <!-- ════════════════════════════════════════════════════
         Bloc métriques coureur — v6 Premium
    ════════════════════════════════════════════════════ -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700&display=swap" rel="stylesheet">

    <div class="rider-signature">
      <!-- Fond avec micro‑texture -->
      <div class="spiral-container" style="filter: drop-shadow(0 6px 16px rgba(0,0,0,0.1));">
        {svg}
      </div>

      <!-- Jauge cardio redesign -->
      <div class="cardio-instrument">
        <div class="cardio-zones">
          <span class="zone diesel">Diesel</span>
          <span class="zone tempo">Tempo</span>
          <span class="zone puncher">Puncher</span>
          <span class="zone fullgaz">Full Gaz</span>
        </div>
        <div class="cardio-track">
          <div class="track-fill"></div>
          <div class="cardio-cursor" style="left: {cursor_pct}%;">
            <div class="cursor-dot"></div>
            <div class="cursor-glow"></div>
          </div>
        </div>
        <div class="cardio-stats">
          <div><strong>FC max</strong> {fc_max} bpm</div>
          <div><strong>Accél.</strong> {fc_accel} bpm/min</div>
          <div><strong>Zone haute</strong> {zone_haute}%</div>
          <div><strong>Profil</strong> {cardio_label}</div>
        </div>
      </div>
    </div>

    <style>
      /* ── Fond & wrapper ────────────────────────────── */
      .rider-signature {{
        max-width: 540px;
        margin: 2rem auto;
        font-family: 'Barlow Condensed', sans-serif;
        background: radial-gradient(circle at 30% 30%, #ffffff, #f5f5f5);
        border-radius: 20px;
        padding: 1.5rem 1rem 1rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.06);
      }}

      .spiral-container {{
        width: 100%;
        border-radius: 12px;
        overflow: hidden;
      }}

      .spiral-container svg {{
        width: 100%;
        height: auto;
        display: block;
      }}

      /* ── Jauge cardio instrument ───────────────────── */
      .cardio-instrument {{
        margin-top: 1.8rem;
        padding-top: 1.2rem;
        border-top: 1px solid #e0e0e0;
      }}

      .cardio-zones {{
        display: flex;
        justify-content: space-between;
        margin-bottom: 0.6rem;
        font-size: 0.7rem;
        letter-spacing: 0.05em;
        color: #999;
        font-weight: 600;
        padding: 0 2px;
      }}

      .cardio-track {{
        height: 14px;
        background: #e9e9e9;
        border-radius: 999px;
        position: relative;
        overflow: visible;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.08);
      }}

      .track-fill {{
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        border-radius: 999px;
        background: linear-gradient(to right, #2980B9, #E67E22);
        opacity: 0.25;
      }}

      .cardio-cursor {{
        position: absolute;
        top: 50%;
        transform: translate(-50%, -50%);
        z-index: 2;
      }}

      .cursor-dot {{
        width: 20px;
        height: 20px;
        background: white;
        border: 3px solid #2ECC71;
        border-radius: 50%;
        box-shadow: 0 0 12px rgba(46, 204, 113, 0.6);
      }}

      .cursor-glow {{
        position: absolute;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 32px;
        height: 32px;
        background: radial-gradient(circle, rgba(46,204,113,0.3), transparent);
        border-radius: 50%;
        pointer-events: none;
      }}

      .cardio-stats {{
        display: flex;
        justify-content: center;
        gap: 1.5rem;
        margin-top: 0.8rem;
        font-size: 0.7rem;
        color: #666;
        flex-wrap: wrap;
      }}

      .cardio-stats div {{
        text-align: center;
      }}

      .cardio-stats strong {{
        color: #1A1A2E;
        font-size: 0.8rem;
      }}

      @media (max-width: 400px) {{
        .rider-signature {{ padding: 1rem 0.5rem; }}
        .cardio-stats {{ gap: 0.8rem; }}
      }}
    </style>
    <!-- ── fin bloc métriques ──────────────────────────── -->
    """)
    return snippet

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="fit_analysis.json → signature physiologique premium")
    parser.add_argument("json_file", nargs="?", default=str(FIT_OUTPUT_FILE))
    parser.add_argument("-o", "--output-svg", default=str(METRICS_SVG))
    parser.add_argument("--html", default=str(METRICS_HTML))
    args = parser.parse_args()

    json_path  = Path(os.path.expanduser(args.json_file))
    svg_path   = Path(os.path.expanduser(args.output_svg))
    html_path  = Path(os.path.expanduser(args.html))
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    data = load_analysis(json_path)
    theta, p_vals, torque_vals, cadence_vals, has_power, labels, durations = prepare_spiral_data(data)
    ftp_w = data.get("ftp_w")
    weight_kg = data.get("rider_weight_kg", None)

    print(f"📊  {len(theta)} points de courbe, puissancemètre : {'oui' if has_power else 'non'}")
    draw_spiral_chart(theta, p_vals, torque_vals, cadence_vals, has_power, ftp_w, labels, durations, weight_kg, svg_path)

    snippet = generate_html_snippet(svg_path, data)
    html_path.write_text(snippet, encoding="utf-8")
    print(f"✅  Snippet HTML → {html_path}")

if __name__ == "__main__":
    main()
