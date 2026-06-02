#!/usr/bin/env python3
"""
3d_grapher.py — Représentation isométrique 3D « Radar Hélice » (Agent 2b)
Lit fit_analysis.json → génère un SVG artistique avec :
  - un axe central (le temps / durée)
  - 8 ailettes disposées régulièrement autour de l’axe
  - sur chaque ailette, une diagonale servant d’échelle de valeur
  - points de données (Pmax, Couple, Cadence) placés sur ces échelles
  - trois courbes interpolées reliant les points correspondants
Aucune dépendance à matplotlib.
"""

import json
import math
import sys
from pathlib import Path

# ==============================================================================
# Configuration
# ==============================================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from core.config import FIT_OUTPUT_FILE, HELI_DATAS, DEBUG
except ImportError:
    FIT_OUTPUT_FILE = PROJECT_ROOT / "data" / "fit_analysis.json"
    HELI_DATAS = PROJECT_ROOT / "data" / "metrics" / "rider_helix.svg"
    DEBUG = True

# ==============================================================================
# Paramètres visuels
# ==============================================================================
WIDTH, HEIGHT = 1000, 1000
ISO_ANGLE = math.radians(30)          # angle de l'axe central (direction isométrique)
ISO_SLOPE = math.tan(ISO_ANGLE)       # pente de l'axe

# Echelles
AXIS_LENGTH = 360                      # longueur des axes de valeur (px)
AXIS_CENTER = (WIDTH * 0.5, HEIGHT * 0.8)  # point de départ de l'axe central (en bas)

# Nombre d'ailettes (correspond aux durées disponibles, max 8)
MAX_FINS = 8
FIN_ANGLE_STEP = 2 * math.pi / MAX_FINS  # 45°

# Couleurs
COLORS = {
    "power":   "#ff4d4d",
    "torque":  "#4dff4d",
    "cadence": "#4da6ff",
}
CURVE_WIDTH = 3
POINT_RADIUS = 5

# ==============================================================================
# Mapping des durées (secondes) → angle horaire (pour ordre)
# ==============================================================================
DURATION_ANGLES = {
    5:    math.pi / 6,
    15:   math.pi / 3,
    30:   math.pi / 2,
    60:   2 * math.pi / 3,
    300:  5 * math.pi / 6,
    900:  math.pi,
    1800: 3 * math.pi / 2,
    3600: 11 * math.pi / 6,
}

