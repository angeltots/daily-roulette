import discord
from discord.ext import commands, tasks
import requests
import os
import random
import datetime as dt
import pytz 
from pymongo import MongoClient
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CLICKUP_TOKEN = os.getenv("CLICKUP_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
TEAM_ID = "31625254"

ARG_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

INTEGRANTES_DATA = {
    "Juan Carlos Urquiza": "1460706682274451467",
    "Catriel Caruso": "1311265389723783179",
    "Angel Mendez": "1362026774988591299",
    "Sol Gosso": "1184514902963015710",
    "Luis Márquez": "1302037681227825215",
    "Matias Camiletti": "1043717500128481310",
    "Christian Ferrer": "1433452588183064658"
}
INTEGRANTES = list(INTEGRANTES_DATA.keys())

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["kupyo_bot"] 
history_collection = db["historial_dailys"] 
logs_collection = db["logs_ejecucion"] 

def get_now_arg():
    return dt.datetime.now(ARG_TZ)

def get_db_history():
    doc = history_collection.find_one({"_id": "estado_ruleta"})
    if not doc:
        doc = {"_id": "estado_ruleta", "this_week": [], "last_week": [], "week_num": -1}
        history_collection.insert_one(doc)
    return doc

def save_db_history(history_data):
    history_collection.update_one({"_id": "estado_ruleta"}, {"$set": history_data}, upsert=True)

def guardar_log(evento, detalles):
    ahora = get_now_arg()
    log_doc = {
        "fecha": ahora,
        "fecha_str": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "evento": evento,
        "detalles": detalles
    }
    logs_collection.insert_one(log_doc)
    print(f"📝 Log guardado: {evento}")

def get_mention(nombre):
    user_id = INTEGRANTES_DATA.get(nombre)
    return f"<@{user_id}>" if user_id else nombre

def get_clickup_availability():
    if not CLICKUP_TOKEN:
        return None, {}, []
    url = f"https://api.clickup.com/api/v2/team/{TEAM_ID}/task"
    ahora_arg = get_now_arg()
    now_ms = int(ahora_arg.timestamp() * 1000)
    headers = {"Authorization": CLICKUP_TOKEN, "Content-Type": "application/json"}
    params = {"include_closed": "true", "subtasks": "true"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        tasks_data = response.json().get("tasks", [])
        ausentes, cumpleañeros, motivo_cancelacion = {}, [], None 

        for task in tasks_data:
            name = task["name"].lower()
            start, due = task.get("start_date"), task.get("due_date")
            en_rango = False 
            if start and due:
                en_rango = int(start) <= now_ms <= int(due)
            elif due and not start:
                due_date_dt = dt.datetime.fromtimestamp(int(due) / 1000, tz=dt.timezone.utc).astimezone(ARG_TZ)
                if due_date_dt.date() == ahora_arg.date(): en_rango = True
            
            if en_rango:
                if "feriado" in name or "argentina" in name: motivo_cancelacion = "Feriado Nacional 🇦🇷"
                elif "free meetings day" in name: motivo_cancelacion = "Free Meetings Day 🚫📅"
                for persona in INTEGRANTES:
                    p = persona.lower().split()
                    if p[0] in name or p[-1] in name or (p[0] == "christian" and "chris" in name):
                        if "half" in name: ausentes[persona] = "Half People Day 🌗"
                        elif "vacaciones" in name: ausentes[persona] = "Vacaciones ✈️"
                        elif "birth" in name or "cumple" in name:
                            ausentes[persona] = "Cumpleaños 🎉"
                            if persona not in cumpleañeros: cumpleañeros.append(persona)
                        else: ausentes[persona] = "Ausente 🛌"
        return motivo_cancelacion, ausentes, cumpleañeros
    except Exception as e:
        return None, {}, []

class SelectorNotas(discord.ui.Select):
    def __init__(self):
        opciones = [discord.SelectOption(label=nombre) for nombre in INTEGRANTES]
        super().__init__(
            placeholder="¿Alguien más tomó las notas hoy?",
            min_values=1, max_values=1, options=opciones,
            custom_id="selector_notas_v1" 
        )

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        await interaction.response.edit_message(view=self.view)

        try:
            embed = interaction.message.embeds[0]
            principal_asignado = "Desconocido"
            for field in embed.fields:
                if "Principal" in field.name:
                    u_id = field.value.replace("<@", "").replace(">", "").replace("!", "")
                    for n, uid in INTEGRANTES_DATA.items():
                        if uid == u_id: principal_asignado = n; break
            
            anotador_real = self.values[0]
            hist = get_db_history()
            if principal_asignado in hist["this_week"]: hist["this_week"].remove(principal_asignado)
            if anotador_real not in hist["this_week"]: hist["this_week"].append(anotador_real)
            
            save_db_history(hist) 
            guardar_log("Cambio Manual de Notas", f"De {principal_asignado} a {anotador_real}")
            await interaction.followup.send(f"✅ Notas registradas a nombre de **{anotador_real}**.", ephemeral=True)
        except Exception as e:
            print(f"🔥 Error: {e}")

class VistaRuleta(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 
        self.add_item(SelectorNotas())

async def ejecutar_ruleta(canal):
    motivo, ausentes_dict, cumples = get_clickup_availability()
    history = get_db_history()
    today = get_now_arg()
    current_week = today.isocalendar()[1]
    
    embed = discord.Embed(title="🎲 Ruleta de la Daily", color=0x3498DB)
    embed.set_footer(text=f"Semana {current_week} • ART: {today.strftime('%d/%m/%Y')}")
    
    if motivo:
        await canal.send(content=f"🛑 Hoy no hay ruleta: **{motivo}**.", embed=embed)
        return

    if history["week_num"] != current_week:
        history["last_week"], history["this_week"], history["week_num"] = history["this_week"], [], current_week

    candidatos = [m for m in INTEGRANTES if m not in history["this_week"] and m not in ausentes_dict]

    if not candidatos:
        await canal.send(content="⚠️ No hay candidatos disponibles hoy.", embed=embed)
    else:
        prioridad = [m for m in candidatos if m not in history["last_week"]]
        principal = random.choice(prioridad) if prioridad else random.choice(candidatos)
        posibles_suplentes = [m for m in INTEGRANTES if m != principal and m not in ausentes_dict]
        suplente = random.choice(posibles_suplentes) if posibles_suplentes else "N/A"

        history["this_week"].append(principal)
        save_db_history(history)

        mencion_p, mencion_s = get_mention(principal), get_mention(suplente)
        embed.description = "¡El destino ha decidido los responsables de las notas de hoy!"
        embed.add_field(name="📝 Principal", value=mencion_p, inline=True)
        embed.add_field(name="🛡️ Suplente", value=mencion_s, inline=True)
        
        if ausentes_dict:
            txt = "\n".join([f"• **{p}**: {m}" for p, m in ausentes_dict.items()])
            embed.add_field(name="📋 Novedades", value=txt, inline=False)
        if cumples:
            txt = "\n".join([f"🎉 ¡Feliz cumple {get_mention(c)}!" for c in cumples])
            embed.add_field(name="🎁 Cumpleaños", value=txt, inline=False)

        guardar_log("Sorteo Realizado", f"P: {principal} | S: {suplente}")
        await canal.send(content=f"🔔 ¡Atención {mencion_p}! Te toca la daily.", embed=embed, view=VistaRuleta())

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(time=dt.time(hour=17, minute=30, tzinfo=dt.timezone.utc))
async def tarea_diaria_ruleta():
    if get_now_arg().weekday() <= 4:
        canal = bot.get_channel(int(DISCORD_CHANNEL_ID))
        if canal: await ejecutar_ruleta(canal)

@bot.event
async def on_ready():
    print(f"🚀 Bot {bot.user} encendido")
    bot.add_view(VistaRuleta()) # Registro de vista persistente
    if not tarea_diaria_ruleta.is_running(): tarea_diaria_ruleta.start()

@bot.command()
async def ruleta(ctx): await ejecutar_ruleta(ctx.channel)

if __name__ == "__main__":
    keep_alive() 
    bot.run(DISCORD_TOKEN)