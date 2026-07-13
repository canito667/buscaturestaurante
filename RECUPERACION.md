# =====================================================================
# ARCHIVO DE RECUPERACION — BuscaTuRestaurante (TrouveTonResto)
# =====================================================================
# PARA QUE SIRVE:
#   Si se te cierra el terminal o pierdes la conversacion, pasame ESTE
#   archivo y puedo retomar el trabajo sin que tengas que explicarlo todo
#   otra vez. Lo mantengo actualizado con cada cambio importante.
#
# COMO USARLO:
#   1. Copia el contenido de este archivo (o la ruta completa:
#      /home/jox/Proy_rest_beta/RECUPERACION.md) y pegalo en el chat.
#   2. Yo leo el "ESTADO ACTUAL" y los "COMANDOS RAPIDOS" y continuo.
# =====================================================================

## DATOS DEL PROYECTO
- Nombre app: TrouveTonResto (BuscaTuRestaurante)
- Proposito: para el hijo del usuario (Daniel), que "nunca sabe donde
  quiere comer". La app decide por el.
- Carpeta local: /home/jox/Proy_rest_beta
- Repo GitHub: https://github.com/canito667/buscaturestaurante (rama main)
- App en la nube: https://buscaturestaurante-fwzt79fl7pyzh7a3nwekr5.streamlit.app/
- Usuario GitHub: canito667 (push con token clasico ghp_ en variable de
  entorno, NO escrito en archivos)
