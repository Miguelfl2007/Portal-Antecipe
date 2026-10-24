"""Persistência local de análises anteriores em SQLite."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

PASTA = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ANTECIPE_DB_PATH", os.path.join(PASTA, "antecipe_historico.sqlite3"))


class Historico:
    def __init__(self, caminho=DB_PATH):
        self.caminho = caminho
        pasta = os.path.dirname(os.path.abspath(caminho))
        os.makedirs(pasta, exist_ok=True)
        with self._conectar() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS analises (
                    id TEXT PRIMARY KEY,
                    arquivo TEXT NOT NULL,
                    criada_em TEXT NOT NULL,
                    resumo_json TEXT NOT NULL,
                    regras_json TEXT NOT NULL,
                    resultados_gzip BLOB NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_analises_criada_em ON analises(criada_em DESC)")

    def _conectar(self):
        db = sqlite3.connect(self.caminho, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def salvar(self, arquivo, resumo, regras, resultados):
        analise_id = uuid.uuid4().hex
        criada_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
        resumo_json = json.dumps(resumo, ensure_ascii=False, separators=(",", ":"))
        regras_json = json.dumps(regras, ensure_ascii=False, separators=(",", ":"))
        resultados_gzip = gzip.compress(
            json.dumps(resultados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            compresslevel=5,
        )
        with self._conectar() as db:
            db.execute(
                "INSERT INTO analises (id, arquivo, criada_em, resumo_json, regras_json, resultados_gzip) VALUES (?, ?, ?, ?, ?, ?)",
                (analise_id, os.path.basename(arquivo), criada_em, resumo_json, regras_json, resultados_gzip),
            )
        return {"id": analise_id, "arquivo": os.path.basename(arquivo), "criada_em": criada_em, "resumo": resumo}

    def listar(self, limite=100):
        limite = max(1, min(int(limite), 500))
        with self._conectar() as db:
            rows = db.execute(
                "SELECT id, arquivo, criada_em, resumo_json FROM analises ORDER BY criada_em DESC, rowid DESC LIMIT ?",
                (limite,),
            ).fetchall()
        return [
            {"id": row["id"], "arquivo": row["arquivo"], "criada_em": row["criada_em"], "resumo": json.loads(row["resumo_json"])}
            for row in rows
        ]

    def obter(self, analise_id):
        with self._conectar() as db:
            row = db.execute(
                "SELECT id, arquivo, criada_em, resumo_json, regras_json, resultados_gzip FROM analises WHERE id = ?",
                (analise_id,),
            ).fetchone()
        if row is None:
            return None
        resultados = json.loads(gzip.decompress(row["resultados_gzip"]).decode("utf-8"))
        return {
            "id": row["id"],
            "arquivo": row["arquivo"],
            "criada_em": row["criada_em"],
            "resumo": json.loads(row["resumo_json"]),
            "regras": json.loads(row["regras_json"]),
            "resultados": resultados,
        }
