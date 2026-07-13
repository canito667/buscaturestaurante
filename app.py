# -*- coding: utf-8 -*-
"""
BuscaTuRestaurante - Decisión rápida para almuerzo (Francia)
-------------------------------------------------------------
Problema que resuelve: "¿qué quieres comer?" -> "no sé" -> hambre ->
Uber Eats -> siempre lo mismo.

En vez de preguntarte "qué quieres", la app te PROPONE opciones ya filtradas
por señales reales de OpenStreetMap que funcionan como "recomendación
implícita de la comunidad" (no hay estrellas en OSM Francia, así que usamos
proxy honestos: frescura de los datos, para-llevar, opciones dietéticas y
completitud de la ficha). Y un botón "decídeme tú" rompe el bucle.

Flujo:
  1. Destino en Francia + radio.
  2. ¿Solo o acompañado? (cambia la recomendación)
  3. Filtros móviles: para llevar / sentarse / vegetariano-vegano / abierto ahora.
  4. La app clasifica por "Índice de Recomendación" y te muestra el Top.
  5. "No sé, decídeme tú" elige al azar entre los mejores.
"""

import streamlit as st
import requests
import time
import random
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:
    PARIS = None

HEADERS = {"User-Agent": "BuscaTuRestauranteApp/1.0 (demo almuerzo Francia)"}
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

UTIL_TAGS = [  # etiquetas que indican una ficha "cuidada" por la comunidad
    "website", "phone", "contact:facebook", "opening_hours", "cuisine",
    "wheelchair", "outdoor_seating", "indoor_seating", "takeaway",
    "diet:vegetarian", "diet:vegan", "addr:street",
]


