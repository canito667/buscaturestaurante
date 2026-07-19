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
import streamlit.components.v1 as components
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
PHOTON_URL = "https://photon.komoot.io/api/"   # open source, OSM, sin API key
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

UTIL_TAGS = [  # etiquetas que indican una ficha "cuidada" por la comunidad
    "website", "phone", "contact:facebook", "opening_hours", "cuisine",
    "wheelchair", "outdoor_seating", "indoor_seating", "takeaway",
    "diet:vegetarian", "diet:vegan", "addr:street",
]

# Países donde buscamos restaurantes (OpenStreetMap, sin API key).
# 'nombres' = palabras que detectan el país en los resultados del geocodificador.
# 'iso'     = código ISO 3166 para la API de Nominatim (countrycodes).
# 'capital' = ciudad por defecto para corregir el dedo cuando no hay ciudad.
# 'ciudades'= ciudades conocidas (evita forzar la capital por error).
PAISES = {
    "fr": {"iso": "fr", "nombres": ("france",), "capital": "Paris",
           "ciudades": {"paris", "lyon", "marseille", "toulouse", "nice",
                        "nantes", "lille", "bordeaux", "strasbourg", "rennes"}},
    "nl": {"iso": "nl", "nombres": ("netherlands", "pays-bas", "holland"),
           "capital": "Amsterdam",
           "ciudades": {"amsterdam", "rotterdam", "utrecht", "eindhoven",
                        "groningen", "maastricht", "leiden", "delft",
                        "den haag", "the hague", "la haye"}},
}


def _pais_de(texto):
    """Devuelve el código ('fr'/'nl') si el texto menciona un país buscado,
    o None. Insensible a mayúsculas/minúsculas."""
    t = texto.lower()
    for code, info in PAISES.items():
        if any(nom in t for nom in info["nombres"]):
            return code
    return None


def _es_pais_buscado(texto):
    """True si el texto menciona Francia o Países Bajos."""
    return _pais_de(texto) is not None


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


