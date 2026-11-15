# Informe de la revisión semántica de tópicos

La revisión semántica se hizo por muestreo, con un modelo de lenguaje como anotador y sin validación humana. Cada uno de los 41 tópicos recibió una definición, criterios de inclusión y exclusión y sus límites observados; además se revisaron las etiquetas legibles de siete dimensiones y los nombres de los 32 códigos de idioma. La revisión quedó aplicada y versionada en ambas bases, sin modificar los datos de origen.

## Resultado semántico

**22 tópicos con soporte muestral y 19 de uso restringido.** Se conservan los 41 códigos, la versión del modelo, las claves sustitutas y las 233.556 pertenencias originales; no se reasignaron outliers ni se volvió a ejecutar el NLP.

Se leyeron completos 488 casos temáticos: AR 164, MX 163 y PE 161; hasta cuatro textos únicos por tópico y país, con hash y semilla fija. Cuatro de los 492 cupos posibles no tenían suficientes textos distintos. La muestra contiene 68.284 caracteres. También se revisaron 54 casos de sentimiento.

Cada caso se calificó respecto de la etiqueta original del tópico: C = soporte explícito, P = parcial, adyacente o genérico, N = sin soporte o con interferencia. Un tópico se habilita para indicadores con C/n ≥ 2/3 en total, ≥ 1/2 en cada país y sin interferencia contextual grave.

Estos cocientes describen la muestra, que está equilibrada por tópico y país; no son una estimación de exactitud sobre todo el corpus.

## Hallazgos principales

- T016 y T024, originalmente titulados como Perú, agrupan también historia y patrimonio argentinos. Se retiró la atribución exclusiva y se restringió su uso temático.
- T025 mezcla Cusco con Cuyo, Culhuacán, CU y Cuale; no sustenta un KPI específico de Cusco o boleto turístico.
- T027 contiene la mina La Mejicana de Argentina, deportes y empresas; no equivale a Revolución mexicana.
- T028 mezcla Lima con Limay y sopa de lima. El país o la ciudad se obtienen de la geografía, no del tópico.
- T021 incluye patrimonio y localidades diversas, no solamente huacas. T033 mezcla fauna patagónica, entorno natural y cultura de la ayahuasca.
- Las menciones de museos pequeños no implican insatisfacción; mágico puede ser elogio, y plantas puede significar pisos. Estas restricciones están explícitas en SQL.

## Catálogo revisado

| Código | Etiqueta activa | C / n respecto al título original | Uso |
|---|---|---:|---|
| 000 | Colecciones y contenidos de la visita museal | 7/12 | Restringido |
| 001 | Café, cafeterías y cultura cafetera | 11/12 | Apto |
| 002 | Condiciones de ingreso, entradas y acceso | 9/12 | Apto |
| 003 | Memoria histórica y conocimiento del pasado | 12/12 | Apto |
| 004 | Gastronomía y servicio de alimentos | 10/12 | Apto |
| 005 | Atención del personal y acompañamiento de la visita | 7/12 | Restringido |
| 006 | Horarios, cierres y disponibilidad de visita | 10/12 | Apto |
| 007 | Arquitectura, edificios y casas patrimoniales | 11/12 | Apto |
| 008 | Entorno, vistas y atractivo general del lugar | 4/12 | Restringido |
| 009 | Fauna, paleontología y cuidado de animales | 10/12 | Apto |
| 010 | Museos pequeños y extensión del recorrido | 10/12 | Apto |
| 011 | Exposiciones y programación cultural | 5/12 | Restringido |
| 012 | Identidad cultural e historia local | 2/12 | Restringido |
| 013 | Aprendizaje y actividades para niños | 12/12 | Apto |
| 014 | Patrimonio inca y arquitectura prehispánica | 6/12 | Restringido |
| 015 | Arte, obras y expresiones artísticas | 11/12 | Apto |
| 016 | Historia e identidad nacional | 3/12 | Restringido |
| 017 | Precios, entradas y medios de pago | 11/12 | Apto |
| 018 | Limitaciones del recorrido y oportunidades de mejora | 6/12 | Restringido |
| 019 | Experiencia de visita y mediación de guías | 4/12 | Restringido |
| 020 | Patrimonio religioso, iglesias y conventos | 10/12 | Apto |
| 021 | Patrimonio local y referencias territoriales | 2/12 | Restringido |
| 022 | Visitas con familia, amigos o pareja | 12/12 | Apto |
| 023 | Automóviles de colección e historia del motor | 12/12 | Apto |
| 024 | Patrimonio cultural e historia regional | 3/11 | Restringido |
| 025 | Historia regional y circuitos de visita | 4/12 | Restringido |
| 026 | Casas-museo y memoria de personajes | 9/12 | Apto |
| 027 | Historia y referencias a México y La Mejicana | 0/12 | Restringido |
| 028 | Referencias a Lima y patrimonio urbano | 2/12 | Restringido |
| 029 | Mineralogía, minería y patrimonio industrial | 11/12 | Apto |
| 030 | Arqueología, ruinas y patrimonio material antiguo | 9/12 | Apto |
| 031 | Estado del lugar, mantenimiento y seguridad | 6/12 | Restringido |
| 032 | Patrimonio e historia cultural de México y otros contextos | 4/9 | Restringido |
| 033 | Naturaleza, fauna y culturas amazónicas | 6/12 | Restringido |
| 034 | Ambiente tranquilo y espacios de descanso | 7/12 | Restringido |
| 035 | Encanto del lugar, leyendas y misticismo | 4/12 | Restringido |
| 036 | Chocolate, cacao y degustación | 12/12 | Apto |
| 037 | Jardines, plantas y espacios botánicos | 10/12 | Apto |
| 038 | Música, instrumentos y conciertos | 12/12 | Apto |
| 039 | Recorridos y recomendación general de visita | 12/12 | Apto |
| 040 | Mariposarios, abejas y divulgación de invertebrados | 9/12 | Apto |

