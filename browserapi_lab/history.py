"""Histórico RAG opt-in em arquivo JSON privado, sem banco/dependência adicional.

Texto NÃO criptografado. Permissões não substituem criptografia de disco.
Limite global em caracteres, não tokens. Escritas atômicas pelo ConfigStore.
"""
import json
import os
from pathlib import Path
import re
import threading

from .config import ConfigStore


class History:
    def __init__(self,data_dir,limit=8_000_000):
        self.path=Path(data_dir)/'history'/'context-history.json'
        self.limit=limit
        self.lock=threading.RLock()

    @staticmethod
    def scope(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
            raise ValueError('Histórico exige conversation_id de 1 a 64 letras/números/_/-')
        return value

    def _read(self):
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('Histórico inválido')
        if not self.path.exists():
            return []
        if not self.path.is_file() or self.path.stat().st_uid!=os.getuid() or self.path.stat().st_size>50_000_000:
            raise ValueError('Histórico inválido')
        with self.path.open('rb') as stream:
            raw=stream.read(50_000_001)
        if len(raw)>50_000_000:
            raise ValueError('Histórico excede capacidade')
        value=json.loads(raw)
        if not isinstance(value,dict) or value.get('schema')!=1 or not isinstance(value.get('records'),list):
            raise ValueError('Histórico incompatível')
        records=value['records']
        if len(records)>10000:
            raise ValueError('Histórico excede capacidade')
        total=0
        for record in records:
            if not isinstance(record,list) or len(record)!=3 or record[1] not in ('user','assistant','document') or not isinstance(record[2],str):
                raise ValueError('Histórico inválido')
            self.scope(record[0])
            total+=len(record[2])
        if total>self.limit:
            raise ValueError('Histórico excede capacidade')
        return records

    def _write(self,records):
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError('Histórico inválido')
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        ConfigStore.write_json(self.path,{'schema':1,'records':records})

    def append(self,scope,question,answer,documents=()):
        self.scope(scope)
        new=[(scope,'user',question),(scope,'assistant',answer),*[(scope,'document',d) for d in documents]]
        if any(not isinstance(text,str) for _,_,text in new):
            raise ValueError('Histórico aceita somente texto')
        if any(len(text)>self.limit for _,_,text in new):
            raise ValueError('Registro excede capacidade local')
        with self.lock:
            records=self._read()+new
            total=sum(len(r[2]) for r in records)
            start=0
            while total>self.limit or len(records)-start>10000:
                total-=len(records[start][2]);start+=1
            self._write(records[start:])

    def read(self,scope):
        self.scope(scope)
        with self.lock:
            return [(role,text) for identifier,role,text in self._read() if identifier==scope]

    def stats(self):
        with self.lock:
            records=self._read()
            return {'records':len(records),'characters':sum(len(r[2]) for r in records),'encrypted':False}

    def clear(self):
        with self.lock:
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise ValueError('Histórico inválido')
            self.path.unlink(missing_ok=True)