def _photon(q, limit=5):
    """Geocodifica con Photon (komoot, open source, OSM, sin API key ni
    rate-limit duro). Devuelve lista de (lat, lon, display_name, es_francia)."""
    try:
        resp = requests.get(PHOTON_URL, params={"q": q, "limit": limit},
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        feats = resp.json().get("features", [])
        out = []
        for f in feats:
            c = f["geometry"]["coordinates"]
            p = f["properties"]
            name = p.get("name") or ""
            parts = [x for x in (p.get("street"), p.get("housenumber"),
                     p.get("postcode"), p.get("city"), p.get("country")) if x]
            label = (name + ", " if name else "") + ", ".join(parts)
            out.append((float(c[1]), float(c[0]), label,
                        _pais_de(p.get("country", ""))))
        return out
    except Exception:
        return []


@st.cache_data(show_spinner=False)
def geocode_help(location_query):
    """Devuelve (lat, lon, display_name, [alternativas]) para la busqueda.
    Usa Photon como fuente principal (open source, OSM, sin rate-limit duro)
    y Nominatim como respaldo si Photon falla. Filtra a Francia. Si el texto
    son 5 digitos, lo trata como codigo postal frances."""
    q = location_query.strip()
    # 1) Photon (principal)
    res = _photon(q, limit=5)
    if res:
        en_pais = [r for r in res if r[3]]   # resultados en FR o NL
        top_list = en_pais or res
        top = top_list[0]
        alts = [r[2] for r in top_list[1:6]]
        return (top[0], top[1], top[2], alts)
    # 2) Respaldo Nominatim (postalcode si 5 digitos)
    codigos = ",".join(info["iso"] for info in PAISES.values())  # "fr,nl"
    postal = q if (q.isdigit() and len(q) == 5) else None
    def _nom():
        if postal:
            params = {"postalcode": postal, "countrycodes": codigos,
                      "format": "json", "limit": 5, "addressdetails": 1}
        else:
            params = {"q": q, "format": "json", "limit": 5,
                      "addressdetails": 1, "countrycodes": codigos}
        r = requests.get(NOMINATIM_URL, params=params,
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    time.sleep(1.0)  # politica Nominatim: 1 peticion/segundo
    try:
        for intento in range(6):
            data = _nom()
            if data:
                break
            time.sleep(1.5 * (intento + 1))
        if not data:
            return None, None, "", []
        en_pais = [d for d in data if _es_pais_buscado(d.get("display_name", ""))]
        top = (en_pais or data)[0]
        alts = [d.get("display_name", "") for d in (en_pais or data)[1:6]]
        return (float(top["lat"]), float(top["lon"]),
                top.get("display_name", q), alts)
    except Exception:
        return None, None, "", []


def geocode_suggestions(location_query, max_res=5):
    """Si la busqueda directa falla, prueba variantes similares y devuelve
    hasta `max_res` candidatos validos (lat, lon, display_name) para que el
    usuario elija. Variantes: sin el numero (maneja '3 bis'/'3ter'), calle +
    Paris (la app es para Francia), sin acentos, solo ciudad, y añadir una 'l'
    al final de la ultima palabra (corrige el dedo: 'raspai' -> 'raspail').
    Prioriza Francia y respeta el rate-limit de Nominatim (1s entre llamadas).
    """
    def _norm(s):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", s)
                       if unicodedata.category(c) != "Mn")
    def _fetch(q):
        # Photon (open source, OSM, sin rate-limit duro) en vez de Nominatim
        ph = _photon(q, limit=1)
        if ph:
            return ph[0][0], ph[0][1], ph[0][2], ph[0][3]
        return None
    # quita el numero inicial, incluido sufijo 'bis'/'ter'/'b'/'ter'
    toks = location_query.split()
    cuerpo = toks[1:] if (toks and toks[0].isdigit()) else toks
    if cuerpo and cuerpo[0].lower() in ("bis", "ter", "b", "ter", "quater"):
        cuerpo = cuerpo[1:]
    variants = []
    if cuerpo:                                  # "rue Pasteur 94270"
        variants.append(" ".join(cuerpo))
    if "," in location_query:                     # "12, rue x, paris"
        partes = [p.strip() for p in location_query.split(",")]
        variants.append(", ".join(partes[:-1]))
        variants.append(partes[-1])
    last = toks[-1] if toks else ""
    # corrige el dedo: ultima palabra larga acabada en vocal -> añade 'l'
    # Ciudades conocidas para no volver a forzar la capital por error
    CIUDADES = set()
    for _info in PAISES.values():
        CIUDADES |= _info["ciudades"]
    # Si el texto parece de Países Bajos, forzamos Amsterdam en vez de Paris
    q_low = location_query.lower()
    es_nl = any(n in q_low for n in PAISES["nl"]["nombres"]) or any(
        c in q_low for c in PAISES["nl"]["ciudades"])
    capital_defecto = "Amsterdam" if es_nl else "Paris"
    if (last and last[-1].lower() in "aeiouy" and len(last) >= 4
            and last.lower() not in CIUDADES):
        variants.append(" ".join(toks[:-1] + [last + "l"]))
    if capital_defecto.lower() not in q_low and last:   # fuerza la capital
        variants.append(" ".join(toks[:-1] + [last, capital_defecto]))
    variants.append(_norm(location_query))        # sin acentos
    variants.append(last)                          # solo la ciudad
    # quita duplicados manteniendo orden
    seen, uniq = set(), []
    for v in variants:
        v = v.strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            uniq.append(v)
    en_pais, fuera = [], []
    for v in uniq:
        if len(en_pais) + len(fuera) >= max_res:
            break
        r = _fetch(v)
        if r:
            (en_pais if r[3] else fuera).append((r[0], r[1], r[2]))
    return (en_pais + fuera)[:max_res]



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
def compute_score(r, solo, takeaway_only, diet, open_now, lang="fr"):
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
    return I18N["fr"].get(key)


I18N = {
    "fr": {
        "lang_label": "🌐 Langue",
        "title": "🍽️ Daniel, señor duerme más — Déjeune vite, je choisis pour toi",
        "subtitle": "Arrête de dire «je sais pas» : on te propose de bonnes "
                    "options en France ou aux Pays-Bas, classées par ce que la communauté recommande vraiment",
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
        "dest_label": "📍 Où déjeunes-tu aujourd'hui ? (ville, code postal ou adresse en France) :",
        "dest_placeholder": "Ex : Paris, 75011, Amsterdam ou 3 bis rue Pasteur 94270",
        "gps_hint": "Utilise ma position pour chercher les restos près de moi",
        "quick_cities": "⚡ Villes rapides (tape et cherche) :",
        "search": "🔍 Chercher",
        "radius": "📏 Rayon de recherche (m) :",
        "companion_q": "🧑‍🤝‍🧑 Seul ou accompagné ?",
        "solo": "Seul (rapide, à emporter)",
        "acco": "Accompagné (sur place)",
        "filters": "⚙️ Filtres",
        "takeaway": "🥡 À emporter uniquement",
        "diet": "🥗 Régime :",
        "diet_none": "Omnivore",
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
        "geo_none_tip": "Essaie : ajoute **France** ou **Pays-Bas**, enlève les "
                        "accents (Café -> Cafe), ou une ville connue proche "
                        "(Paris, Lyon, Amsterdam). Je crois en toi. Un peu.",
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
    }
}

# Razones del índice (lenguaje-neutral -> traducido por idioma)
REASONS = {
    "verif_fresco": {
        "fr": "🕒 Vérifié par la communauté en {y} (données fraîches)"},
    "verif_old": {
        "fr": "🕒 Vérifié en {y} (données un peu anciennes)"},
    "verif_ancien": {
        "fr": "🕒 Vérifié il y a longtemps ({y})"},
    "verif_ilegible": {
        "fr": "🕒 Vérifié par la communauté (date illisible)"},
    "no_verif": {
        "fr": "⚠️ Personne n'a vérifié cet endroit récemment"},
    "takeaway_solo": {
        "fr": "🥡 À emporter : idéal pour manger vite et repartir"},
    "rapida": {
        "fr": "⚡ Cuisine rapide : peu d'attente"},
    "sentarse": {
        "fr": "🪑 A des places assises : pratique en groupe"},
    "takeaway_acco": {
        "fr": "🥡 Aussi à emporter, si tu es pressé"},
    "no_vegan": {
        "fr": "❌ Pas vegan (filtre actif)"},
    "no_takeaway": {
        "fr": "❌ Pas à emporter (filtre actif)"},
    "no_veg": {
        "fr": "❌ Pas végétarien (filtre actif)"},
    "vegan_ok": {
        "fr": "🥗 Vraie option vegan"},
    "veg_ok": {
        "fr": "🥗 Option végétarienne/vegan"},
    "cerrado": {
        "fr": "❌ Fermé en ce moment"},
    "ficha_buena": {
        "fr": "📋 Fiche bien documentée par la communauté (+{tc})"},
    "ficha_parcial": {
        "fr": "📋 Fiche partiellement documentée (+{tc})"},
    "variedad": {
        "fr": "🍜 Cuisine {c} : change from the usual"}
}

# Frases irónicas por idioma (la app decide por ti sabiendo que no debería)
FRASES_IRONICAS = {
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
    ]
}