## Cobertura por país

| País | Reseñas totales | Con texto | Asignadas baseline | En temas aptos | En temas restringidos |
|---|---:|---:|---:|---:|---:|
| AR | 461,594 | 292,344 | 107,277 | 56,990 | 50,287 |
| MX | 560,328 | 270,051 | 102,508 | 55,068 | 47,440 |
| PE | 121,955 | 60,943 | 23,771 | 10,024 | 13,747 |

122.082 reseñas pertenecen a los 22 tópicos aptos y 111.474 a los 19 restringidos (233.556 en total). La revisión evaluó categorías mediante muestras, no cada una de esas reseñas; la vista revisada filtra los tópicos aptos y conserva los denominadores.

## Diagnóstico de sentimiento

De 54 casos revisados: 27 compatibles con la polaridad asignada, 7 mixtos o ambiguos, 1 contradicción clara, 12 abstenciones razonables por señal insuficiente y 7 con señal interpretable que quedaron sin clasificar. Es un diagnóstico del modelo, no una medida de su precisión.

Ejemplo de contradicción: «Una visita obligada en Huamantla.» estaba clasificada como NEGATIVO. También hay textos en español excluidos por la detección de idioma. Estos casos quedan registrados por ID y hash en la capa curada; las predicciones originales se conservan sin correcciones selectivas.

## Cambios aplicados y reproducibilidad

- Origen: esquema `curado` con 41 filas en `catalogo_topicos`, 488 en `evaluacion_topico`, 54 en `evaluacion_sentimiento` y vista `v_catalogo_vigente`. `stg.catalogo`, las dos tablas madre, el puente raw y todos los CSV permanecen intactos.
- Destino: 41 etiquetas/definiciones revisadas en `mart.dim_dimension_latente`, columnas de gobernanza y miembro desconocido explicado. Etiquetas legibles en perfil, extensión, antigüedad, presencia, sentimiento, rating e idioma; no cambian claves o segmentos.
- `aud.revision_semantica` conserva versión, hashes, revisor, `validacion_humana=0` y respaldo de las dimensiones previas.
- ETL adaptado: aplica y verifica la revisión después de DIM y antes de hechos; nueva instalación y reanudación conservan los cambios. La migración se ensayó con rollback comprobado, luego se aplicó y se ejecutó de nuevo: cero nuevas filas y cero actualizaciones en la segunda aplicación.
- Se ejecutó el comando completo adaptado y pasó sus dos pasadas en 336.3 s, con lectura completa de vuelta CSV↔SQL y todas las validaciones relacionales. Delta cero en las 14 tablas de dimensiones/hechos.

