"""Histórico RAG opt-in, SQLite stdlib. Texto local NÃO criptografado.

Diretório privado/arquivo 0600 não substituem criptografia de disco. Sem cookies,
credenciais ou instruções de sistema. Limite global em caracteres, não tokens.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
import threading


class History:
    def __init__(self,data_dir,limit=8_000_000):
        self.path=Path(data_dir)/'history'/'context.sqlite3'
        self.limit=limit
        self.lock=threading.RLock()

    @staticmethod
    def scope(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
            raise ValueError('Histórico exige conversation_id de 1 a 64 letras/números/_/-')
        return value

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():
            raise ValueError('Histórico inválido')
        # Criar antes de conectar impede exposição por umask permissiva.
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600)
        os.close(fd)
        os.chmod(self.path,0o600)
        connection=sqlite3.connect(self.path,timeout=2)
        try:
            connection.execute('PRAGMA secure_delete=ON')
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):
                raise ValueError('Versão do histórico incompatível')
            connection.execute('CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL, chars INTEGER NOT NULL)')
            connection.execute('CREATE INDEX IF NOT EXISTS by_scope ON chunks(scope,id)')
            connection.execute('PRAGMA user_version=1')
            with connection:
                yield connection
        finally:
            connection.close()

    def append(self,scope,question,answer,documents=()):
        self.scope(scope)
        records=[('user',question),('assistant',answer),*[('document',d) for d in documents]]
        if any(not isinstance(text,str) for _,text in records):
            raise ValueError('Histórico aceita somente texto')
        if any(len(text)>self.limit for _,text in records):
            raise ValueError('Registro excede capacidade local')
        with self.lock,self.connect() as db:
            for role,text in records:
                db.execute('INSERT INTO chunks(scope,role,body,chars) VALUES (?,?,?,?)',(scope,role,text,len(text)))
            count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(chars),0) FROM chunks').fetchone()
            while total>self.limit or count>10000:
                identifier,size=db.execute('SELECT id,chars FROM chunks ORDER BY id LIMIT 1').fetchone()
                db.execute('DELETE FROM chunks WHERE id=?',(identifier,))
                total-=size
                count-=1

    def read(self,scope):
        self.scope(scope)
        if not self.path.exists():
            return []
        with self.lock,self.connect() as db:
            # Máximo de registros limita overhead mesmo com muitos textos vazios.
            rows=db.execute('SELECT role,body FROM chunks WHERE scope=? ORDER BY id DESC LIMIT 1900',(scope,)).fetchall()
            return list(reversed(rows))

    def stats(self):
        if not self.path.exists():
            return {'records':0,'characters':0,'encrypted':False}
        with self.lock,self.connect() as db:
            count,chars=db.execute('SELECT COUNT(*),COALESCE(SUM(chars),0) FROM chunks').fetchone()
            return {'records':count,'characters':chars,'encrypted':False}

    def clear(self):
        if not self.path.exists():
            return
        with self.lock,self.connect() as db:
            db.execute('DELETE FROM chunks')
            db.commit()
            db.execute('VACUUM')
