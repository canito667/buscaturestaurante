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
#   2. Yo leo el "ESTADO ACTUAL" y los "COMANDOS RAPIDOS" y continúo.
# =====================================================================

## DATOS DEL PROYECTO
- Nombre app: TrouveTonResto (BuscaTuRestaurante)
- Carpeta local: /home/jox/Proy_rest_beta
- Repo GitHub: https://github.com/canito667/buscaturestaurante (rama main)
- App en la nube: https://buscaturestaurante-fwzt79fl7pyzh7a3nwekr5.streamlit.app/
- Usuario GitHub: canito667  (push con token clasico ghp_ en variable de entorno, NO escrito en archivos)
- Lenguaje app: frances fijado (sin selector de idioma)
- Stack: Streamlit + OpenStreetMap (Nominatim geocodifica, Overpass trae POIs)
- Python: 3.12  (venv en .venv/ ; arranca con ./run.sh -> puerto 8501)
- IMPORTANTE deploy: runtime.txt con "python-3.12" obligatorio (Streamlit Cloud
  usa 3.13 por defecto y pyarrow<18 no tiene wheel para 3.13 -> segfault).

## ESTADO ACTUAL (ultima actualizacion: 2026-07-13)
- Funciona: busqueda por direccion escrita (probado local: "12 Rue de la Paix,
  Paris" -> 300 restaurantes reales de OSM).
- Funciona: botones rapidos (Paris, Lyon, Marseille, Toulouse, Nice, Nantes)
  tras el arreglo del error StreamlitAPIException (linea 848 original).
- Arreglado hoy: la busqueda por boton rapido escribia en
  st.session_state["location_query"] (clave de un widget) -> prohibido en
  Streamlit -> excepcion. Solucion: variable "pending_city" aparte.
- Pendiente de confirmar en NUBE: el usuario reporta que la busqueda por
  direccion "no funciona" en la app de Streamlit Cloud. En local SI funciona.
  Causa mas probable: despliegue en cola / cache de version anterior, o limite
  de Nominatim/Overpass en el servidor compartido de Streamlit Cloud.
  ACCION: tras este commit, pedir al usuario que recargue la nube y pruebe;
  si persiste, revisar logs de Streamlit Cloud (Manage app -> logs).

## COMANDOS RAPIDOS (copialos tal cual)
# Arrancar la app en local (pruebas):
  cd /home/jox/Proy_rest_beta && ./run.sh
  # luego abrir http://localhost:8501

# Hacer commit y push (usa token en env, no lo escribas en archivos):
  cd /home/jox/Proy_rest_beta
  git add app.py
  git commit -m "mensaje corto del cambio"
  export GIT_TOKEN="ghp_TU_TOKEN_AQUI"
  git -c "url.https://canito667:${GIT_TOKEN}@github.com/.insteadOf=https://github.com/" push origin main
  unset GIT_TOKEN

# Probar geocodificacion directa (sin Streamlit):
  cd /home/jox/Proy_rest_beta && ./.venv/bin/python -c "import app; print(app.geocode_help('12 Rue de la Paix, Paris'))"

# Ver estado del repo:
  cd /home/jox/Proy_rest_beta && git status && git log --oneline -3

## HISTORIAL DE CAMBIOS (nuevos arriba)
- 2026-07-13: (PENDIENTE PUSH) Busqueda por direccion escrita manda siempre;
  pending_city solo si el campo esta vacio (evita ciudad "pegada").
- 2026-07-13: Arreglo botones rapidos -> pending_city (commit 21e198d en la nube).
- 2026-07-13: Commit "App fijada a frances: quita selector de idioma" (4a1ce56).
- 2026-07-13: Commit "Quita todos los mapas: direccion resuelta con enlace
  Google Maps" (fdbaf71).
- 2026-07-13: Commit "Added Dev Container Folder" (e17a468).

## NOTAS DE SEGURIDAD
- El token ghp_ se paso en un chat anterior. RECOMENDADO: revocarlo y crear
  uno nuevo en GitHub (Settings -> Developer settings -> PAT) para evitar riesgos.
- Nunca escribas el token en app.py, .git/config ni en este archivo.
