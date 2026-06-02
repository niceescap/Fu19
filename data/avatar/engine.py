"""
engine.py — Avatar FJC colorization engine
~/fjc/data/avatar/engine.py

Usage:
  python engine.py                              # rendu avec config.json courant
  python engine.py --reset                      # remet config.json aux valeurs grises par défaut
  python engine.py --layer jersey --color #0055cc   # modifie un calque et rend
  python engine.py --save equipe_a              # sauvegarde config.json → presets/equipe_a.json
  python engine.py --config presets/equipe_a.json   # charge un preset
  python engine.py --output ~/fjc/outputs/test.png  # chemin de sortie custom
"""

import json
import argparse
import colorsys
import shutil
import numpy as np
from pathlib import Path
from datetime import datetime
from PIL import Image


# ── Chemins ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent                  # ~/fjc/data/avatar/
TIFF_DIR    = BASE_DIR / "avatiff"
CONFIG_PATH = BASE_DIR / "config.json"
PRESETS_DIR = BASE_DIR / "presets"
OUTPUT_DIR  = BASE_DIR / "outputs"

OUTPUT_DIR.mkdir(exist_ok=True)
PRESETS_DIR.mkdir(exist_ok=True)


# ── Valeurs grises par défaut (référence immuable) ─────────────────────────────
DEFAULTS = {
    "stack_order": [
        "background",
        "sketch",
        "shoes",
        "socks",
        "short",
        "skin",
        "gloves",
        "jersey",
        "helmet",
        "glasses",
        "screen",
        "hairs"
    ],
    "layers": {
        "background": {
            "label":      "Fond",
            "file":       "Background.tiff",
            "colorize":   True,
            "base_color": "#ffffff",
            "opacity":    1.0
        },
        "sketch": {
            "label":      "Contours & ombre",
            "file":       "sketch.tiff",
            "colorize":   True,
            "base_color": "#444444",
            "opacity":    1.0
        },
        "shoes": {
            "label":      "Chaussures",
            "file":       "shoes.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "socks": {
            "label":      "Chaussettes",
            "file":       "socks.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "short": {
            "label":      "Cuissard",
            "file":       "short.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "skin": {
            "label":      "Peau",
            "file":       "skin.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "gloves": {
            "label":      "Gants",
            "file":       "gloves.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "jersey": {
            "label":      "Maillot",
            "file":       "jersey.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "helmet": {
            "label":      "Casque",
            "file":       "helmet.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "glasses": {
            "label":      "Monture lunettes",
            "file":       "glasses.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "screen": {
            "label":      "Écran lunettes",
            "file":       "screen.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        },
        "hairs": {
            "label":      "Cheveux",
            "file":       "hairs.tiff",
            "colorize":   True,
            "base_color": "#c4c4c4",
            "opacity":    1.0
        }
    }
}

# ── Helpers couleur ────────────────────────────────────────────────────────────
def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def hls_to_rgb_vec(h, l, s):
    """HLS → RGB vectorisé numpy. Entrées : arrays 2D float [0..1]."""
    c  = (1.0 - np.abs(2.0 * l - 1.0)) * s
    h6 = h * 6.0
    x  = c * (1.0 - np.abs(h6 % 2.0 - 1.0))
    m  = l - c / 2.0
    r  = np.zeros_like(l)
    g  = np.zeros_like(l)
    b  = np.zeros_like(l)
    for i, (r0, g0, b0) in enumerate([
        (c, x, 0), (x, c, 0), (0, c, x),
        (0, x, c), (x, 0, c), (c, 0, x)
    ]):
        mask = (h6 >= i) & (h6 < i + 1)
        r[mask] = r0[mask] if hasattr(r0, '__len__') else r0
        g[mask] = g0[mask] if hasattr(g0, '__len__') else g0
        b[mask] = b0[mask] if hasattr(b0, '__len__') else b0
    return (r + m) * 255, (g + m) * 255, (b + m) * 255


def colorize_layer(img: Image.Image, target_hex: str, opacity: float = 1.0) -> Image.Image:
    """
    Colorise un calque RGBA vers target_hex.
    Conserve le ratio de luminosité de chaque pixel gris source.
    Les pixels transparents restent transparents.
    """
    img = img.convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    alpha = arr[:, :, 3]

    # Luminosité normalisée depuis le canal rouge (R=G=B pour les gris)
    lum = arr[:, :, 0] / 255.0

    # Couleur cible → espace HLS
    tr, tg, tb   = hex_to_rgb(target_hex)
    th, tl, ts   = colorsys.rgb_to_hls(tr, tg, tb)

    # Nouvelle luminosité : ratio source appliqué à la luminosité cible
    # * 1.6 pour préserver les hautes lumières sans les écraser
    new_l = np.clip(lum * (tl * 1.6), 0.0, 1.0)

    r_new, g_new, b_new = hls_to_rgb_vec(
        np.full_like(lum, th),
        new_l,
        np.full_like(lum, ts)
    )

    out = np.zeros_like(arr)
    out[:, :, 0] = np.clip(r_new, 0, 255)
    out[:, :, 1] = np.clip(g_new, 0, 255)
    out[:, :, 2] = np.clip(b_new, 0, 255)
    out[:, :, 3] = np.clip(alpha * opacity, 0, 255)

    return Image.fromarray(out.astype(np.uint8), "RGBA")


# ── Build ──────────────────────────────────────────────────────────────────────
def build_avatar(config: dict) -> Image.Image:
    canvas = None
    for layer_id in config["stack_order"]:
        layer = config["layers"].get(layer_id)
        if not layer:
            print(f"  ⚠️  '{layer_id}' absent de la config, ignoré")
            continue
        tiff_path = TIFF_DIR / layer["file"]
        if not tiff_path.exists():
            print(f"  ⚠️  fichier manquant : {tiff_path.name}, ignoré")
            continue
        img = Image.open(tiff_path)
        if canvas is None:
            canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
        if layer.get("colorize", False):
            img = colorize_layer(img, layer["base_color"], layer.get("opacity", 1.0))
        else:
            img = img.convert("RGBA")
        print(f"  ✅ {layer_id:16s} → {layer['base_color']}")
        canvas = Image.alpha_composite(canvas, img)
    return canvas


# ── Config helpers ─────────────────────────────────────────────────────────────
def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_config(config: dict, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def reset_config():
    """Régénère config.json depuis DEFAULTS."""
    save_config(DEFAULTS, CONFIG_PATH)
    print(f"✅ config.json réinitialisé aux valeurs par défaut → {CONFIG_PATH}")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Avatar FJC engine")
    parser.add_argument("--config",  default=None,
                        help="Chemin vers un preset (ex: presets/equipe_a.json)")
    parser.add_argument("--reset",   action="store_true",
                        help="Remet config.json aux valeurs grises par défaut")
    parser.add_argument("--layer",   default=None,
                        help="Nom du calque à overrider (ex: jersey)")
    parser.add_argument("--color",   default=None,
                        help="Couleur hex (ex: #0055cc)")
    parser.add_argument("--save",    default=None,
                        help="Sauvegarde config.json courant → presets/<nom>.json")
    parser.add_argument("--output",  default=None,
                        help="Chemin PNG de sortie")
    args = parser.parse_args()

    # -- Reset
    if args.reset:
        reset_config()
        return

    # -- Sauvegarde preset
    if args.save:
        dest = PRESETS_DIR / f"{args.save}.json"
        shutil.copy(CONFIG_PATH, dest)
        print(f"✅ Preset sauvegardé → {dest}")
        return

    # -- Chargement config
    config_path = Path(args.config) if args.config else CONFIG_PATH
    if not config_path.exists():
        print(f"⚠️  {config_path} introuvable, génération depuis les défauts...")
        reset_config()
    config = load_config(config_path)

    # -- Override calque
    if args.layer and args.color:
        if args.layer in config["layers"]:
            config["layers"][args.layer]["base_color"] = args.color
            print(f"  🎨 override : {args.layer} → {args.color}")
            # Persisté dans config.json courant seulement si on utilisait config.json
            if not args.config:
                save_config(config, CONFIG_PATH)
        else:
            print(f"  ❌ calque inconnu : {args.layer}")
            print(f"     Calques disponibles : {list(config['layers'].keys())}")
            return

    # -- Rendu
    print("\n▶ Construction avatar...")
    avatar = build_avatar(config)

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.output) if args.output else OUTPUT_DIR / f"avatar_{ts}.png"
    avatar.save(str(out), "PNG")
    print(f"\n✅ Export → {out}")


if __name__ == "__main__":
    main()