# ---------------------------------------------------------------------------
# INTERFAZ
# ---------------------------------------------------------------------------
st.title(t("title"))
st.subheader(t("subtitle"))

# --- Paso 1: destino ---
if "resultados" not in st.session_state:
    st.session_state.resultados = None  # lista de restaurantes ya obtenidos

# Ciudad elegida con un boton rapido (no escribimos en el widget de texto,
# porque Streamlit no permite asignar a la clave de un widget ya creado).
if "pending_city" not in st.session_state:
    st.session_state.pending_city = ""

# --- Boton "DECIDE POR MI" con GPS: restaurantes CERCA de donde esta Daniel ---
# navigator.geolocation solo funciona en contexto seguro (localhost o HTTPS).
# En el PC (http://localhost:8501) funciona. En el iPhone por IP local
# (http://192.168.x.x:8501) el navegador BLOQUEA el GPS (exige HTTPS); ahi
# damos un fallback a ciudad al azar (abajo).
import random as _rnd
VILLES_FR = ["Paris", "Lyon", "Marseille", "Toulouse", "Nice", "Nantes",
             "Montpellier", "Strasbourg", "Bordeaux", "Lille", "Rennes",
             "Reims", "Saint-Etienne", "Le Havre", "Toulon", "Grenoble",
             "Amsterdam", "Rotterdam", "Utrecht", "La Haye", "Eindhoven"]
GPS_HTML = """
<script>
function pedir(){
  if(typeof Streamlit === "undefined") return;
  if(!navigator.geolocation){
    Streamlit.setComponentValue({error:"Geolocalizacion no disponible"});
    return;
  }
  navigator.geolocation.getCurrentPosition(
    function(pos){ Streamlit.setComponentValue({lat:pos.coords.latitude, lon:pos.coords.longitude}); },
    function(err){ Streamlit.setComponentValue({error: err.message || "Permiso denegado"}); },
    {enableHighAccuracy:true, timeout:10000, maximumAge:0}
  );
}
if(window.Streamlit){ pedir(); }
else { window.addEventListener("streamlit:loaded", pedir); }
</script>
<div style='font-size:14px;color:#555'>📡 Demande de position GPS…</div>
"""

