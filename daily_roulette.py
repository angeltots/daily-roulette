import os
import random
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Configuración desde Secretos de GitHub / Variables de Entorno
MONGO_URI = os.getenv('MONGO_URI') # ¡Asegurate de agregar esta en GitHub Secrets!
DB_NAME = "daily_bot_db"
COLLECTION_NAME = "history"

DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID')

def get_mongo_client():
    client = MongoClient(MONGO_URI)
    return client[DB_NAME][COLLECTION_NAME]

def get_team_members():
    # Podés hardcodearlos acá o traerlos de otra colección de Mongo
    return ["Persona 1", "Persona 2", "Persona 3", "Persona 4"]

def run_roulette():
    collection = get_mongo_client()
    team = get_team_members()
    
    # 1. Obtener historial de Mongo
    history_doc = collection.find_one({"type": "daily_history"})
    past_winners = history_doc.get("winners", []) if history_doc else []

    # 2. Filtrar disponibles (los que no salieron en la última ronda)
    available = [m for m in team if m not in past_winners]
    
    # Si todos ya salieron, resetear ciclo
    if not available:
        available = team
        past_winners = []

    # 3. Elegir ganador
    winner = random.choice(available)
    past_winners.append(winner)

    # 4. Guardar nuevo historial en Mongo
    collection.update_one(
        {"type": "daily_history"},
        {"$set": {"winners": past_winners}},
        upsert=True
    )

    # 5. Enviar a Discord (Webhook o API)
    message = f"🎲 **Plan B Activado**\nEl encargado de la daily hoy es: **{winner}**"
    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    requests.post(url, headers=headers, json={"content": message})

if __name__ == "__main__":
    run_roulette()