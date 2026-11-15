"""Títulos provisionales de IA basados en términos y ejemplos reales leídos.
No altera asignaciones, pesos ni NMF; no equivale a validación humana independiente.
"""
import json
from experiment import FINAL,read_csv,save_csv,atomic_json,utcnow

LABELS={
 'lda-4e844cf06060':[
 'Historia general y contenido del recorrido','Experiencia, atención y servicios','Aprendizaje cultural y visita familiar',
 'Espacios expositivos y fotografías','Tiempo libre, ambiente y disponibilidad','Casas históricas, arte y colecciones',
 'Personal, mantenimiento y carencias','Precios y visitas guiadas','Valoración del patrimonio y recomendación','Patrimonio inca y sitios arqueológicos'],
 's-bert-8bcb6303e2dc':[
 'Contenido de exposiciones y recorrido interactivo','Café y experiencia de cafetería','Gestión del acceso y taquilla',
 'Memoria histórica y relatos del pasado','Gastronomía regional y restaurantes','Atención amable y dinámicas de visita',
 'Horarios, cierres e información de acceso','Arquitectura y casas patrimoniales','Paisajes, vistas y entorno',
 'Fauna, conservación y trato a los animales','Museos pequeños y amplitud del recorrido','Exposiciones temporales y programación cultural',
 'Raíces culturales y patrimonio ancestral','Aprendizaje y actividades para niños','Patrimonio inca y arquitectura de templos',
 'Arte, pinturas, murales y esculturas','Historia y culturas del Perú','Precios y medios de pago',
 'Carencias de organización y servicio','Experiencia de visitas guiadas','Patrimonio religioso y conventos',
 'Huacas y culturas prehispánicas','Visitas con familia y amigos','Automóviles clásicos y restauración',
 'Arte y patrimonio cultural peruano','Historia regional del Cusco y boleto turístico','Casas-museo y personajes históricos',
 'Historia política y revolución mexicana','Patrimonio del Centro Histórico de Lima','Mineralogía, minería y patrimonio industrial',
 'Sitios arqueológicos y ruinas','Mantenimiento, limpieza y seguridad','Patrimonio mexicano y relatos históricos',
 'Turismo natural y avistamiento de fauna','Áreas verdes, tranquilidad y relajación','Misticismo y tradiciones locales',
 'Chocolate, cacao y degustación','Jardines botánicos y plantas','Patrimonio musical y conciertos',
 'Recorridos y valoración general de la visita','Mariposarios, abejas y conservación de insectos']}

def apply(method):
    folder=FINAL/method; path=folder/'validacion_final.json'
    if not path.exists(): raise ValueError('No hay export final para etiquetar '+method)
    report=json.loads(path.read_text(encoding='utf8')); version=report['modelo_topicos']['version']
    if version not in LABELS:
        print('Sin propuesta semántica revisada para versión '+version); return
    rows=[r for _,r in read_csv(folder/'catalogo_dimensiones_latentes.csv')]
    if len(rows)!=len(LABELS[version]): raise ValueError('Catálogo no corresponde a títulos propuestos')
    for row in rows:
        index=int(row['codigo_topico'].rsplit('T',1)[1]); row['etiqueta']=LABELS[version][index]
        row['descripcion']='Propuesta de IA tras lectura de términos y ejemplos de entrenamiento; validar con muestra aleatoria externa. Puede contener subtemas o contexto geográfico.'
        row['validacion_etiqueta']='PROPUESTA_IA_REVISAR_EQUIPO'
    output=save_csv(folder,'catalogo_dimensiones_latentes.csv',list(rows[0]),rows)
    report['outputs']=[output if o['file']==output['file'] else o for o in report['outputs']]
    report['modelo_topicos']['catalog']=rows
    report['etiquetado']=dict(fecha=utcnow(),tipo='PROPUESTA_IA',evidencia='LDA: términos y muestra aleatoria; S-BERT: términos y ejemplos centrales de entrenamiento.',decision_equipo='PENDIENTE',limitacion='No validación humana independiente; revisar grupos redundantes/geográficos y contaminación de ejemplos.')
    atomic_json(path,report)
    from validate import validate
    validate(folder)
    print('Títulos de negocio propuestos: '+method,flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('method',choices=['LDA','S-BERT']); apply(parser.parse_args().method)
