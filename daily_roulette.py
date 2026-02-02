import random
import requests
import os
import json

INTEGRANTES = ["Juan", "Catriel", "Christian", "Sol", "Luis", "Mati", "Angel"]

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")

def run_roulette():
    seleccionados = random.sample(INTEGRANTES, 2)
    principal, suplente = seleccionados[0], seleccionados[1]

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
            "footer": {"text": "Daily Bot 🚀"}
        }]
    }

    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))

    if response.status_code in [200, 201]:
        print(f"✅ Éxito: {principal} y {suplente} asignados.")
    else:
        print(f"❌ Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    run_roulette()