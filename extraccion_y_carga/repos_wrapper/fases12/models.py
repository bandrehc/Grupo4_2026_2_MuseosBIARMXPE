"""Modelos locales con revisiones fijas, descarga reanudable y sin código remoto."""
import json
import time
import urllib.request
from pathlib import Path

from common import REPO,atomic_json,digest,normalized_text

MODEL_SPECS={
 'distilbert':dict(repo='Xenova/distilbert-base-multilingual-cased-sentiments-student',
   revision='9d9ac661fd7b0b48535a1fc99b20ae6947629e65',
   languages=['ar','de','en','fr','hi','it','ja','ms','pt','ru','es','zh']),
 'reviews_bert':dict(repo='Xenova/bert-base-multilingual-uncased-sentiment',
   revision='fad9b372f770c208d2efaf00d02f2cb3b61ec450',
   languages=['en','nl','de','fr','es','it']),
 'xlm_t':dict(repo='onnx-community/twitter-xlm-roberta-base-sentiment-ONNX',
   revision='3112e85dea04f0019bf01282916588e3c9dd9bc8',
   languages=['ar','en','fr','de','hi','it','es','pt']),
}
CACHE=REPO/'.runtime_fases12/models'


def download_file(url,destination,progress=None):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.is_file(): return
    partial=destination.with_suffix(destination.suffix+'.part')
    for attempt in range(4):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            headers={'User-Agent':'MuseosLATAM-local-preparation/1.0'}
            if offset: headers['Range']=f'bytes={offset}-'
            request=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(request,timeout=90) as response:
                append=response.status==206 and offset>0
                if not append: offset=0
                length=int(response.headers.get('Content-Length','0'))+offset
                written=offset
                with partial.open('ab' if append else 'wb') as f:
                    while True:
                        block=response.read(1024*1024)
                        if not block: break
                        f.write(block); written+=len(block)
                        if progress and written%(5*1024*1024)<1024*1024:
                            f.flush()
                            progress.update('descargar_modelo',written,length,
                                            f'{destination.name}: {written/1024**2:.1f} MB',unidad='bytes')
            if length and written!=length: raise IOError('Descarga incompleta')
            partial.replace(destination)
            return
        except Exception:
            if attempt==3: raise
            time.sleep(min(2**attempt,8))


