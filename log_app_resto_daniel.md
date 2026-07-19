# LOG COMPLETO — TrouveTonResto (BuscaTuRestaurante)
# App para que Daniel elija dónde almorzar en Francia
================================================================================
ARCHIVO: log_app_resto_daniel.md  (en la carpeta del proyecto)
PROPÓSITO: registro completo de TODO lo aplicado en la app + su publicación,
para que cualquier mejora futura se entienda leyendo este archivo.
ÚLTIMA ACTUALIZACIÓN: 2026-07-19
MANTENEDOR: jox (usuario) + Hermes Agent (asistente)
================================================================================

--------------------------------------------------------------------------------
1. QUÉ ES LA APP Y PARA QUIÉN
--------------------------------------------------------------------------------
Problema que resuelve:
  "¿Qué quieres comer?" -> "no sé" -> hambre -> Uber Eats -> siempre lo mismo.
  La app DECIDE POR Daniel (hijo de 16 años, vive/estudia en Francia) para
  romper esa rutina. Busca restaurantes REALES vía OpenStreetMap y los ordena
  por un "Índice de Recomendación" (0-100) basado en señales honestas de la
  comunidad OSM (no hay estrellas en OSM Francia, así que se usan proxies:
  frescura de datos, para-llevar, opciones dietéticas, completitud de ficha).

Usuario final: Daniel (16 años). Va rápido, móvil, French. Por eso los botones
son GIGANTES, NARANJAS y PULSANTES, y el texto en francés juvenil.

