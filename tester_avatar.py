#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
from pathlib import Path

import requests

from core.config import (
    GROQ_API_KEY,
    GROQ_MODEL
)

# =========================================================
# CONFIG
# =========================================================

IMAGE_PATH = "avatar_base.png"

PROMPT = """
You are a recoloring engine.

Recolor the cyclist avatar.

Rules:
- preserve pose
- preserve outlines
- preserve proportions
- preserve style
- only recolor

Colors:
- skin: caucasian pink
- helmet: red
- jersey: cyan blue
- gloves: white
- shorts: dark graphite
- socks: neon yellow
- shoes: black
"""

# =========================================================
# IMAGE -> BASE64
# =========================================================

def image_to_base64(path: str) -> str:

    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# =========================================================
# MAIN
# =========================================================

def main():

    image_b64 = image_to_base64(IMAGE_PATH)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GROQ_MODEL,

        "messages": [
            {
                "role": "user",

                "content": [
                    {
                        "type": "text",
                        "text": PROMPT
                    },

                    {
                        "type": "image_url",

                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    }
                ]
            }
        ],

        "temperature": 0.2,
        "max_tokens": 1024
    }

    print("Sending request...")
    print()

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=120
    )

    print("STATUS:", response.status_code)
    print()

    data = response.json()

    print(json.dumps(data, indent=2))


# =========================================================

if __name__ == "__main__":
    main()
