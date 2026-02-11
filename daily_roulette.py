import random
import requests
import os
import json
from datetime import datetime

INTEGRANTES = ["Juan", "Catriel", "Christian", "Sol", "Luis", "Mati", "Angel"]
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {"this_week": [], "last_week": [], "week_num": -1}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def run_roulette():
    history = load_history()
    today = datetime.now()
    current_week = today.isocalendar()[1]

    if history["week_num"] != current_week:
        history["last_week"] = history["this_week"]
        history["this_week"] = []
        history["week_num"] = current_week

    candidatos = [m for m in INTEGRANTES if m not in history["this_week"]]

    prioridad = [m for m in candidatos if m not in history["last_week"]]

    if prioridad:
        principal = random.choice(prioridad)
    else:
        principal = random.choice(candidatos)

    suplente = random.choice([m for m in INTEGRANTES if m != principal])

    history["this_week"].append(principal)
    save_history(history)

    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    
    payload = {
        "embeds": [{
            "title": "🎲 Ruleta de la Daily",
            "description": "¡El destino ha decidido los responsables de las notas de hoy!",
            "color": 3447003,
            "fields": [
                {"name": "📝 Principal", "value": f"**{principal}**", "inline": True},
                {"name": "🛡️ Suplente", "value": f"**{suplente}**", "inline": True}
            ],
            "footer": {"text": f"Semana {current_week} • Daily Bot 🚀"}
        }]
    }

    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        print(f"✅ Éxito: {principal} (Principal) y {suplente} (Suplente).")
    else:
        print(f"❌ Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    run_roulette()