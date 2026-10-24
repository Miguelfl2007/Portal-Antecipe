"""Leitura genérica de CSV ou ZIP de dados."""
import os
import zipfile

import pandas as pd


def carregar_notas_brutas(caminho=None):
    """Carrega todas as linhas de um CSV ou do primeiro CSV encontrado num ZIP.

    O caminho pode ser passado pelo chamador ou pela variável de ambiente
    ANTECIPE_DATA_FILE. Sem caminho, usa o primeiro CSV/ZIP distribuído junto
    com este módulo. Linhas malformadas provocam erro explícito: não são puladas.
    """
    pasta = os.path.dirname(os.path.abspath(__file__))
    caminho = caminho or os.environ.get("ANTECIPE_DATA_FILE")
    if not caminho:
        candidatos = sorted(
            os.path.join(pasta, nome) for nome in os.listdir(pasta)
            if nome.lower().endswith((".csv", ".zip"))
        )
        if not candidatos:
            raise FileNotFoundError(
                "Nenhum CSV/ZIP de dados foi encontrado. Passe --arquivo ou defina ANTECIPE_DATA_FILE."
            )
        caminho = candidatos[0]

    if str(caminho).lower().endswith(".zip"):
        with zipfile.ZipFile(caminho, "r") as pacote:
            candidatos = [
                nome for nome in pacote.namelist()
                if nome.lower().endswith(".csv") and not nome.endswith("/")
            ]
            if not candidatos:
                raise ValueError(f"O ZIP {caminho!r} não contém CSV")
            with pacote.open(candidatos[0]) as arquivo:
                df = pd.read_csv(
                    arquivo, sep=";", encoding="utf-8-sig", dtype=str,
                    keep_default_na=False, on_bad_lines="error",
                )
    else:
        df = pd.read_csv(
            caminho, sep=";", encoding="utf-8-sig", dtype=str,
            keep_default_na=False, on_bad_lines="error",
        )

    return [
        {"linha_csv": i + 2, **registro}
        for i, registro in enumerate(df.to_dict("records"))
    ]