# Bouton "Chercher" : meme effet XL + pulsation que le bouton decide, mais en
# vert menthe (couleur calme pour la vue), pour que Daniel le remarque aussi.
# On garde un vrai st.button (retour bool fiable) et on le stylise via CSS
# global cible SUR LE SEUL bouton dont la cle est "chercher_btn" : Streamlit
# genere la classe .st-key-chercher_btn sur son conteneur -> ne teinte AUCUN
# autre bouton (le GPS est dans un iframe isole, et decide est type="primary").
CHERCHER_CSS = """
<style>
.st-key-chercher_btn button{
  width:100% !important;height:66px !important;font-size:22px !important;
  font-weight:800 !important;color:#063b2e !important;
  background-image:linear-gradient(135deg,#5fe3b0,#19b98a) !important;
  background-color:transparent !important;
  border:3px solid #fff !important;border-radius:16px !important;cursor:pointer;
  box-shadow:0 0 0 0 rgba(25,185,138,.7) !important;
  animation:chercherPulse 1.6s ease-in-out infinite !important;
}
/* Pulse = ONLY a glow (box-shadow), never a transform: the button must not
   move so the click always lands (some browsers miss clicks on scaled btns). */
@keyframes chercherPulse{
  0%{box-shadow:0 0 0 0 rgba(25,185,138,.7);}
  50%{box-shadow:0 0 26px 10px rgba(25,185,138,.55);}
  100%{box-shadow:0 0 0 0 rgba(25,185,138,.7);}
}
</style>
"""

# Style du bouton "Je sais pas, choisis pour moi" (Daniel, 16 ans, 100 km/h) :
# on le rend XL, orange et pulsant pour qu'il soit impossible a rater.
# On l'applique via CSS global cible sur LE SEUL bouton type="primary".
# NOTE: components.html renvoie un DeltaGenerator en Streamlit 1.59 (et pas la
# valeur du composant), donc on garde un vrai st.button (retour bool fiable).
DECIDE_CSS = """
<style>
button[kind="primary"]{
  font-size:22px !important;font-weight:800 !important;height:66px !important;
  border-radius:16px !important;width:100%;
  background-image:linear-gradient(135deg,#ff6a00,#ff2d00) !important;
  background-color:transparent !important;
  color:#000 !important;border:3px solid #fff !important;cursor:pointer;
  box-shadow:0 0 0 0 rgba(255,106,0,.7) !important;
  animation:decidePulse 1.5s ease-in-out infinite !important;
}
@keyframes decidePulse{
  0%{box-shadow:0 0 0 0 rgba(255,106,0,.75);}
  50%{box-shadow:0 0 26px 10px rgba(255,106,0,.6);}
  100%{box-shadow:0 0 0 0 rgba(255,106,0,.75);}
}
</style>
"""

if st.button("🎲 DECIDE POR MÍ (cerca de ti)", key="decide_grande",
             use_container_width=True):
    st.session_state["pending_city"] = ""
    st.session_state["_gps_mode"] = True
    st.rerun()

radius = st.slider(t("radius"), 500, 3000, 1200, 100)

# --- Camino GPS: tras pulsar "DECIDE POR MI", esperamos la posicion ---
if st.session_state.get("_gps_mode"):
    st.info("📡 Autorise la localisation pour chercher pres de toi.")
    _gps = components.html(GPS_HTML, height=50)
    if isinstance(_gps, dict) and _gps:
        st.session_state["_gps_mode"] = False
        if "error" in _gps:
            st.session_state["_gps_error"] = _gps["error"]
        else:
            with st.spinner(t("osm")):
                time.sleep(0.5)
                st.session_state.resultados = get_restaurants_nearby(
                    _gps["lat"], _gps["lon"], radius=radius)
                st.session_state.display_name = "Pres de toi (GPS)"
            st.session_state["geo_alts"] = []
        st.rerun()

if st.session_state.get("_gps_error"):
    st.error(f"❌ GPS impossible : {st.session_state['_gps_error']}")
    st.info("Le GPS exige HTTPS (ou localhost sur ordinateur). Sur iPhone en "
            "WiFi local (http://IP), le navigateur le bloque. Solution : "
            "utilise la version en ligne (HTTPS) ou ce PC en localhost.")
    if st.button("🎲 Ville au hasard (sans GPS)", key="fallback_gps"):
        st.session_state["_gps_error"] = ""
        st.session_state["pending_city"] = _rnd.choice(VILLES_FR)
        st.session_state["_auto_search"] = True
        st.rerun()

location_query = st.text_input(
    t("dest_label"),
    key="location_query",
    placeholder=t("dest_placeholder"),
    label_visibility="collapsed")