DECISIÓN DE DISEÑO CLAVE (no cambiar sin avisar):
  - Título: "🍽️ Daniel, señor duerme más — Déjeune vite, je choisis pour toi"
    Es una frase cariñosa para Daniel; él debe sentir que la app está HECHA
    PARA ÉL. NO cambiar el "señor duerme más" por otra cosa.
  - Idioma de la app: 100% FRANCÉS (se purgaron es/en en commit d84d841).
  - Botón principal: "🎲 Je sais pas, choisis pour moi" (texto acordado con el
    usuario; estilo juvenil coherente con "Papa, no sé, mais l'appli choisit
    pour moi").

--------------------------------------------------------------------------------
2. STACK TÉCNICO
--------------------------------------------------------------------------------
- Lenguaje: Python 3.12 (venv en .venv/; arranca con ./run.sh -> puerto 8501)
- Framework: Streamlit 1.59.1 (OJO: en 1.59 components.html() devuelve
  DeltaGenerator, NO el valor del componente -> por eso el GPS usa otra vía).
- Datos: OpenStreetMap (SIN API key, open source, sin depender de corporates):
    * Geocodificación PRINCIPAL: Photon (komoot)  https://photon.komoot.io/api/
    * Geocodificación RESPALDO: Nominatim          https://nominatim.openstreetmap.org/search
      (solo si Photon falla; siempre countrycodes=fr para restringir Francia)
    * Búsqueda de POIs (restaurantes): Overpass API https://overpass-api.de/api/interpreter
- GPS: streamlit_js_eval.get_geolocation() (librería open source, usa la API
  del navegador; SIN API key).
- Mapa/enlace: Google Maps solo para el ENLACE al restaurante elegido (aceptado
  por el usuario; NO se usa la API de Places, para no depender de Google).
- Filosofía: open source / self-managed. Sin cuentas de corporaciones grandes.

ARCHIVOS DEL REPOSITORIO (github.com/canito667/buscaturestaurante, rama main):
  app.py              -> código principal (1035 líneas aprox)
  requirements.txt    -> dependencias (streamlit, requests, pyarrow<18, streamlit-js-eval)
  runtime.txt         -> "python-3.12" (OBLIGATORIO: Streamlit Cloud usa 3.13
                         por defecto y pyarrow<18 no tiene wheel para 3.13 -> segfault)
  run.sh              -> arranca en local (streamlit run app.py --server.port 8501)
  .streamlit/config.toml -> config de Streamlit
  README.md           -> (existe en repo)
  RECUPERACION.md     -> archivo de recuperación para retomar sesiones
  LOG_SESION.md       -> log de sesión (SOLO LOCAL, no se commitea)
  log_app_resto_daniel.md -> ESTE archivo

--------------------------------------------------------------------------------
3. ESTADO ACTUAL (al cierre de 2026-07-19, commit 2e921af)
--------------------------------------------------------------------------------
APP CONFIRMADA PÚBLICA y funcionando en la nube (sin muro de login; se hizo
pública a propósito para que Daniel y amigos la abran sin cuenta de Streamlit).

FUNCIONALIDAD:
  [OK] Buscador por texto: ciudad / código postal (5 dígitos) / dirección en
       Francia. Resuelve "75008", "Lyon", "3 bis rue Pasteur 94270", etc.
  [OK] Botones rápidos de ciudad (pending_city) y sugerencias con corrección
       de dedo (raspai->raspail) y manejo de "3 bis"/"3ter".
  [OK] Radio de búsqueda ajustable (slider 500-3000 m, default 1200).
  [OK] Filtros: solo/acompañado, para llevar, dieta (omnívoro/veg/vegano),
       solo si abierto ahora.
  [OK] Índice de Recomendación 0-100 y lista de candidatos ordenada.
  [OK] Botón "DECIDE / elegir al azar": el CORAZÓN de la app. Elige uno al
       azar ponderado por score (random.choices), suelta globos, vibra el
       móvil, muestra caja naranja gigante con el restaurante + enlace Maps +
       frase irónica + razones del score.
  [OK] GPS ("cerca de ti"): al pulsar DECIDE sin haber buscado, pide ubicación
       y busca restaurantes cerca. Funciona en HTTPS (nube) y localhost; en
       móvil por IP local (http://192.168.x.x) el navegador lo bloquea -> usa
       la versión en línea (HTTPS).
  [OK] Fallback si niega el GPS: "Ville au hasard" (ciudad al azar de la lista).

DISEÑO / UX:
  [OK] Título en francés (ver frase en sección 1).
  [OK] Botón DECIDE de ARRIBA: "🎲 Je sais pas, choisis pour moi" (naranja,
       pulsante). Si no hay resultados -> activa GPS; si ya los hay -> elige.
  [OK] Botón DECIDE de ABAJO (tras los resultados): "🎲 Je sais pas, choisis
       pour moi" (naranja, pulsante). ELIGE al azar. Este es el que faltaba y
       se reparó en el commit 2e921af (ver sección 4).
  [OK] Botón "🔍 Chercher": verde menta, pulsante, campo con borde verde animado.
  [OK] Vibración en móvil al elegir (navigator.vibrate 200 ms).
  [OK] CSS aislado: solo los botones DECIDE quedan naranjas (selector por key
       .st-key-decide_grande y .st-key-decide_resultados), no afecta a Chercher.

FUENTES DE DATOS (verificadas):
  [OK] Photon 200, Nominatim 200, Overpass 200. Restaurantrs reales devueltos
       (p.ej. búsqueda "Paris" -> 300 resultados; "Chez Nicos" 39/100, etc.).

--------------------------------------------------------------------------------
4. HISTORIAL DE CAMBIOS APLICADOS (de más reciente a más viejo)
--------------------------------------------------------------------------------
Cada cambio tiene su commit. Para entender el estado, lee de abajo hacia arriba.

- 2e921af (2026-07-19): FIX crítico. El agente de "botón único" fusionó mal y
  dejó el botón de elegir al azar desplazado/confuso. Se REINYECTÓ el botón
  "🎲 Je sais pas, choisis pour moi" (key=decide_resultados) justo TRAS los
  resultados, cableado a elegir_restaurante(candidatos). CSS DECIDE_CSS
  ampliado a .st-key-decide_resultados para que también quede naranja.
  -> Esto devolvió el CORAZÓN de la app (elegir restaurante al azar).

- 73df307 (2026-07-19): Botón DECIDE único gigante arriba (fusión de los dos
  antiguos), vibración móvil (components.html + navigator.vibrate), CSS aislado
  por key, y REVERSIÓN del título al original "Daniel, señor duerme más" (un
  subagente anterior lo había cambiado por error a "encore 5 minutes").

- da3bb8d (2026-07-19): Depuración general. Quitó import streamlit.components.v1
  muerto (luego se reañadió para la vibración), función get_coordinates() sin
  usar, claves I18N muertas. Corrigió bug de idioma: comparación de dirección
  "Dirección no disponible" -> "Adresse non disponible" (antes un restaurante
  sin dirección mostraba la etiqueta cruda en español). Botón DECIDE -> francés
  "Je sais pas, choisis pour moi".

- 4b5261a (2026-07-19): FIX GPS. components.html + navigator.geolocation era
  CÓDIGO MUERTO en Streamlit 1.59 (devolvía DeltaGenerator, no el dict). Cambiado
  a streamlit_js_eval.get_geolocation(component_key="geo_btn") que SÍ devuelve
  dict real {coords:{latitude,longitude}, timestamp} o {error:{message}}. Se
  añadió streamlit-js-eval a requirements.txt. Caja glow en francés envuelve el
  botón "Get location" (inglés, no configurable en la lib).

- de10692 (2026-07-19): Botones Chercher (verde) y Decide (naranja) con efecto
  visual pulso/brillo + st.balloons() al elegir.

- 64007da / d84d841 (2026-07-19): purga de idiomas es/en -> 100% francés;
  efecto visual movido al campo de búsqueda (borde verde animado).

- 3c7208d (2026-07-18): eliminado el bloque GPS completo (no funcionaba al
  usuario en móvil); quedó solo buscador por texto. (Luego el GPS se reparó
  correctamente en 4b5261a.)

- Historial previo (2026-07-13/14): búsqueda por CP, botón GPS vía components.html
  (descartado), get_geolocation con cuelgue (fix b928a19), etc. Ver RECUPERACION.md
  para el detalle completo de esas sesiones.

NOTA SOBRE EL GPS (importante para mejoras):
  El GPS actual USA get_geolocation() que se ejecuta en CADA rerun mientras
  _gps_mode está activo. Tras pulsar su botón interno "Get location" y CONCEDER
  permiso, devuelve el dict y se dispara la búsqueda. Si se niega, muestra error
  + fallback "Ville au hasard". Verificado en navegador: el round-trip funciona
  (el navegador devolvió "User denied Geolocation" a Python y la app lo mostró).

--------------------------------------------------------------------------------
5. PUBLICACIÓN EN LA NUBE
--------------------------------------------------------------------------------
Plataforma: Streamlit Community Cloud (Snowflake) -> https://share.streamlit.io/
Repo conectado: github.com/canito667/buscaturestaurante (rama main)
Archivo principal: app.py
URL PÚBLICA:
  https://buscaturestaurante-fwzt79fl7pyzh7a3nwekr5.streamlit.app/

Cómo se despliega:
  - Al hacer `git push origin main`, Streamlit Cloud detecta el cambio y
    redespiega solo (tarda 1-2 minutos).
  - Requisito crítico: runtime.txt con "python-3.12" (ver sección 2).
  - La app es PÚBLICA (sin muro de login) para que Daniel y amigos la abran sin
    cuenta. Si en el futuro se quiere privacidad, se puede migrar a Hugging Face
    Spaces (también público sin login, open source) — app.py + requirements.txt,
    sin secretos.

Último deploy: commit 2e921af (2026-07-19).

SEGURIDAD (leer antes de tocar tokens):
  - El push se hace con un token clásico de GitHub (ghp_...) en variable de
    entorno GIT_TOKEN, NUNCA escrito en archivos ni en el código.
  - Comando de push:
      export GIT_TOKEN="ghp_xxxx"
      git -c "url.https://canito667:${GIT_TOKEN}@github.com/.insteadOf=https://github.com/" push origin main
      unset GIT_TOKEN
  - El token usado en esta sesión (ghp_lA...Ivvy) debe REVOCARSE en GitHub
    (Settings -> Developer settings -> Personal access tokens) tras cada uso.
  - NUNCA reutilizar ni guardar tokens en memoria/notas.

--------------------------------------------------------------------------------
6. CÓMO APLICAR UNA MEJORA LEYENDO ESTE LOG
--------------------------------------------------------------------------------
Cuando Daniel o los amigos den feedback y haya que mejorar:

1. LEER ESTE ARCHIVO primero: dice qué hay, qué texto es intocable (título,
   botón DECIDE en francés), y qué commits hicieron qué.
2. Arrancar en local para reproducir:
     cd /home/jox/Proy_rest_beta && ./run.sh
     abrir http://localhost:8501
3. Buscar en app.py las zonas clave (líneas aproximadas, pueden variar):
     - Título I18N["fr"]["title"]            (~línea 479)
     - Botón DECIDE arriba (key decide_grande)  (~línea 799)
     - Bloque GPS (_gps_mode, get_geolocation) (~línea 810+)
     - Botón DECIDE abajo (key decide_resultados) (~línea 997)
     - función elegir_restaurante()          (~línea 726)
     - Bloque de búsqueda (search_button)    (~línea 880)
4. Hacer el cambio, verificar:
     - Compilar: ./.venv/bin/python -m py_compile app.py
     - Probar en navegador real (browser_snapshot) que renderiza y el botón
       DECIDE funciona. Compilar OK y HTTP 200 NO bastan para UI.
5. Commitear y pushear (ver sección 5, con token fresco).
6. ACTUALIZAR ESTE ARCHIVO (log_app_resto_daniel.md) con el nuevo cambio al
   final de la sección 4 y subir el commit. Así el historial permanece completo.

--------------------------------------------------------------------------------
7. PENDIENTE / IDEAS DE MEJORA (feedback de Daniel y amigos)
--------------------------------------------------------------------------------
[ESPACIO PARA ANOTAR COMENTARIOS REALES DE DANIEL Y AMIGOS]
- (vacío al cierre de 2026-07-19; llénalo conforme llegue feedback)

Ideas ya evaluadas por el agente de análisis (NO aplicadas aún, a decisión del
usuario; todas open source, sin API key):
  - Top-3 + "sortear entre estos 3" (modo secundario).
  - Modo sorpresa (ignora filtros blandos, NUNCA "abierto ahora").
  - TTS / voz (Web Speech API del navegador, sin libs).
  - streamlit-shuffle para animación tipo ruleta al revelar el elegido.
  (Ver /home/jox/.hermes/informe_decide_por_mi.md para la tabla comparativa.)

================================================================================
FIN DEL LOG — TrouveTonResto / BuscaTuRestaurante
Mantener este archivo al día es CLAVE para que las mejoras futuras sean rápidas.
================================================================================