# ---------------------------------------------------------------------------
# DATOS (internet -> OpenStreetMap)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_coordinates(location_query):
    try:
        params = {"q": location_query, "format": "json", "limit": 1}
        resp = requests.get(NOMINATIM_URL, params=params,
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None, None, ""
        top = data[0]
        return float(top["lat"]), float(top["lon"]), top.get("display_name", location_query)
    except Exception as e:
        st.exception(e)
        return None, None, ""


@st.cache_data(show_spinner=False)
def geocode_help(location_query):
    """Igual que get_coordinates pero devuelve también hasta 5 alternativas
    para que la UI proponga correcciones si la direccion esta mal/ambigua.
    Reintenta una vez si Nominatim devuelve vacio (rate-limit transitorio del
    servidor publico, frecuente en la nube que comparte IP)."""
    def _fetch():
        params = {"q": location_query, "format": "json", "limit": 5,
                  "addressdetails": 1}
        resp = requests.get(NOMINATIM_URL, params=params,
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    try:
        data = _fetch()
        if not data:  # posible rate-limit: espera y reintenta una vez
            time.sleep(1.5)
            data = _fetch()
        if not data:
            return None, None, "", []
        alts = [d.get("display_name", "") for d in data[1:6]]
        top = data[0]
        return (float(top["lat"]), float(top["lon"]),
                top.get("display_name", location_query), alts)
    except Exception:
        return None, None, "", []


@st.cache_data(show_spinner=False)
def get_restaurants_nearby(lat, lon, radius=1500):
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"~"restaurant|cafe|fast_food"](around:{radius},{lat},{lon});
      way["amenity"~"restaurant|cafe|fast_food"](around:{radius},{lat},{lon});
    );
    out center 300;
    """
    # Overpass es un servidor publico y a veces se satura (429 rate limit,
    # o 500/502/503/504 errores de gateway). Reintentamos ante todos esos
    # con espera creciente, para que el usuario no vea un error en seco.
    RETRIABLE = {429, 500, 502, 503, 504}
    elements = None
    for intento in range(4):
        try:
            resp = requests.post(OVERPASS_URL, data={"data": query},
                                headers=HEADERS, timeout=40)
            if resp.status_code in RETRIABLE:
                if intento == 3:
                    st.exception(RuntimeError(
                        f"Overpass no responde (HTTP {resp.status_code}). "
                        f"Reintenta en unos segundos."))
                    return []
                time.sleep(4 * (intento + 1))
                continue
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except Exception as e:
            if intento == 3:
                st.exception(e)
                return []
            time.sleep(4 * (intento + 1))

    out = []
    for el in (elements or []):
        tags = el.get("tags", {})
        if el["type"] == "way":
            elat = el.get("center", {}).get("lat")
            elon = el.get("center", {}).get("lon")
        else:
            elat = el.get("lat")
            elon = el.get("lon")

        calle = tags.get("addr:street", "")
        num = tags.get("addr:housenumber", "")
        ciudad = tags.get("addr:city", "")
        direccion = ", ".join(p for p in (calle, num, ciudad) if p) or "Dirección no disponible"

        out.append({
            "nombre": tags.get("name", "Sin nombre"),
            "cocina": tags.get("cuisine", "No especificada"),
            "direccion": direccion,
            "horario": tags.get("opening_hours", "No disponible"),
            "takeaway": tags.get("takeaway", "unknown"),       # yes/no/only/unknown
            "vegan": tags.get("diet:vegan", "no") == "yes",
            "vegetarian": tags.get("diet:vegetarian", "no") == "yes",
            "outdoor": tags.get("outdoor_seating", "no") == "yes",
            "indoor": tags.get("indoor_seating", "no") == "yes",
            "wheelchair": tags.get("wheelchair", "no") == "yes",
            "website": tags.get("website", ""),
            "check_date": tags.get("check_date", tags.get("survey:date", "")),
            "tags_count": sum(1 for t in UTIL_TAGS if t in tags),
            "lat": elat,
            "lon": elon,
        })
    return out


# ---------------------------------------------------------------------------
# "COMENTARIOS FAVORABLES" -> Índice de Recomendación (proxy honesto de OSM)
# ---------------------------------------------------------------------------
def compute_score(r, solo, takeaway_only, diet, open_now, lang="es"):
    """0-100 basado en señales abiertas de OSM.
    Devuelve (score, razones) donde 'razones' es una lista de textos cortos
    que explican en lenguaje claro por qué ese restaurante tiene esa nota.
    'lang' elige el idioma de esas razones (es/en/fr)."""
    def RZ(key, **kw):
        return REASONS[key][lang].format(**kw)
    score = 0
    razones = []

    # 1) Frescura de los datos: check_date reciente = sitio vigente y cuidado
    if r.get("check_date"):
        try:
            y = int(str(r["check_date"])[:4])
            age = datetime.now().year - y
            if age <= 2:
                score += 15
                razones.append(RZ("verif_fresco", y=y))
            elif age <= 4:
                score += 8
                razones.append(RZ("verif_old", y=y))
            else:
                score += 3
                razones.append(RZ("verif_ancien", y=y))
        except Exception:
            score += 5
            razones.append(RZ("verif_ilegible"))
    else:
        razones.append(RZ("no_verif"))

    # 2) Modo: solo (rapidez) vs acompañado (sentarse)
    if solo:
        if r["takeaway"] in ("yes", "only"):
            score += 18
            razones.append(RZ("takeaway_solo"))
        if r["cocina"] in ("fast_food", "sandwich", "pizza", "burger", "kebab"):
            score += 6
            razones.append(RZ("rapida"))
    else:
        if r["indoor"] or r["outdoor"]:
            score += 18
            razones.append(RZ("sentarse"))
        if r["takeaway"] in ("yes", "only"):
            score += 6
            razones.append(RZ("takeaway_acco"))

    # 3) Filtros móviles pedidos por el usuario
    if takeaway_only and r["takeaway"] not in ("yes", "only"):
        return 0, [RZ("no_takeaway")]
    if diet == "vegan" and not r["vegan"]:
        return 0, [RZ("no_vegan")]
    if diet == "vegetarian" and not (r["vegetarian"] or r["vegan"]):
        return 0, [RZ("no_veg")]
    if diet == "vegan" and r["vegan"]:
        score += 10
        razones.append(RZ("vegan_ok"))
    if diet == "vegetarian" and (r["vegetarian"] or r["vegan"]):
        score += 10
        razones.append(RZ("veg_ok"))
    # Filtro "abierto ahora": solo descarta si sabemos que esta CERRADO (False).
    # Si es None (horario ausente/ilegible), no lo ocultamos.
    if open_now and r.get("_abierto_ahora") is False:
        return 0, [RZ("cerrado")]

    # 4) Completitud de ficha = la comunidad lo valida / documenta
    tc = min(20, r["tags_count"] * 2)
    score += tc
    if tc >= 12:
        razones.append(RZ("ficha_buena", tc=tc))
    elif tc > 0:
        razones.append(RZ("ficha_parcial", tc=tc))

    # 5) Diversidad de cocina (evitar "siempre lo mismo")
    if r["cocina"] not in ("fast_food", "no especificada", ""):
        score += 5
        razones.append(RZ("variedad", c=r["cocina"]))

    return min(100, int(score)), razones



# ---------------------------------------------------------------------------
# ¿Abierto ahora? (parser ligero de opening_hours para la hora de París)
# ---------------------------------------------------------------------------
def is_open_now(opening_hours):
    """Heurístico de opening_hours de OSM para la hora actual en París.
    Devuelve True/False si se sabe; None si el horario está ausente o es
    ilegible (en ese caso NO se descarta en el filtro)."""
    if not opening_hours or PARIS is None:
        return None
    # OSM usa "Mo-Fr 09:00-18:00" (día y hora separados por ESPACIO).
    # Solo colapsamos espacios multiples; NO los borramos todos.
    oh = " ".join(opening_hours.lower().split())
    now = datetime.now(PARIS)
    dias = ["mo", "tu", "we", "th", "fr", "sa", "su"]
    hoy = dias[now.weekday()]
    hhmm = now.hour * 60 + now.minute

    if "24/7" in oh:
        return True

    def a_minutos(hhmm_str):
        # "24:00" -> 1440 (fin de dia); "02:00" -> 120
        h, m = hhmm_str.split(":")
        return int(h) * 60 + int(m)

    # Cada regla separada por ';'. Formato OSM: "Mo-Fr 09:00-18:00"
    # (día y hora separados por ESPACIO, no por ':').
    # Si la regla NO tiene espacio (empieza por la hora), OSM la aplica
    # todos los dias.
    for rule in oh.split(";"):
        if " " in rule:
            left, right = rule.split(" ", 1)
            # Quitar prefijos de feriado/public holiday: "ph,mo-su" -> "mo-su"
            left = left.split(",")[-1]  # toma el ultimo tramo (el de dias)
        else:
            left, right = None, rule  # sin dia => todos los dias
        # ¿La regla aplica hoy?
        aplica = False
        if left is None:
            aplica = True  # sin dia especificado => todos los dias
        elif "-" in left:
            try:
                a, b = left.split("-")
                if a in dias and b in dias:
                    seq = dias[dias.index(a):dias.index(b) + 1]
                    aplica = hoy in seq
            except Exception:
                aplica = False
        else:
            aplica = left in dias
        if not aplica:
            continue
        # ¿hora dentro de algun rango? (soporta cruce de medianoche)
        for rango in right.split(","):
            if "-" not in rango:
                continue
            try:
                s, e = rango.split("-")
                sh = a_minutos(s)
                eh = a_minutos(e)
                if sh <= eh:
                    if sh <= hhmm <= eh:
                        return True
                else:  # cruza medianoche: sh > eh (ej 20:00-02:00)
                    if hhmm >= sh or hhmm <= eh:
                        return True
            except Exception:
                continue
    return False


# ---------------------------------------------------------------------------
# Enlace a Google Maps (SOLO para ver la direccion en el movil, gratis, sin
# API key). Las BUSQUEDAS siguen siendo 100% OpenStreetMap; Google solo
# sirve de mapa porque es la app mas instalada en telefonos.
# ---------------------------------------------------------------------------
def gmaps_link(r):
    """Enlace gratuito de Google Maps a la ubicacion del restaurante.
    Usa coordenadas (siempre validas) y, si hay, la direccion como texto."""
    nombre = r.get("nombre", "")
    if r.get("lat") and r.get("lon"):
        q = f"{r['lat']},{r['lon']}"
    elif r.get("direccion"):
        q = r["direccion"].replace(" ", "+")
    else:
        q = nombre.replace(" ", "+")
    if nombre:
        q = f"{nombre.replace(' ', '+')} {q}"
    from urllib.parse import quote
    return f"https://www.google.com/maps/search/?api=1&query={quote(q)}"


# ---------------------------------------------------------------------------
# IDIOMAS (es / en / fr) — la interfaz se traduce entera; las BUSQUEDAS
# siguen siendo 100% OpenStreetMap. El usuario elige el idioma en la barra
# lateral y se guarda en st.session_state["lang"].
# ---------------------------------------------------------------------------
def t(key):
    # App fijada a frances (uso en Francia). Sin selector de idioma.
    lang = "fr"
    return I18N[lang].get(key, I18N["es"][key])


I18N = {
    "es": {
        "lang_label": "🌐 Idioma",
        "title": "🍽️ BuscaTuRestaurante · Decisión rápida para almuerzo",
        "subtitle": "Dejas de decir «no sé»: te proponemos buenas opciones en "
                    "Francia, ordenadas por lo que la comunidad recomienda de verdad",
        "how_header": "ℹ️ ¿Cómo funciona?",
        "how_body": (
            "**El problema:** «¿qué quieres comer?» → «no sé» → hambre → Uber Eats "
            "→ siempre lo mismo.\n\n"
            "**La solución:** la app no te pregunta «qué quieres». Te propone "
            "opciones ya cribadas y ordenadas por un **Índice de Recomendación** "
            "basado en señales reales de OpenStreetMap (la comunidad de mapa libre):\n\n"
            "- 🕒 **Frescura de datos** (`check_date`): sitios verificados recientemente.\n"
            "- 🥡 **Para llevar** / 🪑 **Para sentarse** según vayas solo o acompañado.\n"
            "- 🥗 **Opciones veganas/vegetarianas** si las pides.\n"
            "- 📋 **Completitud de la ficha** (web, teléfono, accesibilidad…): la "
            "comunidad lo cuida = implícitamente recomendado.\n"
            "- 🍜 **Variedad de cocina** para romper la rutina de siempre lo mismo.\n\n"
            "> Nota honesta: OpenStreetMap en Francia **no tiene estrellas ni "
            "comentarios** tipo Google. Este índice es un proxy transparente con "
            "lo que SÍ existe."
        ),
        "dest_label": "📍 ¿Dónde almuerzas hoy? (ciudad/barrio en Francia):",
        "dest_placeholder": "Escribe tu sitio: Paris, Lyon, Marsella…",
        "quick_cities": "⚡ Ciudades rápidas (toque y busca):",
        "search": "🔍 Buscar",
        "radius": "📏 Radio de búsqueda (m):",
        "companion_q": "🧑‍🤝‍🧑 ¿Vas solo o acompañado?",
        "solo": "Solo (rápido, para llevar)",
        "acco": "Acompañado (sentarse)",
        "filters": "⚙️ Filtros",
        "takeaway": "🥡 Solo para llevar (takeaway)",
        "diet": "🥗 Régimen:",
        "diet_none": "Ninguno",
        "diet_veg": "Vegetariano",
        "diet_vegan": "Vegano",
        "open": "🟢 Solo si está abierto ahora",
        "enter_loc": "Escribe una ubicación.",
        "not_found": "❌ Ubicación no encontrada. Prueba añadiendo «Francia».",
        "searching": "🔍 Buscando «{q}»...",
        "osm": "🍽️ Consultando OpenStreetMap...",
        "press_search": "👆 Pulsa **Buscar** para ver opciones cerca de tu ubicación.",
        "no_results": "😔 Ningún sitio encaja con tus filtros. Afloja alguno "
                      "(ej. quita «abierto ahora» o «solo para llevar»).",
        "recommended": "🎯 {n} opciones recomendadas, de mejor a peor:",
        "decide": "🎲 No sé, ¡decídeme tú!",
        "chosen": "🍽️ Hoy te toca: **{name}**",
        "chosen_eyebrow": "Hoy te toca (la app decidió por ti):",
        "gmaps_addr_text": "Ver en Google Maps",
        "cuisine_idx": "**Cocina:** {c} · **Índice:** {s}/100",
        "gmaps": "📍 [Ver en Google Maps]({url})",
        "gmaps_addr": "📍 [Ver en Google Maps (dirección)]({url})",
        "why": "**¿Por qué este y no otro?**",
        "low_score": "⚠️ Ojo: su nota no es alta. Era el que mejor encajaba con "
                     "tus filtros entre todas las opciones, pero tú siempre "
                     "puedes ignorarme y mirar la lista.",
        "why_note": "ℹ️ Por qué esta nota",
        "address": "**Dirección:** {d}",
        "address_na": "**Dirección:** Dirección no disponible",
        "schedule": "**Horario:** {h}",
        "perfil_header": "🧭 Tu perfil móvil",
        "perfil_body": "Trabajas desplazándote por Francia y el almuerzo es corto. "
                       "Esta app existe para que no caigas siempre en lo mismo.",
        "consejo": "**Consejo:** usa «No sé, decídeme tú» cuando el tiempo apriete. "
                   "El azar, entre buenas opciones, rompe la rutina.",
        "fuente": "Fuente: OpenStreetMap (datos abiertos). Sin estrellas tipo "
                  "Google en Francia; el índice es un proxy de recomendación de la comunidad.",
        "badges": {
            "llevar": "🥡 llevar", "vegano": "🥗 vegano",
            "vegetariano": "🥗 vegetariano", "terraza": "🌞 terraza",
            "salon": "🪑 salón", "accesible": "♿ accesible",
            "web": "🌐 web", "verif": "🕒 verif. {d}",
        },
        "geo_none": "🤔 No encontré «{q}». O lo escribiste con el dedo pequeño, "
                    "o ese sitio está escondido mejor que tus ganas de cocinar.",
        "geo_none_tip": "Prueba a: añadir **Francia**, quitar acentos (Café -> "
                        "Cafe), o poner una ciudad conocida cerca (París, Lyon, "
                        "Marsella). Yo confío en ti. Casi.",
        "geo_lowprec": "🔍 Encontré algo parecido, pero no juraría que es «{q}». "
                       "Mira bien antes de que acabes comiendo en el país vecino.",
        "geo_ambiguous": "🧭 «{q}» puede ser varias cosas. Elige la que suena a "
                         "donde quieres almorzar:",
        "geo_confirm_q": "¿Es este tu sitio o Prefieres reescribirlo?",
        "geo_yes": "✅ Sí, ese",
        "geo_no": "✏️ Lo reescribo",
        "geo_keep": "Vale, confío en tu pulso. Buscando cerca de ahí…",
        "geo_retry": "Perfecto. Reescribe la ubicación arriba y dale a Buscar.",
        "add_to_home_hint_title": "Usar como app en el móvil",
        "add_to_home_hint": "En el iPhone: abre esta página en **Safari**, pulsa el "
                            "botón **Compartir** (el cuadradito con flecha) y elige "
                            "**Añadir a pantalla de inicio**. Se crea un icono como "
                            "el de una app: se abre a pantalla completa y sin la barra "
                            "de Safari. Así almuerzas decidido en un toque.",
    },
    "en": {
        "lang_label": "🌐 Language",
        "title": "🍽️ FindYourRestaurant · Quick lunch decision",
        "subtitle": "Stop saying \"I don't know\": we suggest good options in "
                    "France, ranked by what the community really recommends",
        "how_header": "ℹ️ How it works",
        "how_body": (
            "**The problem:** \"What do you want to eat?\" → \"I don't know\" → "
            "hungry → Uber Eats → always the same.\n\n"
            "**The fix:** the app doesn't ask \"what do you want\". It suggests "
            "pre-filtered options ranked by a **Recommendation Index** based on "
            "real OpenStreetMap signals (the free-map community):\n\n"
            "- 🕒 **Data freshness** (`check_date`): recently verified places.\n"
            "- 🥡 **Takeaway** / 🪑 **Sit-down** depending on solo or with company.\n"
            "- 🥗 **Vegan/vegetarian options** if you ask.\n"
            "- 📋 **Complete entry** (website, phone, accessibility…): the "
            "community maintains it = implicitly recommended.\n"
            "- 🍜 **Cuisine variety** to break the always-the-same routine.\n\n"
            "> Honest note: OpenStreetMap in France **has no stars or reviews** "
            "like Google. This index is a transparent proxy from what DOES exist."
        ),
        "dest_label": "📍 Where are you having lunch today? (city/district in France):",
        "dest_placeholder": "Type your place: Paris, Lyon, Marseille…",
        "quick_cities": "⚡ Quick cities (tap to search):",
        "search": "🔍 Search",
        "radius": "📏 Search radius (m):",
        "companion_q": "🧑‍🤝‍🧑 Solo or with company?",
        "solo": "Solo (quick, takeaway)",
        "acco": "With company (sit down)",
        "filters": "⚙️ Filters",
        "takeaway": "🥡 Takeaway only",
        "diet": "🥗 Diet:",
        "diet_none": "None",
        "diet_veg": "Vegetarian",
        "diet_vegan": "Vegan",
        "open": "🟢 Only if open now",
        "enter_loc": "Type a location.",
        "not_found": "❌ Location not found. Try adding \"France\".",
        "searching": "🔍 Searching \"{q}\"...",
        "osm": "🍽️ Querying OpenStreetMap...",
        "press_search": "👆 Press **Search** to see options near your location.",
        "no_results": "😔 No place matches your filters. Loosen one "
                      "(e.g. uncheck \"open now\" or \"takeaway only\").",
        "recommended": "🎯 {n} recommended options, best to worst:",
        "decide": "🎲 I don't know, you choose!",
        "chosen": "🍽️ Today it's: **{name}**",
        "chosen_eyebrow": "Today it's (the app chose for you):",
        "gmaps_addr_text": "View on Google Maps",
        "cuisine_idx": "**Cuisine:** {c} · **Index:** {s}/100",
        "gmaps": "📍 [View on Google Maps]({url})",
        "gmaps_addr": "📍 [View on Google Maps (address)]({url})",
        "why": "**Why this one and not another?**",
        "low_score": "⚠️ Heads up: its score isn't high. It was the best fit for "
                     "your filters among all options, but you can always ignore "
                     "me and check the list.",
        "why_note": "ℹ️ Why this score",
        "address": "**Address:** {d}",
        "address_na": "**Address:** Address not available",
        "schedule": "**Hours:** {h}",
        "perfil_header": "🧭 Your mobile profile",
        "perfil_body": "You work on the move across France and lunch is short. "
                       "This app exists so you don't always fall back on the same.",
        "consejo": "**Tip:** use \"I don't know, you choose!\" when time is tight. "
                   "Chance, among good options, breaks the routine.",
        "fuente": "Source: OpenStreetMap (open data). No Google-style stars in "
                  "France; the index is a community-recommendation proxy.",
        "badges": {
            "llevar": "🥡 takeaway", "vegano": "🥗 vegan",
            "vegetariano": "🥗 vegetarian", "terraza": "🌞 terrace",
            "salon": "🪑 dining room", "accesible": "♿ accessible",
            "web": "🌐 web", "verif": "🕒 verif. {d}",
        },
        "geo_none": "🤔 I couldn't find \"{q}\". Either you typed it with your "
                    "thumb, or that place is hidden better than your will to cook.",
        "geo_none_tip": "Try: add **France**, drop accents (Café -> Cafe), or use "
                        "a well-known nearby city (Paris, Lyon, Marseille). I "
                        "believe in you. Sort of.",
        "geo_lowprec": "🔍 I found something close, but I wouldn't bet it's "
                       "\"{q}\". Double-check before you end up eating in the "
                       "next country.",
        "geo_ambiguous": "🧭 \"{q}\" could be several things. Pick the one that "
                         "sounds like where you want lunch:",
        "geo_confirm_q": "Is this your spot, or do you want to rewrite it?",
        "geo_yes": "✅ Yes, that one",
        "geo_no": "✏️ I'll rewrite it",
        "geo_keep": "Ok, I trust your aim. Searching near there…",
        "geo_retry": "Great. Rewrite the location above and hit Search.",
        "add_to_home_hint_title": "Use as a mobile app",
        "add_to_home_hint": "On iPhone: open this page in **Safari**, tap the "
                            "**Share** button (the square with an arrow) and choose "
                            "**Add to Home Screen**. It makes an app icon: opens "
                            "fullscreen, no Safari bar. Decide lunch in one tap.",
    },
    "fr": {
        "lang_label": "🌐 Langue",
        "title": "🍽️ TrouveTonResto · Décision rapide pour le déjeuner",
        "subtitle": "Arrête de dire «je sais pas» : on te propose de bonnes "
                    "options en France, classées par ce que la communauté recommande vraiment",
        "how_header": "ℹ️ Comment ça marche",
        "how_body": (
            "**Le problème :** «qu'est-ce que tu veux manger ?» → «je sais pas» → "
            "faim → Uber Eats → toujours la même chose.\n\n"
            "**La solution :** l'app ne te demande pas «qu'est-ce que tu veux». "
            "Elle propose des options déjà filtrées et classées par un **Index de "
            "Recommandation** basé sur de vrais signaux d'OpenStreetMap (la "
            "communauté de la carte libre) :\n\n"
            "- 🕒 **Fraîcheur des données** (`check_date`) : lieux vérifiés récemment.\n"
            "- 🥡 **À emporter** / 🪑 **Sur place** selon que tu es seul ou accompagné.\n"
            "- 🥗 **Options vegan/végétariennes** si tu les demandes.\n"
            "- 📋 **Fiche complète** (site, téléphone, accessibilité…) : la "
            "communauté la soigne = recommandée implicitement.\n"
            "- 🍜 **Variété de cuisine** pour briser la routine de toujours la même.\n\n"
            "> Note honnête : OpenStreetMap en France **n'a ni étoiles ni avis** "
            "comme Google. Cet index est un proxy transparent à partir de ce qui "
            "EXISTE."
        ),
        "dest_label": "📍 Où déjeunes-tu aujourd'hui ? (ville/quartier en France) :",
        "dest_placeholder": "Écris ton lieu : Paris, Lyon, Marseille…",
        "quick_cities": "⚡ Villes rapides (tape et cherche) :",
        "search": "🔍 Chercher",
        "radius": "📏 Rayon de recherche (m) :",
        "companion_q": "🧑‍🤝‍🧑 Seul ou accompagné ?",
        "solo": "Seul (rapide, à emporter)",
        "acco": "Accompagné (sur place)",
        "filters": "⚙️ Filtres",
        "takeaway": "🥡 À emporter uniquement",
        "diet": "🥗 Régime :",
        "diet_none": "Aucun",
        "diet_veg": "Végétarien",
        "diet_vegan": "Vegan",
        "open": "🟢 Uniquement si ouvert maintenant",
        "enter_loc": "Écris un lieu.",
        "not_found": "❌ Lieu introuvable. Essaie d'ajouter «France».",
        "searching": "🔍 Recherche de «{q}»...",
        "osm": "🍽️ Interrogation d'OpenStreetMap...",
        "press_search": "👆 Appuie sur **Chercher** pour voir les options près de toi.",
        "no_results": "😔 Aucun lieu ne correspond à tes filtres. Assouplis-en un "
                      "(ex. décoche «ouvert maintenant» ou «à emporter»).",
        "recommended": "🎯 {n} options recommandées, du meilleur au pire :",
        "decide": "🎲 Je sais pas, choisis pour moi !",
        "chosen": "🍽️ Aujourd'hui c'est : **{name}**",
        "chosen_eyebrow": "Aujourd'hui c'est (l'app a choisi pour toi) :",
        "gmaps_addr_text": "Voir sur Google Maps",
        "cuisine_idx": "**Cuisine :** {c} · **Index :** {s}/100",
        "gmaps": "📍 [Voir sur Google Maps]({url})",
        "gmaps_addr": "📍 [Voir sur Google Maps (adresse)]({url})",
        "why": "**Pourquoi celui-ci et pas un autre ?**",
        "low_score": "⚠️ Attention : sa note n'est pas élevée. C'était le meilleur "
                     "ajustement à tes filtres parmi toutes les options, mais tu "
                     "peux toujours m'ignorer et regarder la liste.",
        "why_note": "ℹ️ Pourquoi cette note",
        "address": "**Adresse :** {d}",
        "address_na": "**Adresse :** Adresse non disponible",
        "schedule": "**Horaires :** {h}",
        "perfil_header": "🧭 Ton profil mobile",
        "perfil_body": "Tu travailles en déplacement en France et le déjeuner est "
                       "court. Cette app existe pour que tu ne retombes pas toujours dans le même.",
        "consejo": "**Conseil :** utilise «Je sais pas, choisis pour moi !» quand "
                   "le temps presse. Le hasard, parmi de bonnes options, brise la routine.",
        "fuente": "Source : OpenStreetMap (données ouvertes). Pas d'étoiles type "
                  "Google en France ; l'index est un proxy de recommandation communautaire.",
        "badges": {
            "llevar": "🥡 à emporter", "vegano": "🥗 vegan",
            "vegetariano": "🥗 végétarien", "terraza": "🌞 terrasse",
            "salon": "🪑 salle", "accesible": "♿ accessible",
            "web": "🌐 web", "verif": "🕒 vérif. {d}",
        },
        "geo_none": "🤔 Je n'ai pas trouvé «{q}». Soit tu l'as tapé avec le pouce, "
                    "soit ce lieu est mieux caché que ton envie de cuisiner.",
        "geo_none_tip": "Essaie : ajoute **France**, enlève les accents (Café -> "
                        "Cafe), ou une ville connue proche (Paris, Lyon, "
                        "Marseille). Je crois en toi. Un peu.",
        "geo_lowprec": "🔍 J'ai trouvé un truc approchant, mais je ne parierais "
                       "pas que c'est «{q}». Vérifie avant de finir à manger dans "
                       "le pays d'à côté.",
        "geo_ambiguous": "🧭 «{q}» peut désigner plusieurs endroits. Choisis celui "
                         "qui ressemble à où tu veux déjeuner :",
        "geo_confirm_q": "C'est bien ton spot, ou tu préfères réécrire ?",
        "geo_yes": "✅ Oui, celui-là",
        "geo_no": "✏️ Je réécris",
        "geo_keep": "Ok, je fais confiance à ton instinct. Recherche par là…",
        "geo_retry": "Parfait. Réécris la localisation en haut et lance la recherche.",
        "add_to_home_hint_title": "Utiliser comme app mobile",
        "add_to_home_hint": "Sur iPhone : ouvre cette page dans **Safari**, tape le "
                            "bouton **Partager** (le carré avec flèche) et choisis "
                            "**Ajouter à l'écran d'accueil**. Ça crée une icône d'app : "
                            "ouverture plein écran, sans la barre Safari. Déjeune "
                            "décidé en une tape.",
    },
}

# Razones del índice (lenguaje-neutral -> traducido por idioma)
REASONS = {
    "verif_fresco": {
        "es": "🕒 Verificado por la comunidad en {y} (datos frescos)",
        "en": "🕒 Verified by the community in {y} (fresh data)",
        "fr": "🕒 Vérifié par la communauté en {y} (données fraîches)"},
    "verif_old": {
        "es": "🕒 Verificado en {y} (datos algo antiguos)",
        "en": "🕒 Verified in {y} (somewhat old data)",
        "fr": "🕒 Vérifié en {y} (données un peu anciennes)"},
    "verif_ancien": {
        "es": "🕒 Verificado hace tiempo ({y})",
        "en": "🕒 Verified a while ago ({y})",
        "fr": "🕒 Vérifié il y a longtemps ({y})"},
    "verif_ilegible": {
        "es": "🕒 Verificado por la comunidad (fecha ilegible)",
        "en": "🕒 Verified by the community (unreadable date)",
        "fr": "🕒 Vérifié par la communauté (date illisible)"},
    "no_verif": {
        "es": "⚠️ Nadie ha verificado este sitio recientemente",
        "en": "⚠️ Nobody has verified this place recently",
        "fr": "⚠️ Personne n'a vérifié cet endroit récemment"},
    "takeaway_solo": {
        "es": "🥡 Para llevar: ideal para comer rápido y seguir",
        "en": "🥡 Takeaway: ideal to eat fast and move on",
        "fr": "🥡 À emporter : idéal pour manger vite et repartir"},
    "rapida": {
        "es": "⚡ Cocina rápida: poco tiempo de espera",
        "en": "⚡ Fast food: little waiting time",
        "fr": "⚡ Cuisine rapide : peu d'attente"},
    "sentarse": {
        "es": "🪑 Tiene donde sentarse: bueno para acompañado",
        "en": "🪑 Has seating: good when with company",
        "fr": "🪑 A des places assises : pratique en groupe"},
    "takeaway_acco": {
        "es": "🥡 También para llevar, por si apuras",
        "en": "🥡 Also takeaway, in case you're in a hurry",
        "fr": "🥡 Aussi à emporter, si tu es pressé"},
    "no_vegan": {
        "es": "❌ No es vegano (filtro activo)",
        "en": "❌ Not vegan (filter active)",
        "fr": "❌ Pas vegan (filtre actif)"},
    "no_takeaway": {
        "es": "❌ No es para llevar (filtro activo)",
        "en": "❌ Not takeaway (filter active)",
        "fr": "❌ Pas à emporter (filtre actif)"},
    "no_veg": {
        "es": "❌ No es vegetariano (filtro activo)",
        "en": "❌ Not vegetarian (filter active)",
        "fr": "❌ Pas végétarien (filtre actif)"},
    "vegan_ok": {
        "es": "🥗 Opción vegana de verdad",
        "en": "🥗 Real vegan option",
        "fr": "🥗 Vraie option vegan"},
    "veg_ok": {
        "es": "🥗 Opción vegetariana/vegana",
        "en": "🥗 Vegetarian/vegan option",
        "fr": "🥗 Option végétarienne/vegan"},
    "cerrado": {
        "es": "❌ Cerrado ahora mismo",
        "en": "❌ Closed right now",
        "fr": "❌ Fermé en ce moment"},
    "ficha_buena": {
        "es": "📋 Ficha bien documentada por la comunidad (+{tc})",
        "en": "📋 Well-documented entry by the community (+{tc})",
        "fr": "📋 Fiche bien documentée par la communauté (+{tc})"},
    "ficha_parcial": {
        "es": "📋 Ficha parcialmente documentada (+{tc})",
        "en": "📋 Partially documented entry (+{tc})",
        "fr": "📋 Fiche partiellement documentée (+{tc})"},
    "variedad": {
        "es": "🍜 Cocina {c}: varies de lo de siempre",
        "en": "🍜 {c} cuisine: break from the usual",
        "fr": "🍜 Cuisine {c} : change from the usual"},
}

# Frases irónicas por idioma (la app decide por ti sabiendo que no debería)
FRASES_IRONICAS = {
    "es": [
        "🤖 Lo elegí por ti. Sí, irónico: esto tendrías que decidirlo tú, pero "
        "justo por eso existo — para romper el «no sé» que te deja con hambre y "
        "pidiendo siempre lo mismo. Tómalo como empujón, no sentencia.",
        "🤖 Decidí por ti otra vez. Eres libre, claro… libre de seguir sin saber "
        "qué quieres. Yo cubro ese hueco mientras tanto.",
        "🤖 Yo sí sé qué quieres (aparentemente). Tú, que llevas años sin elegir, "
        "bienvenido a delegar en una app de almuerzo.",
        "🤖 Tu libre albedrío descansó hoy. No te preocupes: lo elegí con criterio "
        "de comunidad, no con tu indecisión.",
        "🤖 Alguien tenía que decidir. Como tú no ibas a hacerlo, me tocó a mí. La "
        "ironía es que esto debería ser tu trabajo.",
        "🤖 Menos «no sé» y más «me lo comí». Asumí el mando de tu almuerzo para "
        "que dejes de dar vueltas.",
        "🤖 Delegaste en una máquina lo que un humano hace desde el neolítico: "
        "elegir comida. Progreso, supongo.",
        "🤖 Lo mío es no tener hambre y aun así elegir por ti. La paradoja almuerza "
        "mientras tú dudas.",
        "🤖 Otra vez yo. Si fueras decisivo no necesitarías esta app, pero aquí "
        "estamos, rompiendo la rutina de lo de siempre.",
        "🤖 Pulsaste un botón para no decidir. Mis respetos a tu eficiencia en la "
        "procrastinación culinaria.",
    ],
    "en": [
        "🤖 I chose it for you. Yes, ironic: you should've decided this yourself, "
        "but that's exactly why I exist — to break the \"I don't know\" that leaves "
        "you hungry and always ordering the same. Take it as a nudge, not a sentence.",
        "🤖 I decided for you again. You're free, sure… free to keep not knowing "
        "what you want. I cover that gap in the meantime.",
        "🤖 I do know what you want (apparently). You, who haven't chosen in years, "
        "welcome to delegating to a lunch app.",
        "🤖 Your free will took the day off. Don't worry: I picked it with "
        "community criteria, not your indecision.",
        "🤖 Someone had to decide. Since you weren't going to, it fell to me. The "
        "irony is this should be your job.",
        "🤖 Less \"I don't know\" and more \"I ate it\". I took command of your "
        "lunch so you'd stop going in circles.",
        "🤖 You delegated to a machine what humans have done since the Neolithic: "
        "pick food. Progress, I guess.",
        "🤖 I don't get hungry and still choose for you. The paradox eats while you "
        "hesitate.",
        "🤖 Me again. If you were decisive you wouldn't need this app, but here we "
        "are, breaking the same-old routine.",
        "🤖 You pressed a button to avoid deciding. My respects for your efficiency "
        "at culinary procrastination.",
    ],
    "fr": [
        "🤖 Je l'ai choisi pour toi. Oui, ironique : tu aurais dû décider toi-même, "
        "mais c'est exactement pour ça que j'existe — pour briser le «je sais pas» "
        "qui te laisse affamé et toujours la même chose. Prends-le comme une "
        "bousculade, pas une sentence.",
        "🤖 J'ai décidé pour toi encore une fois. Tu es libre, bien sûr… libre de "
        "ne pas savoir quoi vouloir. Je comble ce vide en attendant.",
        "🤖 Je sais ce que tu veux (apparemment). Toi qui n'as rien choisi depuis "
        "des années, bienvenue dans la délégation à une app de déj.",
        "🤖 Ton libre arbitre est en pause aujourd'hui. Ne t'inquiète pas : j'ai "
        "choisi selon les critères de la communauté, pas ton indécision.",
        "🤖 Quelqu'un devait décider. Comme ce n'était pas toi, ça m'est tombé "
        "dessus. L'ironie : ça devrait être ton boulot.",
        "🤖 Moins «je sais pas» et plus «je l'ai mangé». J'ai pris les commandes de "
        "ton déjeuner pour que tu arrêtes de tourner en rond.",
        "🤖 Tu as délégué à une machine ce que l'humain fait depuis le Néolithique : "
        "choisir à manger. Le progrès, j'imagine.",
        "🤖 Je n'ai pas faim et je choisis quand même pour toi. Le paradoxe déjeune "
        "pendant que tu hésites.",
        "🤖 Moi encore. Si tu étais décisif tu n'aurais pas besoin de cette app, "
        "mais nous voilà, en train de briser la routine du toujours-pareil.",
        "🤖 Tu as pressé un bouton pour ne pas décider. Mon respect pour ton "
        "efficacité en procrastination culinaire.",
    ],
}


# ---------------------------------------------------------------------------
# INTERFAZ
# ---------------------------------------------------------------------------
st.title(t("title"))
st.subheader(t("subtitle"))

# --- Adaptación móvil / Safari / "Añadir a pantalla de inicio" ---
# Solo el bloque style (sin etiqueta meta pegada delante): Streamlit ya
# incluye el viewport por defecto. Dejar el style aislado evita que el parser
# de markdown lo muestre como texto. Selectores actualizados a Streamlit 1.x
# (los de "reportview" ya no existen y no aplicaban).
st.markdown(
    """
    <style>
    /* Botones y radios grandes para el dedo (touch-friendly) */
    .stButton>button, .stRadio>div, .stCheckbox>label, .stSelectbox>div {
      font-size:17px !important; min-height:44px;
    }
    .stTextInput>div>div>input { font-size:17px !important; height:46px; }
    /* La barra lateral en movil ocupa toda la pantalla y se ve como menu */
    @media (max-width: 640px) {
      section[data-testid='stSidebar'] { width:100% !important; }
    }
    /* Quita el hueco inferior en Safari (notch / home indicator) */
    .block-container { padding-bottom: 80px; }
    </style>
    """,
    unsafe_allow_html=True)

with st.expander("📱 " + t("add_to_home_hint_title"), expanded=False):
    st.markdown(t("add_to_home_hint"))

with st.expander(t("how_header")):
    st.markdown(t("how_body"))

# Barra lateral: perfil movil (idioma fijado a frances, sin selector)
with st.sidebar:
    st.header(t("perfil_header"))
    st.write(t("perfil_body"))
    st.write(t("consejo"))
    st.info(t("fuente"))

# --- Paso 1: destino ---
if "resultados" not in st.session_state:
    st.session_state.resultados = None  # lista de restaurantes ya obtenidos

# Ciudad elegida con un boton rapido (no escribimos en el widget de texto,
# porque Streamlit no permite asignar a la clave de un widget ya creado).
if "pending_city" not in st.session_state:
    st.session_state.pending_city = ""

# Caja de busqueda destacada (sin valor por defecto: el usuario escribe el suyo)
st.markdown(
    "<div style='padding:14px 16px;border-radius:14px;"
    "background:linear-gradient(135deg,#1f6f54,#2e8b57);color:white;"
    "box-shadow:0 4px 14px rgba(0,0,0,.25);margin-bottom:14px'>"
    f"<div style='font-size:20px;font-weight:800;margin-bottom:10px'>"
    f"🍽️ {t('dest_label')}</div></div>",
    unsafe_allow_html=True)
location_query = st.text_input(
    "",  # etiqueta ya en la caja destacada de arriba
    key="location_query",
    placeholder=t("dest_placeholder"))
search_button = st.button(t("search"), type="primary", use_container_width=True)

# Ciudades rapidas: un toque y busca (sin teclear acentos)
QUICK = ["Paris", "Lyon", "Marseille", "Toulouse", "Nice", "Nantes"]
st.caption(t("quick_cities"))
qcols = st.columns(len(QUICK))
for i, city in enumerate(QUICK):
    with qcols[i]:
        if st.button(city, key=f"quick_{i}", use_container_width=True):
            st.session_state["pending_city"] = city
            search_button = True

radius = st.slider(t("radius"), 500, 3000, 1200, 100)

# --- Paso 2: ¿solo o acompañado? ---
st.markdown(f"### {t('companion_q')}")
companion = st.radio(
    t("companion_q"),
    [t("solo"), t("acco")],
    horizontal=True)
solo = companion.startswith(t("solo")[:4])

# --- Paso 3: filtros móviles ---
st.markdown(f"### {t('filters')}")
f_takeaway = st.checkbox(t("takeaway"))
f_diet = st.selectbox(t("diet"), [t("diet_none"), t("diet_veg"), t("diet_vegan")])
f_open = st.checkbox(t("open"))
diet_key = {t("diet_none"): None, t("diet_veg"): "vegetarian",
            t("diet_vegan"): "vegan"}[f_diet]

# --- BÚSQUEDA EN RED: solo al pulsar "Buscar" (no en cada cambio de filtro) ---
if search_button:
    # Lo que escriba el usuario manda siempre; el boton rapido solo si el
    # campo esta vacio. Asi no queda "pegada" una ciudad anterior.
    typed = location_query.strip()
    if typed:
        st.session_state["pending_city"] = ""
        query = typed
    else:
        query = st.session_state.get("pending_city", "")
    if not query:
        st.warning(t("enter_loc"))
    else:
        with st.spinner(t("searching").format(q=query)):
            lat, lon, display_name, alts = geocode_help(query)

        if lat is None:
            st.error(t("geo_none").format(q=query))
            st.info(t("geo_none_tip"))
            # Sugiere buscar solo la calle (el numero a veces no esta en OSM)
            # y permite reintentar de un toque.
            partes = [p.strip() for p in query.split(",")]
            if len(partes) > 1:  # forma "12, Rue X, Paris" -> quita la ciudad
                solo_calle = ", ".join(partes[:-1])
            else:  # forma "214 boulevard raspail paris" -> quita el nº inicial
                toks = query.split()
                solo_calle = " ".join(toks[1:]) if toks and toks[0].isdigit() else query
            with st.expander("💡 Astuces si ça ne marche pas"):
                st.write(
                    "OpenStreetMap n'a pas ce numéro. Essaie le nom de la "
                    f"rue seul, par ex. : **{solo_calle}**")
                st.write(
                    "Ou vérifie l'orthographe (le clavier du pouce ajoute "
                    "parfois une faute). Texte envoyé : "
                    f"`{query}`")
            if st.button("↻ Réessayer", key="retry_geo_btn",
                         use_container_width=True):
                st.session_state["pending_city"] = query
                st.rerun()
        else:
            # ¿El resultado parece Francia? Si no, advertir y proponer alternativas.
            es_francia = "france" in display_name.lower()
            if not es_francia and alts:
                st.warning(t("geo_lowprec").format(q=query))
                st.session_state["geo_candidato"] = (lat, lon, display_name)
                st.session_state["geo_alts"] = alts
            else:
                st.session_state["geo_candidato"] = (lat, lon, display_name)
                st.session_state["geo_alts"] = []
                st.success(f"✅ {display_name}")
                with st.spinner(t("osm")):
                    time.sleep(1.0)
                    st.session_state.resultados = get_restaurants_nearby(
                        lat, lon, radius=radius)
                    st.session_state.display_name = display_name

# Si hay un candidato en duda (no parecia Francia), proponer elegir/reescribir
if st.session_state.get("geo_alts"):
    cand = st.session_state["geo_candidato"]
    st.markdown(f"### 🧭 {t('geo_ambiguous').format(q=location_query)}")
    st.write(f"🔎 **{cand[2]}**")
    col_a, col_b = st.columns([1, 1])
    if col_a.button(t("geo_yes"), key="geo_yes_btn"):
        st.session_state["geo_alts"] = []
        st.success(t("geo_keep"))
        with st.spinner(t("osm")):
            time.sleep(1.0)
            st.session_state.resultados = get_restaurants_nearby(
                cand[0], cand[1], radius=radius)
            st.session_state.display_name = cand[2]
    if col_b.button(t("geo_no"), key="geo_no_btn"):
        st.session_state["geo_alts"] = []
        st.session_state.resultados = None
        st.info(t("geo_retry"))

# --- APLICAR FILTROS: instantáneo sobre datos ya cargados (sin red) ---
restaurantes = st.session_state.resultados
if restaurantes is None:
    st.info(t("press_search"))
else:
    if f_open:
        for r in restaurantes:
            r["_abierto_ahora"] = is_open_now(r["horario"])

    candidatos = []
    for r in restaurantes:
        s, razones = compute_score(r, solo, f_takeaway, diet_key, f_open,
                                    lang=st.session_state.get("lang", "es"))
        if s > 0:
            r["_score"] = s
            r["_razones"] = razones
            candidatos.append(r)
    candidatos.sort(key=lambda r: r["_score"], reverse=True)

    if not candidatos:
        st.warning(t("no_results"))
    else:
        st.success(t("recommended").format(n=len(candidatos)))

        if st.button(t("decide"), type="primary"):
            pesos = [max(1, r["_score"]) for r in candidatos]
            elegido = random.choices(candidatos, weights=pesos, k=1)[0]
            frase = random.choice(FRASES_IRONICAS[st.session_state.get("lang", "es")])
            st.balloons()
            maps_url = gmaps_link(elegido)
            # Resultado GRANDE y destacado: la gente apurada (99%) no lee
            # texto pequeno. Se separa del resto con una caja visual.
            st.markdown("---")
            st.markdown(
                f"<div style='padding:18px 20px;border-radius:14px;"
                f"background:linear-gradient(135deg,#1f6f54,#2e8b57);"
                f"color:white;box-shadow:0 4px 14px rgba(0,0,0,.25)'>"
                f"<div style='font-size:14px;opacity:.85;margin-bottom:4px'>"
                f"🤖 {t('chosen_eyebrow')}</div>"
                f"<div style='font-size:34px;font-weight:800;line-height:1.1'>"
                f"🍽️ {elegido['nombre']}</div>"
                f"<div style='font-size:18px;margin-top:6px'>"
                f"{t('cuisine_idx').format(c=elegido['cocina'], s=elegido['_score'])}"
                f"</div>"
                f"<div style='font-size:16px;margin-top:8px'>"
                f"📍 <a href='{maps_url}' target='_blank' style='color:#cfe'>"
                f"{t('gmaps_addr_text')}</a></div>"
                f"</div>",
                unsafe_allow_html=True)
            st.info(frase)
            st.success(t("why"))
            for razon in elegido.get("_razones", []):
                st.write(f"- {razon}")
            if elegido["_score"] < 60:
                st.caption(t("low_score"))
            st.markdown("---")

        for r in candidatos[:20]:
            with st.container():
                st.subheader(f"{r['nombre']}  ·  {r['_score']}/100")
                st.write(t("cuisine_idx").format(c=r["cocina"], s=r["_score"]))
                if r["direccion"] and r["direccion"] != "Dirección no disponible":
                    st.write(t("address").format(d=r["direccion"]))
                else:
                    st.write(t("address_na"))
                st.markdown(t("gmaps").format(url=gmaps_link(r)))
                st.write(t("schedule").format(h=r["horario"]))
                with st.expander(t("why_note")):
                    for razon in r.get("_razones", []):
                        st.write(f"- {razon}")
                b = t("badges")
                badges = []
                if r["takeaway"] in ("yes", "only"):
                    badges.append(b["llevar"])
                if r["vegan"]:
                    badges.append(b["vegano"])
                elif r["vegetarian"]:
                    badges.append(b["vegetariano"])
                if r["outdoor"]:
                    badges.append(b["terraza"])
                if r["indoor"]:
                    badges.append(b["salon"])
                if r["wheelchair"]:
                    badges.append(b["accesible"])
                if r["website"]:
                    badges.append(b["web"])
                if r["check_date"]:
                    badges.append(b["verif"].format(
                        d=str(r["check_date"])[:10]))
                if badges:
                    st.caption(" · ".join(badges))
                st.divider()