# Bouton "Chercher" XL + vert pulsant (meme effet que decide, couleur calme).
# On garde un vrai st.button (retour bool fiable, sans depends du runtime
# Streamlit de l'iframe) et on le stylise via CSS global cible SUR LE SEUL
# bouton dont la cle est "chercher_btn" (classe .st-key-chercher_btn generee
# par Streamlit, unique -> ne teinte aucun autre bouton).
st.markdown(CHERCHER_CSS, unsafe_allow_html=True)
search_button = st.button(t("search"), key="chercher_btn", use_container_width=True)
# El boton gigante "DECIDE POR MI" fuerza la busqueda con la ciudad elegida
if st.session_state.get("_auto_search"):
    st.session_state["_auto_search"] = False
    search_button = True

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
            # Busca variantes similares y las propone para que elijas
            sugs = geocode_suggestions(query)
            if sugs:
                st.markdown("### 🔎 Pas trouvé ? Essaie l'une de celles-ci :")
                for i, (slat, slon, sname) in enumerate(sugs):
                    if st.button(sname, key=f"sug_{i}",
                                 use_container_width=True):
                        st.session_state["geo_candidato"] = (slat, slon, sname)
                        st.session_state["geo_alts"] = []
                        st.session_state.resultados = get_restaurants_nearby(
                            slat, slon, radius=radius)
                        st.session_state.display_name = sname
                        st.rerun()
            if st.button("↻ Réessayer", key="retry_geo_btn",
                         use_container_width=True):
                st.session_state["pending_city"] = query
                st.rerun()
        else:
            # ¿El resultado parece Francia? Si no, advertir y proponer alternativas.
            es_pais = _es_pais_buscado(display_name)
            if not es_pais and alts:
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
                                    lang="fr")
        if s > 0:
            r["_score"] = s
            r["_razones"] = razones
            candidatos.append(r)
    candidatos.sort(key=lambda r: r["_score"], reverse=True)

    if not candidatos:
        st.warning(t("no_results"))
    else:
        st.success(t("recommended").format(n=len(candidatos)))

        # Boton "Je sais pas, choisis pour moi" EXTRA-visible: Daniel (16 ans,
        # 100 km/h, ne lit pas les details). Taille XL + couleur flash +
        # animation pulse/brillance pour qu'il voie que le bouton existe.
        # On utilise un vrai st.button (retour bool fiable) : en Streamlit 1.59
        # components.html renvoie un DeltaGenerator (pas la valeur), ce qui
        # provoquait "get() is not a valid Streamlit command". Le style
        # naranja/pulso vient de DECIDE_CSS (CSS global sur le seul bouton
        # type="primary").
        st.markdown(DECIDE_CSS, unsafe_allow_html=True)
        if st.button(t("decide"), type="primary", key="decide_btn",
                     use_container_width=True):
            # Globos subiendo desde abajo (effet "fete") quand Daniel choisit.
            st.balloons()
            pesos = [max(1, r["_score"]) for r in candidatos]
            elegido = random.choices(candidatos, weights=pesos, k=1)[0]
            frase = random.choice(FRASES_IRONICAS["fr"])
            maps_url = gmaps_link(elegido)
            # Resultado ULTRA-destacado para Daniel (16 ans, 100 km/h, ne lit
            # pas les details) : grosse caisse orange, nom en lettres GEANTES,
            # separe nettement du reste.
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#ff6a00,#ff2d00);'
                f'color:#fff;border-radius:18px;padding:22px 26px;'
                f'text-align:center;box-shadow:0 0 26px 6px rgba(255,106,0,.55);'
                f'margin:14px 0;">'
                f'<div style="font-size:15px;font-weight:700;letter-spacing:1px;'
                f'opacity:.95;">🍽️ TON RESTO</div>'
                f'<div style="font-size:40px;font-weight:900;line-height:1.1;'
                f'margin:8px 0;">{elegido["nombre"]}</div>'
                f'<div style="font-size:18px;font-weight:700;">'
                f'{elegido["cocina"]} · {elegido["_score"]}/100</div>'
                f'</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div style="text-align:center;margin:6px 0 14px;">'
                f'<a href="{maps_url}" target="_blank" rel="noopener" '
                f'style="display:inline-block;background:#111;color:#fff;'
                f'font-weight:800;font-size:17px;padding:12px 20px;'
                f'border-radius:12px;text-decoration:none;">📍 Ouvrir dans Google Maps</a>'
                f'</div>', unsafe_allow_html=True)
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