Las consultas vigentes son `mart.v_catalogo_topicos`, `mart.v_dimension_satisfaccion` (baseline con banderas), `mart.v_dimension_satisfaccion_revisada` (solo temas habilitados) y `mart.v_cobertura_tematica`. `VER_REVISION.sql` permite inspeccionar los dictámenes y los textos exactos mediante join con origen.

Los nombres de idioma se contrastaron con la [tabla de códigos ISO de Library of Congress](https://www.loc.gov/standards/iso639-2/php/code_list.php).

## Definiciones y límites por tópico

### 000 — Colecciones y contenidos de la visita museal

Opiniones sobre el contenido de las colecciones, su organización, su interés educativo y la presentación del museo. Incluye: Objetos exhibidos, curaduría, materiales interpretativos y aprendizaje durante el recorrido. Exclusiones: No implica que toda reseña describa interacción tecnológica ni una exposición concreta.

**Límite observado:** La etiqueta anterior sobreestimaba el componente interactivo; aparecen recomendaciones generales y comentarios de limpieza o arquitectura.

### 001 — Café, cafeterías y cultura cafetera

Experiencias vinculadas al café como bebida, producto cultural, proceso de elaboración o servicio de cafetería durante la visita. Incluye: Degustaciones de café, capuchino, molienda, tostado, compra de granos y atención de cafeterías. Exclusiones: Distinguir del cacao y chocolate cuando no se menciona café, y de la gastronomía sin relación cafetera.

**Límite observado:** Se observó una reseña de cacao sin café; la asignación temática no garantiza pertinencia individual.

### 002 — Condiciones de ingreso, entradas y acceso

Comentarios sobre las condiciones prácticas para ingresar y recorrer el establecimiento, incluida la entrada gratuita o pagada. Incluye: Taquilla, disponibilidad de ingreso, costo de entrada, restricciones de bolsas o fotografías y facilidades de acceso. Exclusiones: No interpretar todo el grupo como queja de precios ni como medición de accesibilidad universal.

**Límite observado:** Se solapa con horarios y precios; algunas reseñas evalúan solamente la exposición y no el acceso.

### 003 — Memoria histórica y conocimiento del pasado

Relatos sobre el aprendizaje de la historia, la evocación de recuerdos y la reflexión sobre el pasado a partir de la visita. Incluye: Historia local o nacional, acontecimientos, recuerdos personales y relatos históricos. Exclusiones: No atribuye un acontecimiento, país o período único a todo el grupo.

**Límite observado:** Tema amplio que comparte contenido con patrimonio nacional, regional y casas de personajes.

### 004 — Gastronomía y servicio de alimentos

Valoraciones de comida, postres, bebidas y atención de restaurantes o bares asociados a los lugares visitados. Incluye: Calidad y variedad de platos, desayunos, cenas, servicio de mesa y tiempos de atención. Exclusiones: No equiparar calidad gastronómica con la calidad de las colecciones del museo.

**Límite observado:** Existen comentarios de productos alimenticios sin experiencia museal y una valoración genérica sin referencia gastronómica.

### 005 — Atención del personal y acompañamiento de la visita

Comentarios sobre el trato recibido, la disposición del personal, la organización y las explicaciones durante la visita. Incluye: Amabilidad, ayuda, claridad explicativa, organización de filas y acompañamiento. Exclusiones: Una valoración positiva genérica no demuestra que hubo buena atención.

**Límite observado:** Parte de la muestra solo recomienda el lugar o describe su entorno, sin evaluar al personal.

### 006 — Horarios, cierres y disponibilidad de visita

Experiencias de apertura, cierre, reservas y disponibilidad efectiva de servicios de visita frente a la información anunciada. Incluye: Horarios incumplidos, remodelación, reservas, información web y ausencia de guías. Exclusiones: Distinguir quejas de atención sin relación con disponibilidad u horario.

**Límite observado:** La información es una experiencia histórica de la reseña, no el horario vigente del establecimiento.

### 007 — Arquitectura, edificios y casas patrimoniales

Apreciaciones del inmueble, su diseño arquitectónico, conservación material y valor de las casas o construcciones visitadas. Incluye: Decoración, viviendas históricas, templos, diseño, restauración y técnicas constructivas. Exclusiones: La mención de una casa cercana o del domicilio del autor no acredita interés arquitectónico.

**Límite observado:** Se observó una reseña que solo dice pasar por el lugar de camino a casa.

### 008 — Entorno, vistas y atractivo general del lugar

Agrupación de opiniones sobre el entorno visual, el paisaje, las vistas y el atractivo general de un lugar. Incluye: Vistas urbanas o naturales, fotografías, paisaje y apreciaciones del entorno. Exclusiones: No tratar toda recomendación general o mención de un evento como valoración del paisaje.

**Límite observado:** La muestra mezcla vistas explícitas con elogios genéricos y actividades culturales; uso temático restringido.

### 009 — Fauna, paleontología y cuidado de animales

Agrupación de experiencias de observación y aprendizaje sobre animales vivos, rescate de fauna y exhibiciones paleontológicas. Incluye: Bienestar animal, especies, tortugas, monos, dinosaurios, mamuts y colecciones relacionadas. Exclusiones: La presencia incidental de ganado en un acceso no describe una exhibición de fauna.

**Límite observado:** Conviven animales vivos y fósiles; no usar el total como indicador exclusivo de bienestar animal.

### 010 — Museos pequeños y extensión del recorrido

Opiniones sobre el tamaño del museo, la cantidad de salas o piezas y la duración percibida del recorrido. Incluye: Recorridos cortos, salas pequeñas, amplitud limitada y evaluación de una colección reducida. Exclusiones: Pequeño no significa malo; la ausencia de concurrencia no prueba tamaño reducido.

**Límite observado:** Incluye algunas opiniones generales sobre exposiciones o ubicación sin referencia al tamaño.

### 011 — Exposiciones y programación cultural

Experiencias de muestras, exposiciones, talleres, espectáculos y actividades culturales ofrecidas por el lugar. Incluye: Exhibiciones permanentes o temporales, eventos, talleres, presentaciones y programación. Exclusiones: No suponer temporalidad o renovación periódica si la reseña no lo indica.

**Límite observado:** La etiqueta original era demasiado específica al afirmar exposiciones temporales; muchas reseñas solo mencionan una exposición.

### 012 — Identidad cultural e historia local

Agrupación de referencias a cultura, tradiciones, historia local y valoración del patrimonio de una comunidad. Incluye: Identidad regional, cultura local, raíces e historia de la comunidad. Exclusiones: No inferir origen ancestral o prehispánico de una referencia cultural genérica.

**Límite observado:** Se observó lenguaje cultural amplio y poca evidencia explícita de ancestros en varios países; solapamiento con otros temas históricos.

### 013 — Aprendizaje y actividades para niños

Opiniones sobre la adecuación de la visita para niños y adolescentes, su entretenimiento y sus oportunidades de aprendizaje. Incluye: Actividades infantiles, juegos, interactividad y recomendaciones o críticas para visitantes con niños. Exclusiones: No inferir edad de los autores ni que toda actividad interactiva sea adecuada para niños.

**Límite observado:** Contiene opiniones favorables y desfavorables sobre la experiencia infantil; el tópico no fija el sentimiento.

### 014 — Patrimonio inca y arquitectura prehispánica

Agrupación de referencias a patrimonio inca, templos, ruinas y otras construcciones o culturas prehispánicas. Incluye: Patrimonio inca, arquitectura antigua, estructuras ceremoniales y explicaciones de culturas prehispánicas. Exclusiones: No clasificar automáticamente como inca una referencia zapoteca, colonial o de otro origen.

**Límite observado:** En México aparecen patrimonio zapoteca, edificios coloniales y una exposición revolucionaria; el grupo no es homogéneo entre países.

### 015 — Arte, obras y expresiones artísticas

Experiencias de apreciación de obras y expresiones artísticas, con presencia de pintura, murales, esculturas, cerámica y artesanías. Incluye: Exhibición de artistas, obras plásticas, creación artesanal y valoración estética. Exclusiones: No deducir una disciplina única ni confundir cualquier evento del lugar con arte plástico.

**Límite observado:** También aparece una obra musical; la etiqueta abarca arte sin declarar exclusividad de las artes visuales.

### 016 — Historia e identidad nacional

Agrupación contextual de reseñas sobre historia y cultura nacional, con vocabulario inicialmente asociado al Perú. Incluye: Menciones explícitas de historia nacional e identidad cultural del país referido en la reseña. Exclusiones: No atribuir todas las reseñas al Perú ni inferir nacionalidad del autor.

**Límite observado:** Las reseñas argentinas hablan de Argentina; en México aparecen saludos desde Perú y contenidos sin historia peruana. No apto como indicador temático comparable.

### 017 — Precios, entradas y medios de pago

Experiencias sobre el costo de la visita y sus servicios, la relación precio-valor y los medios de pago disponibles. Incluye: Entradas, propinas, descuentos, gratuidad, cobros por fotografías y uso de efectivo o tarjetas. Exclusiones: Los importes corresponden al momento y moneda de cada reseña; no son tarifas actuales comparables directamente.

**Límite observado:** Comparte reseñas con acceso y taquilla; no sumar ambos grupos como dimensiones mutuamente excluyentes de la experiencia.

### 018 — Limitaciones del recorrido y oportunidades de mejora

Agrupación de comentarios sobre recursos, espacio, información, mantenimiento y expectativas no satisfechas durante la visita. Incluye: Falta de material o explicaciones, abandono, escasez de instalaciones y críticas sobre el recorrido. Exclusiones: No interpretar una referencia a tamaño pequeño como insatisfacción si la reseña es favorable.

**Límite observado:** Varias reseñas de museos pequeños son positivas; no usar el tópico como sustituto de sentimiento negativo.

### 019 — Experiencia de visita y mediación de guías

Agrupación de valoraciones globales de la experiencia, algunas relacionadas con explicaciones, atención y mediación de guías. Incluye: Experiencias recomendadas, aprendizaje durante el recorrido y comentarios de guías. Exclusiones: No asumir visita guiada cuando solo se menciona una experiencia agradable.

**Límite observado:** La mayoría de varios estratos es genérica y no confirma guiado; la etiqueta anterior sobreestimaba ese componente.

### 020 — Patrimonio religioso, iglesias y conventos

Experiencias de visita y apreciación de templos, conventos, reliquias, arte religioso y espacios patrimoniales vinculados. Incluye: Edificios religiosos, pintura eclesiástica, teología y colecciones relacionadas. Exclusiones: No inferir religión del autor ni práctica devocional a partir de una visita cultural.

**Límite observado:** Algunas reseñas describen plazas o áreas verdes cercanas; no todas evalúan el patrimonio religioso directamente.

### 021 — Patrimonio local y referencias territoriales

Agrupación contextual que combina huacas y culturas prehispánicas con referencias a localidades y patrimonio histórico diverso. Incluye: Solo interpretar de forma específica una reseña que mencione explícitamente la cultura o el bien patrimonial. Exclusiones: No extender la categoría huaca o prehispánica a todo el grupo por semejanza de topónimos.

**Límite observado:** Aparecen Chascomús, Chaco, Miramar, Chapala, Chapultepec y marionetas de Cajamarca. No hay un tema prehispánico común verificable entre países.

### 022 — Visitas con familia, amigos o pareja

Opiniones sobre compartir la visita con familia, amigos o pareja y la adecuación del lugar para actividades en compañía. Incluye: Recomendaciones familiares, tiempo compartido y actividades grupales. Exclusiones: No inferir parentescos, composición del hogar o edad del autor más allá del contenido textual.

**Límite observado:** La visita acompañada puede coexistir con cualquier otro aspecto temático y no determina satisfacción.

### 023 — Automóviles de colección e historia del motor

Experiencias en colecciones de automóviles y exhibiciones sobre motores, automovilismo y vehículos históricos. Incluye: Autos clásicos, conservación de vehículos, historia del automóvil y valoración de las colecciones. Exclusiones: No atribuir restauración técnica a todo vehículo bien presentado si no se documenta.

**Límite observado:** El estado de conservación expresado por visitantes es una percepción, no una inspección mecánica.

### 024 — Patrimonio cultural e historia regional

Agrupación contextual de cultura, historia, arte y patrimonio regional, originalmente etiquetada como patrimonio peruano. Incluye: Contenido cultural regional explícito descrito por la reseña. Exclusiones: No tratar todo el grupo como arte peruano ni como evidencia exclusiva de un país.

**Límite observado:** La muestra argentina contiene museos patagónicos y paleontología; la mexicana incluye gastronomía y memoria local. Se solapa con historia e identidad nacional.

### 025 — Historia regional y circuitos de visita

Agrupación contextual de museos regionales, edificios históricos y recorridos, con fuerte referencia original al Cusco. Incluye: Historia regional y condiciones de visita solo cuando se mencionan explícitamente. Exclusiones: No identificar automáticamente Cusco o boleto turístico en las reseñas de otros lugares.

**Límite observado:** Se observaron Cuyo, Tucumán, Rosario, Culhuacán, CU y Cuale. La agrupación mezcla referencias territoriales; no apta para comparar una experiencia específica.

### 026 — Casas-museo y memoria de personajes

Experiencias relacionadas con residencias históricas, vida y obra de personajes, homenajes y memoria biográfica. Incluye: Casas de escritores o figuras históricas, biografías, legados y homenajes artísticos. Exclusiones: Un nombre de guía o trabajador no convierte una reseña en contenido biográfico.

**Límite observado:** Se observaron nombres propios de guías como José o Ricardo sin relación con personajes históricos; revisar ejemplos individuales antes de citarlos.

### 027 — Historia y referencias a México y La Mejicana

Agrupación contextual de referencias mexicanas y otras menciones de semejanza léxica, incluida la mina La Mejicana en Argentina. Incluye: Solo tomar como contenido histórico mexicano o político los textos que lo expresen de forma directa. Exclusiones: No equiparar la mina La Mejicana con la Revolución mexicana ni atribuir política a deportes, empresas o bancos.

**Límite observado:** La muestra no sostiene el título político original; hay homonimia y mezcla de historia industrial, cultural y referencias generales. No apta para KPI temáticos.

### 028 — Referencias a Lima y patrimonio urbano

Agrupación contextual de referencias a Lima y otros contenidos urbanos o territoriales de semejanza léxica. Incluye: Interpretación territorial únicamente cuando el texto identifica claramente la ciudad o cultura referida. Exclusiones: No confundir Lima con Limay ni con sopa de lima; no asumir Centro Histórico de Lima para todos los registros.

**Límite observado:** En Argentina aparecen Limay y patrimonio de otras ciudades; en México una reseña de sopa de lima. La categoría original no es geográficamente válida para todo el grupo.

### 029 — Mineralogía, minería y patrimonio industrial

Experiencias sobre colecciones de minerales y rocas, minas, túneles y aprendizaje de la historia de la actividad minera. Incluye: Exhibición mineralógica, patrimonio minero, trabajo de mineros y recorridos por minas. Exclusiones: Una visita genérica a cuevas no acredita necesariamente minería o mineralogía.

**Límite observado:** Puede coexistir arqueología o fósiles en las mismas colecciones; no reducir todas las reseñas a condiciones laborales mineras.

### 030 — Arqueología, ruinas y patrimonio material antiguo

Experiencias de visita y aprendizaje en sitios arqueológicos, ruinas, monumentos y colecciones de culturas antiguas. Incluye: Yacimientos, pirámides, tumbas, monolitos, estructuras antiguas y piezas arqueológicas. Exclusiones: Distinguir formaciones naturales, fósiles y monumentos modernos cuando no se relacionan con arqueología.

**Límite observado:** En Argentina aparecen colecciones paleontológicas mixtas; hay referencias aisladas a una mina y una roca natural.

### 031 — Estado del lugar, mantenimiento y seguridad

Agrupación de opiniones sobre conservación, mantenimiento, limpieza, seguridad y condiciones generales de uso del lugar. Incluye: Deterioro, riesgo, necesidades de mantenimiento, cuidado de instalaciones y dificultades para recorrer. Exclusiones: No inferir inseguridad de un comentario genérico de poco interés o falta de promoción.

**Límite observado:** La muestra mezcla estado material con atractivo turístico y concurrencia; no es una medida homogénea de seguridad.

### 032 — Patrimonio e historia cultural de México y otros contextos

Agrupación contextual de patrimonio, objetos históricos y referencias culturales, originalmente asociada a México. Incluye: Contenido histórico o cultural mexicano cuando está expresamente presente. Exclusiones: No identificar todas las reseñas como mexicanas a partir del tópico; usar el país del lugar para análisis geográfico.

**Límite observado:** Las reseñas argentinas describen costumbres gauchas, colonos y ciudades argentinas. La muestra peruana sí menciona México, pero no valida la etiqueta en otros países.

### 033 — Naturaleza, fauna y culturas amazónicas

Agrupación que combina turismo natural, observación o interpretación de fauna y referencias culturales amazónicas, incluida la ayahuasca. Incluye: Paisajes naturales, ballenas, ambientes amazónicos y experiencias culturales expresamente vinculadas. Exclusiones: No equiparar todo el grupo con avistamiento de animales; una metáfora como elefante blanco no describe fauna.

**Límite observado:** Los estratos de Argentina, México y Perú representan subtemas distintos. No apta como indicador exclusivo de conservación o avistamiento.

### 034 — Ambiente tranquilo y espacios de descanso

Opiniones sobre tranquilidad, comodidad, descanso y disfrute de espacios abiertos o acogedores durante la visita. Incluye: Relajación, áreas verdes, lectura, pausa y ambiente tranquilo. Exclusiones: Una recomendación general de pasar la tarde no demuestra presencia de jardín o tranquilidad.

**Límite observado:** Algunas reseñas son genéricas o describen servicios de camping; evitar inferencias sobre infraestructura no mencionada.

### 035 — Encanto del lugar, leyendas y misticismo

Agrupación de expresiones de encanto o magia junto con referencias a leyendas, mitos y experiencias místicas. Incluye: Relatos legendarios, misticismo y valoraciones metafóricas de un lugar como mágico. Exclusiones: No interpretar toda palabra mágico como creencia espiritual o tradición religiosa.

**Límite observado:** Gran parte de Argentina y México usa magia como elogio o referencia artística; la interpretación mística predomina solo en algunos textos peruanos.

### 036 — Chocolate, cacao y degustación

Experiencias de aprendizaje, elaboración, consumo y apreciación artística del cacao y el chocolate. Incluye: Museos y talleres de cacao, procesos, degustaciones, tiendas y obras en chocolate. Exclusiones: Distinguir del café y de gastronomía sin referencia a cacao o chocolate.

**Límite observado:** Las expectativas pueden ser positivas o negativas; el tópico no acredita que exista demostración de fábrica en cada visita.

### 037 — Jardines, plantas y espacios botánicos

Experiencias de apreciación de jardines, vegetación, flores y exhibiciones botánicas en los lugares visitados. Incluye: Especies vegetales, orquídeas, jardines, árboles y conservación de vegetación. Exclusiones: No interpretar plantas como pisos de un edificio ni cultivarse como evidencia botánica.

**Límite observado:** Se detectó una referencia a tres plantas de un edificio y una expresión figurada; controlar esa polisemia.

### 038 — Música, instrumentos y conciertos

Experiencias de patrimonio musical, instrumentos, artistas, conciertos, coros y otras actividades de interpretación musical. Incluye: Música criolla, instrumentos andinos, orquestas, recitales y condiciones de escucha. Exclusiones: No confundir la mera realización de un evento con un concierto si no hay contenido musical explícito.

**Límite observado:** Incluye tanto colecciones permanentes como presentaciones y música ambiental; no son equivalentes en operación.

### 039 — Recorridos y recomendación general de visita

Valoraciones globales de recorridos y recomendaciones de visitar el lugar, con o sin referencia explícita a un guía. Incluye: Utilidad del recorrido, interés de la visita, recomendaciones y agradecimientos por el tour. Exclusiones: No inferir un atributo específico como precio, accesibilidad o conservación solo por una recomendación global.

**Límite observado:** Grupo amplio y predominantemente valorativo; se solapa con experiencia general y atención de guías.

### 040 — Mariposarios, abejas y divulgación de invertebrados

Experiencias de observación y aprendizaje en mariposarios, espacios de abejas y otras exhibiciones de invertebrados. Incluye: Ciclo de mariposas, abejas nativas, laboratorios, arañas y explicaciones de especies. Exclusiones: No interpretar toda queja de mosquitos como referencia a una exhibición o programa de conservación.

**Límite observado:** Hay comentarios de mosquitos incidentales y cierre del lugar; la etiqueta no acredita actividades de conservación en todos los casos.

## Estado final

La revisión semántica quedó registrada y aplicada. Los 19 tópicos restringidos siguen identificados en el catálogo y quedan fuera de los indicadores temáticos; los valores desconocidos, las reseñas sin texto y la fecha de reputación no documentada se conservan. La capa BI y el dashboard consumen la revisión mediante la bandera `apto_analisis_tematico`.