def ensure_model(name,progress=None):
    spec=MODEL_SPECS[name]
    folder=CACHE/name/spec['revision']
    for filename in ('config.json','tokenizer.json','onnx/model_quantized.onnx'):
        download_file(f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{filename}",folder/filename,progress)
    manifest_path=folder/'manifest.json'
    hashes={filename:digest(folder/filename) for filename in ('config.json','tokenizer.json','onnx/model_quantized.onnx')}
    if manifest_path.exists():
        old=json.loads(manifest_path.read_text(encoding='utf-8'))
        if old['sha256']!=hashes: raise ValueError(f'Modelo local modificado: {name}')
    manifest=dict(name=name,**spec,sha256=hashes,backend='onnxruntime_cpu_int8')
    atomic_json(manifest_path,manifest)
    return folder,manifest


class LanguageDetector:
    def __init__(self):
        try:
            from lingua import LanguageDetectorBuilder
            self.detector=LanguageDetectorBuilder.from_all_languages().build()
            self.engine='lingua'
        except (ImportError,MemoryError):
            from langdetect import DetectorFactory
            DetectorFactory.seed=20261011
            self.engine='langdetect'

    def detect(self,text):
        if sum(c.isalpha() for c in text)<3: return 'xx',0.,self.engine
        if self.engine=='lingua':
            scores=self.detector.compute_language_confidence_values(text)
            if not scores: return 'xx',0.,self.engine
            best=scores[0]
            confidence=float(best.value)
            margin=confidence-(float(scores[1].value) if len(scores)>1 else 0.)
            code=best.language.iso_code_639_1.name.lower()
            # No es probabilidad calibrada. Palabras compartidas pueden quedar desconocidas.
            return (code if confidence>=.60 and margin>=.08 else 'xx'),confidence,self.engine
        from langdetect import detect_langs,LangDetectException
        try:
            best=detect_langs(text)[0]
            return (best.lang if best.prob>=.85 else 'xx'),float(best.prob),self.engine
        except LangDetectException: return 'xx',0.,self.engine


class OnnxSentiment:
    def __init__(self,name,threads=6,batch_size=32,max_tokens=256,progress=None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np=np
        folder,self.manifest=ensure_model(name,progress)
        self.name=name
        self.version=name+':'+self.manifest['revision']+':int8'
        self.supported=set(self.manifest['languages'])
        self.tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        config=json.loads((folder/'config.json').read_text(encoding='utf-8'))
        self.labels={int(k):v.lower() for k,v in config['id2label'].items()}
        options=ort.SessionOptions()
        options.intra_op_num_threads=threads
        options.inter_op_num_threads=1
        options.log_severity_level=3
        self.session=ort.InferenceSession(str(folder/'onnx/model_quantized.onnx'),sess_options=options,
                                         providers=['CPUExecutionProvider'])
        self.inputs=[x.name for x in self.session.get_inputs()]
        self.batch_size=batch_size; self.max_tokens=max_tokens
        self.cls=config.get('bos_token_id',self.tokenizer.token_to_id('[CLS]'))
        self.sep=config.get('eos_token_id',self.tokenizer.token_to_id('[SEP]'))
        self.pad=config.get('pad_token_id',self.tokenizer.token_to_id('[PAD]') or 0)
        if self.cls is None or self.sep is None: raise ValueError('Tokenizador sin tokens de inicio/final compatibles')

    def _probabilities(self,logits):
        np=self.np
        scores=np.exp(logits-np.max(logits,axis=1,keepdims=True))
        scores/=scores.sum(axis=1,keepdims=True)
        if self.name=='reviews_bert':
            # Las estrellas son PREDICHAS desde texto, no se usa rating observado.
            return np.column_stack((scores[:,0]+scores[:,1],scores[:,2],scores[:,3]+scores[:,4]))
        indices={label:index for index,label in self.labels.items()}
        return np.column_stack([scores[:,indices[x]] for x in ('negative','neutral','positive')])

    def predict(self,texts):
        np=self.np
        # Ventanas sin pérdida de tokens; no truncar una reseña larga a los primeros 256.
        chunks=[]; token_counts=[]; chunk_counts=[]
        for i,text in enumerate(texts):
            ids=self.tokenizer.encode(normalized_text(text),add_special_tokens=False).ids
            token_counts.append(len(ids)); count=0
            for start in range(0,len(ids),self.max_tokens-2):
                body=ids[start:start+self.max_tokens-2]
                chunks.append((i,[self.cls]+body+[self.sep],len(body))); count+=1
            chunk_counts.append(count)
        weighted=np.zeros((len(texts),3),dtype=np.float64)
        weights=np.zeros(len(texts),dtype=np.float64)
        chunks.sort(key=lambda x:len(x[1]))
        start=0; batch_size=self.batch_size
        while start<len(chunks):
            batch=chunks[start:start+batch_size]
            size=max(len(x[1]) for x in batch)
            ids=np.full((len(batch),size),self.pad,dtype=np.int64)
            mask=np.zeros_like(ids)
            for j,(_,tokens,_) in enumerate(batch): ids[j,:len(tokens)]=tokens; mask[j,:len(tokens)]=1
            inputs={'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)}
            try:
                logits=self.session.run(None,{key:inputs[key] for key in self.inputs})[0]
            except Exception:
                if batch_size<=1: raise
                batch_size=max(1,batch_size//2)
                continue
            probabilities=self._probabilities(logits)
            for (index,_,weight),scores in zip(batch,probabilities):
                weighted[index]+=scores*weight; weights[index]+=weight
            start+=len(batch)
        result=[]
        for i in range(len(texts)):
            if not weights[i]:
                result.append(dict(sentiment='NO_CLASIFICADO',score=None,confidence=0.,probabilities=[0.,0.,0.],tokens=0,chunks=0))
                continue
            probs=weighted[i]/weights[i]
            best=int(np.argmax(probs)); confidence=float(probs[best])
            result.append(dict(sentiment=['NEGATIVO','NEUTRO','POSITIVO'][best] if confidence>=.55 else 'NO_CLASIFICADO',
                               score=float(probs[2]-probs[0]),confidence=confidence,
                               probabilities=[float(x) for x in probs],tokens=token_counts[i],chunks=chunk_counts[i]))
        return result


if __name__=='__main__':
    import argparse
    from common import Progress
    ap=argparse.ArgumentParser(); ap.add_argument('--prepare',action='store_true'); args=ap.parse_args()
    if args.prepare:
        progress=Progress('modelos')
        for name in MODEL_SPECS: ensure_model(name,progress)
        progress.update('modelos_descargados',len(MODEL_SPECS),len(MODEL_SPECS),'Descargas verificadas; no se enviaron textos a ninguna API',estado='COMPLETADO')
        progress.close()