- Lenguaje app: frances fijado (sin selector de idioma)
- Stack: Streamlit + OpenStreetMap. Geocodificacion:
  * PRINCIPAL: Photon (komoot, open source OSM, sin API key, sin
    rate-limit). URL: https://photon.komoot.io/api/
  * RESPALDO: Nominatim (https://nominatim.openstreetmap.org/search)
    SOLO si Photon falla. Siempre countrycodes=fr (restringir Francia).
- Busqueda de POIs: Overpass API (OSM).
- Python: 3.12 (venv en .venv/ ; arranca con ./run.sh -> puerto 8501)
- IMPORTANTE deploy: runtime.txt con "python-3.12" obligatorio
  (Streamlit Cloud usa 3.13 por defecto y pyarrow<18 no tiene wheel
  para 3.13 -> segfault).
- NUEVO dependencia: streamlit_js_eval (en requirements.txt) para el
  boton GPS fiable en la nube.

## ESTADO ACTUAL (ultima actualizacion: 2026-07-14)
- Titulo app (3 idiomas, opcion A elegida por usuario):
  es: "🍽️ Daniel, señor duerme más — Almuerza ya, que yo elijo por ti"
  en/fr: "🍽️ Daniel, señor duerme más — Déjeune vite, je choisis pour toi"
- Funciona: busqueda por direccion/CP/ciudad escrita, vía Photon
  (resuelve "75008", "75014", "Lyon", "3 bis rue Pasteur 94270" ->
  Le Kremlin-Bicêtre, etc.). Probado local y en nube.
- Funciona: botones rapidos de ciudad (pending_city).
- Funciona: sugerencias con correccion de dedo (raspai->raspail) y
  manejo de "3 bis"/"3ter".
- BOTON GPS "Usar mi ubicacion" (OPCION PRINCIPAL / heroe):
  * Ubicado ARRIBA del buscador por texto.
  * Caja verde animada (glow) con texto:
    "📍 Papa, no sé, mais l'appli choisit pour moi"
  * Debajo, el boton del componente streamlit_js_eval (dice "Get
    location" en ingles, no se puede cambiar el texto con get_geolocation).
  * Al pulsarlo y aceptar permiso GPS, rellena la busqueda con
    "lat, lon" y busca restaurantes cerca.
  * IMPLEMENTACION ACTUAL (commit b928a19): usa
    st_js.get_geolocation(component_key="geo_btn") — patron OFICIAL del
    paquete, que NO cuelga la pagina.
  * HISTORIAL de intentos (para no repetirlos):
    - components.html (deprecado) -> FALLO
    - declare_component(path=...) -> NO se sirve en Streamlit Cloud
    - HTML embebido st.markdown que escribe en text_input oculto ->
      FRAGIL, el evento no propaga -> FALLO
    - streamlit_js_eval con js_expressions=Promise que resuelve al click
      -> CUELGA la app (espera el resultado para terminar render) -> FALLO
    - get_geolocation() con key= en vez de component_key= -> TypeError
      (bug detectado en verificacion, corregido en 1018ba8)
    - get_geolocation(component_key=...) envuelto en caja glow -> OK

## COMANDOS RAPIDOS (copialos tal cual)
# Arrancar la app en local (pruebas):
  cd /home/jox/Proy_rest_beta && ./run.sh
  # luego abrir http://localhost:8501

# Hacer commit y push (usa token en env, no lo escribas en archivos):
  cd /home/jox/Proy_rest_beta
  git add app.py requirements.txt
  git commit -m "mensaje corto del cambio"
  export GIT_TOKEN="ghp_TU_TOKEN_AQUI"
  git -c "url.https://canito667:${GIT_TOKEN}@github.com/.insteadOf=https://github.com/" push origin main
  unset GIT_TOKEN

# Probar geocodificacion directa (sin Streamlit):
  cd /home/jox/Proy_rest_beta && ./.venv/bin/python -c "import app; print(app.geocode_help('75008'))"

# Ver estado del repo:
  cd /home/jox/Proy_rest_beta && git status && git log --oneline -5

# Verificar cambios sin suite (ad-hoc, /tmp, se borra):
#   crear /tmp/hermes-verify-X.py que importe app y pruebe la logica,
#   ejecutarlo con ./.venv/bin/python, luego rm.

## HISTORIAL DE CAMBIOS (nuevos arriba)
- 2026-07-14: Fix cuelgue boton GPS -> get_geolocation(envuelto caja
  glow). Commit b928a19.
- 2026-07-14: Fix bug get_geolocation usa component_key (no key).
  Commit 1018ba8.
- 2026-07-14: Boton GPS via streamlit_js_eval (intento fragil luego
  corregido). Commit 1919cf4.
- 2026-07-14: Boton GPS heroe texto 'Je sais pas papa...' + animacion
  glow/latido/radar (luego reemplazado). Commit c2bcbac.
- 2026-07-14: Titulo 'Daniel, senor duerme mas' + GPS via HTML
  embebido. Commit 6ca6b4f.
- 2026-07-14: Boton GPS migra de components.html a declare_component
  local (luego descartado: no se sirve en nube). Commit 8402819.
- 2026-07-13: Geocodificacion con Photon (OSM open source, sin
  rate-limit) + GPS via components.html. Commit e5cb990.
- 2026-07-13: CP 5 digitos busca por postalcode + boton GPS height
  visible. Commit 42cbb03.
- 2026-07-13: Restringe Francia (countrycodes=fr), placeholder
  CP/direccion, boton GPS cerca de mi. Commit 28acdc8.
- 2026-07-13: Geocodificacion reintentos + maneja '3 bis'. 56c825f.
- 2026-07-13: Sugerencias corrige dedo (raspai->raspail). a61af6e.
- 2026-07-13: Omnivoro como primera opcion diet. b960122.
- 2026-07-13: Quita expanders 'app mobile' y 'coment ca marche'. 162c80d.
- 2026-07-13: Quita botones villes rapidas. 8da1a3d.
- 2026-07-13: Geocode reintento + aviso mejorado. 3867cb2.
- 2026-07-13: Busqueda por texto manda siempre; pending_city si vacio. ddf6f84.
- 2026-07-13: Commit inicial botones rapidos pending_city. 21e198d.

## NOTAS DE SEGURIDAD
- El token ghp_ se paso en un chat anterior. RECOMENDADO: revocarlo y
  crear uno nuevo en GitHub (Settings -> Developer settings -> PAT) para
  evitar riesgos.
- Nunca escribas el token en app.py, .git/config ni en este archivo.
- LOG_SESION.md es SOLO LOCAL (no se commitea); este RECUPERACION.md
  SI esta en el repo para retomar desde cualquier lado.