# ==============================================================================
# Lecture et extraction des données
# ==============================================================================
def load_analysis(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def prepare_spiral_data(data: dict):
    """
    Retourne les listes ordonnées par angle (12h = haut, sens horaire)
    theta : angles (radians)
    p_wkg, torque, cadence : listes parallèles (None si absent)
    has_power : bool
    labels : étiquettes de durée
    """
    power_curve = data.get("power_curve")
    cadence_curve = data.get("cadence_curve")

    available = set()
    if power_curve: available.update(power_curve.keys())
    if cadence_curve: available.update(cadence_curve.keys())
    if not available:
        raise ValueError("Aucune courbe disponible.")

    ordered = []
    for dur_s, angle in sorted(DURATION_ANGLES.items(), key=lambda x: x[1]):
        lbl = f"{dur_s}s" if dur_s < 60 else (f"{dur_s//60}min" if dur_s % 60 == 0 else f"{dur_s/60:.1f}min")
        if lbl in available:
            ordered.append((dur_s, angle, lbl))

    theta = [a for _, a, _ in ordered]
    labels = [l for _, _, l in ordered]
    p_wkg, torque, cadence = [], [], []
    for dur_s, _, lbl in ordered:
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
    return theta, p_wkg, torque, cadence, has_power, labels

# ==============================================================================
# Projection isométrique 3D → 2D
# ==============================================================================
def iso_project(x, y, z):
    """
    Projection isométrique classique :
      x_écran = (x - y) * cos(30°)
      y_écran = (x + y) * sin(30°) - z
    On centre ensuite.
    """
    cos30 = math.cos(math.radians(30))
    sin30 = math.sin(math.radians(30))
    ex = (x - y) * cos30
    ey = (x + y) * sin30 - z
    return WIDTH/2 + ex, HEIGHT/2 - ey   # Y inversé

# ==============================================================================
# Construction des ailettes et des axes
# ==============================================================================
def generate_helix_svg(theta, p_wkg, torque, cadence, has_power, labels):
    # Normalisation (0..1)
    max_p = max((v for v in p_wkg if v is not None), default=0.0)
    max_t = max((v for v in torque if v is not None), default=0.0)
    max_c = max(cadence) if cadence else 0.0

    def norm_p(v): return v/max_p if max_p>0 and v is not None else 0.0
    def norm_t(v): return v/max_t if max_t>0 and v is not None else 0.0
    def norm_c(v): return v/max_c if max_c>0 else 0.0

    # Combien d'ailettes réelles (min 3, max 8)
    n_fins = len(theta)
    if n_fins < 3:
        # si moins de 3 durées, on duplique la première pour avoir au moins 3
        theta = theta * 3
        labels = labels * 3
        p_wkg = p_wkg * 3
        torque = torque * 3
        cadence = cadence * 3
        n_fins = len(theta)

    # Angle entre chaque ailette autour de l'axe central (isométrique)
    # Nous allons répartir les durées disponibles uniformément sur 360°
    # Si moins de 8, on les espace régulièrement.
    angle_step = 2 * math.pi / n_fins

    # L'axe central est une droite 3D : x = t * ux, y = t * uy, z = t * uz
    # On choisit un vecteur unitaire orienté dans la direction isométrique
    # Pour un axe qui "monte" vers la droite-haut en projection,
    # on peut prendre ux = 1, uy = 1, uz = 1, normalisé.
    u = math.sqrt(3)
    ux, uy, uz = 1/u, 1/u, 1/u

    # Pour chaque durée i (0..n_fins-1), on définit un plan passant par l'axe central
    # et tourné d'un angle φ_i = i * angle_step autour de l'axe.
    # On veut que le plan contienne le vecteur axe et un vecteur radial perpendiculaire.
    # On construit un repère local : axe = (ux, uy, uz)
    # On choisit un vecteur arbitraire non colinéaire, ex: (0, -uz, uy) pour le premier plan,
    # puis on le fait tourner autour de l'axe par une rotation d'angle φ_i.

    # Vecteur radial de base (perpendiculaire à l'axe)
    v0_x = 0
    v0_y = -uz
    v0_z = uy
    # Normalisation
    norm_v0 = math.sqrt(v0_x**2 + v0_y**2 + v0_z**2)
    v0_x /= norm_v0
    v0_y /= norm_v0
    v0_z /= norm_v0

    # Pour chaque ailette, on calcule le vecteur radial après rotation φ
    def rotate_around_axis(vx, vy, vz, angle):
        # Formule de Rodrigues pour rotation autour de l'axe (ux, uy, uz)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        dot = vx*ux + vy*uy + vz*uz
        rx = vx*cos_a + (uy*vz - uz*vy)*sin_a + ux*dot*(1-cos_a)
        ry = vy*cos_a + (uz*vx - ux*vz)*sin_a + uy*dot*(1-cos_a)
        rz = vz*cos_a + (ux*vy - uy*vx)*sin_a + uz*dot*(1-cos_a)
        return rx, ry, rz

    # Préparer les points 3D pour chaque grandeur
    points3d_p = []
    points3d_t = []
    points3d_c = []

    for i in range(n_fins):
        # angle de l'ailette
        phi = i * angle_step
        rad_x, rad_y, rad_z = rotate_around_axis(v0_x, v0_y, v0_z, phi)

        # Position le long de l'axe central pour cette durée (proportionnelle à i)
        # On fait correspondre l'axe central au temps : l'extrémité supérieure (i grand) = durée longue
        # On choisit un paramètre t entre 0 et 1 (0 pour la première durée, 1 pour la dernière)
        t = i / (n_fins - 1) if n_fins > 1 else 0.5
        # Coordonnées du point sur l'axe central
        ax_x = t * ux * AXIS_LENGTH
        ax_y = t * uy * AXIS_LENGTH
        ax_z = t * uz * AXIS_LENGTH

        # Pour chaque métrique, le point est décalé radialement de la valeur normalisée
        def point_on_fin(value_norm):
            # distance radiale = value_norm * AXIS_LENGTH
            r = value_norm * AXIS_LENGTH * 0.8  # facteur 0.8 pour ne pas dépasser
            return (ax_x + rad_x * r, ax_y + rad_y * r, ax_z + rad_z * r)

        if has_power and p_wkg[i] is not None:
            points3d_p.append(point_on_fin(norm_p(p_wkg[i])))
            points3d_t.append(point_on_fin(norm_t(torque[i])))
        points3d_c.append(point_on_fin(norm_c(cadence[i])))

    # Projection 2D des points
    proj_p = [iso_project(x,y,z) for x,y,z in points3d_p] if points3d_p else []
    proj_t = [iso_project(x,y,z) for x,y,z in points3d_t] if points3d_t else []
    proj_c = [iso_project(x,y,z) for x,y,z in points3d_c] if points3d_c else []

    # Projeter aussi l'axe central et les axes des ailettes pour le dessin
    axis_pts_2d = []
    for t in [0, 1]:
        x = t * ux * AXIS_LENGTH
        y = t * uy * AXIS_LENGTH
        z = t * uz * AXIS_LENGTH
        axis_pts_2d.append(iso_project(x, y, z))

    # Dessiner les ailettes (lignes radiales) pour chaque durée
    fin_lines = []   # liste de (start_2d, end_2d) pour chaque ailette (axe de valeur)
    for i in range(n_fins):
        t = i / (n_fins - 1) if n_fins > 1 else 0.5
        ax_x = t * ux * AXIS_LENGTH
        ax_y = t * uy * AXIS_LENGTH
        ax_z = t * uz * AXIS_LENGTH
        phi = i * angle_step
        rad_x, rad_y, rad_z = rotate_around_axis(v0_x, v0_y, v0_z, phi)
        # Point de départ sur l'axe
        start = iso_project(ax_x, ax_y, ax_z)
        # Point d'arrivée au bout de l'axe radial (longueur AXIS_LENGTH)
        end_x = ax_x + rad_x * AXIS_LENGTH
        end_y = ax_y + rad_y * AXIS_LENGTH
        end_z = ax_z + rad_z * AXIS_LENGTH
        end = iso_project(end_x, end_y, end_z)
        fin_lines.append((start, end))

    # Interpolation 2D des courbes (spline cubique via scipy si disponible, sinon Catmull-Rom)
    def interpolate_curve(points):
        if len(points) < 2:
            return points
        # Utiliser scipy si présent
        try:
            from scipy.interpolate import splprep, splev
            import numpy as np
            pts = np.array(points)
            # On ajoute un peu de lissage si assez de points
            k = min(3, len(points)-1)
            tck, u = splprep([pts[:,0], pts[:,1]], s=0, k=k)
            u_fine = np.linspace(0, 1, 100)
            x_fine, y_fine = splev(u_fine, tck)
            return list(zip(x_fine, y_fine))
        except ImportError:
            pass
        # Fallback : courbe de Catmull-Rom (simplifiée)
        n = len(points)
        if n == 2:
            return points
        result = []
        for i in range(n-1):
            p0 = points[i-1] if i>0 else points[0]
            p1 = points[i]
            p2 = points[i+1]
            p3 = points[i+2] if i+2 < n else points[i+1]
            for t in [j/20 for j in range(21)]:
                t2 = t*t
                t3 = t2*t
                x = 0.5 * ((2*p1[0]) +
                          (-p0[0]+p2[0])*t +
                          (2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2 +
                          (-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3)
                y = 0.5 * ((2*p1[1]) +
                          (-p0[1]+p2[1])*t +
                          (2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2 +
                          (-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3)
                result.append((x, y))
        result.append(points[-1])
        return result

    curve_p = interpolate_curve(proj_p) if proj_p else []
    curve_t = interpolate_curve(proj_t) if proj_t else []
    curve_c = interpolate_curve(proj_c) if proj_c else []

    # ── Génération du SVG ──
    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">')
    svg.append('<defs>')
    svg.append('''
        <filter id="glow">
            <feGaussianBlur stdDeviation="2" result="blur"/>
            <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
        <filter id="shadow">
            <feDropShadow dx="2" dy="2" stdDeviation="3" flood-color="#000" flood-opacity="0.5"/>
        </filter>
        <radialGradient id="bgGrad" cx="50%" cy="50%" r="70%">
            <stop offset="0%" stop-color="#0a0a1a"/>
            <stop offset="100%" stop-color="#020210"/>
        </radialGradient>
    ''')
    svg.append('</defs>')
    svg.append(f'<rect width="100%" height="100%" fill="url(#bgGrad)"/>')

    # Dessiner l'axe central (ligne épaisse)
    svg.append(f'<line x1="{axis_pts_2d[0][0]:.1f}" y1="{axis_pts_2d[0][1]:.1f}" '
              f'x2="{axis_pts_2d[1][0]:.1f}" y2="{axis_pts_2d[1][1]:.1f}" '
              f'stroke="#888" stroke-width="4" filter="url(#shadow)"/>')

    # Dessiner les ailettes (axes de valeur)
    for start, end in fin_lines:
        svg.append(f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
                  f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" '
                  f'stroke="#555" stroke-width="1" stroke-dasharray="4,2"/>')

    # Dessiner les courbes interpolées
    def draw_curve(curve, color, width=CURVE_WIDTH):
        if not curve: return
        d = "M " + " L ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in curve)
        svg.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                   f'filter="url(#glow)"/>')

    draw_curve(curve_c, COLORS["cadence"])
    if has_power:
        draw_curve(curve_p, COLORS["power"])
        draw_curve(curve_t, COLORS["torque"])

    # Dessiner les points de données (cercles) et les valeurs
    for i in range(n_fins):
        if proj_c:
            px, py = proj_c[i]
            svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{POINT_RADIUS}" '
                       f'fill="{COLORS["cadence"]}" stroke="white" stroke-width="1"/>')
            # texte
            val = cadence[i]
            txt = f"{val:.0f}"
            svg.append(f'<text x="{px:.1f}" y="{py-12:.1f}" fill="white" font-size="10" '
                       f'text-anchor="middle" font-family="sans-serif" filter="url(#glow)">{txt}</text>')
        if has_power and proj_p:
            px, py = proj_p[i]
            svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{POINT_RADIUS}" '
                       f'fill="{COLORS["power"]}" stroke="white" stroke-width="1"/>')
            val = p_wkg[i]
            txt = f"{val:.2f}" if val and val < 10 else f"{val:.1f}"
            svg.append(f'<text x="{px:.1f}" y="{py-12:.1f}" fill="white" font-size="10" '
                       f'text-anchor="middle" font-family="sans-serif" filter="url(#glow)">{txt}</text>')
        if has_power and proj_t:
            px, py = proj_t[i]
            svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{POINT_RADIUS}" '
                       f'fill="{COLORS["torque"]}" stroke="white" stroke-width="1"/>')
            val = torque[i]
            txt = f"{val:.2f}" if val and val < 10 else f"{val:.1f}"
            svg.append(f'<text x="{px:.1f}" y="{py-12:.1f}" fill="white" font-size="10" '
                       f'text-anchor="middle" font-family="sans-serif" filter="url(#glow)">{txt}</text>')

    # Légende
    lg_x, lg_y = 50, 50
    items = [("Cadence (rpm)", COLORS["cadence"])]
    if has_power:
        items += [("Pmax (W/kg)", COLORS["power"]), ("Couple (N·m)", COLORS["torque"])]
    for j, (label, col) in enumerate(items):
        y = lg_y + j*30
        svg.append(f'<circle cx="{lg_x}" cy="{y}" r="8" fill="{col}" filter="url(#glow)"/>')
        svg.append(f'<text x="{lg_x+20}" y="{y+5}" fill="white" font-size="14" font-family="sans-serif">{label}</text>')

    svg.append('</svg>')
    return "\n".join(svg)

# ==============================================================================
# Point d'entrée
# ==============================================================================
def main():
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else FIT_OUTPUT_FILE
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HELI_DATAS

    data = load_analysis(json_path)
    theta, p_wkg, torque, cadence, has_power, labels = prepare_spiral_data(data)

    if DEBUG:
        print(f"[3d_grapher] {len(theta)} durées, puissancemètre={'oui' if has_power else 'non'}")

    svg = generate_helix_svg(theta, p_wkg, torque, cadence, has_power, labels)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[3d_grapher] ✅ Graphique radar 3D → {output_path}")

if __name__ == "__main__":
    main()
