"""Camada de serviço do validador Antecipe.

Converte os resultados das regras de negócio em uma resposta JSON consumível
pela interface e oferece consultas paginadas para os endpoints da API.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from leitura import carregar_notas_brutas
from regras import carregar_config
from validacao import processar_notas


PASTA = os.path.dirname(os.path.abspath(__file__))


class Servico:
    def __init__(self, caminho_config, caminho_dados=None, somente_fundo_do_json=False):
        self.caminho_config = caminho_config
        self.caminho_dados = caminho_dados
        self.config = carregar_config(caminho_config)
        self.somente_fundo_do_json = somente_fundo_do_json
        self._resultados = []
        self._resumo = {}
        self._data_referencia = date.today()
        self._tempo_processamento_s = 0.0

    def _parse_data(self, valor):
        if not valor:
            return date.today()
        if isinstance(valor, date):
            return valor
        try:
            return datetime.strptime(str(valor), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("data_referencia deve estar no formato AAAA-MM-DD") from exc

    def _carregar_padrao(self):
        if self.caminho_dados:
            notas = self._ler_arquivo(self.caminho_dados, None)
            return notas
        return carregar_notas_brutas()

    def _ler_csv(self, conteudo):
        try:
            df = pd.read_csv(
                io.BytesIO(conteudo), sep=";", encoding="utf-8-sig",
                dtype=str, keep_default_na=False, on_bad_lines="error",
            )
        except Exception as exc:
            raise ValueError(f"Não foi possível ler o CSV: {exc}") from exc
        if len(df.columns) < 2:
            raise ValueError("CSV inválido: esperado separador ponto e vírgula (;) e cabeçalho")
        return [{"linha_csv": i + 2, **registro} for i, registro in enumerate(df.to_dict("records"))]

    def _ler_arquivo(self, nome, conteudo):
        if conteudo is None:
            with open(nome, "rb") as arquivo:
                conteudo = arquivo.read()
        nome = (nome or "arquivo.csv").lower()
        if nome.endswith(".zip") or conteudo[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
                    candidatos = [n for n in pacote.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]
                    if not candidatos:
                        internos = [n for n in pacote.namelist() if n.lower().endswith(".zip")]
                        if internos:
                            return self._ler_arquivo(internos[0], pacote.read(internos[0]))
                        raise ValueError("O ZIP não contém nenhum arquivo CSV")
                    escolhido = candidatos[0]
                    info = pacote.getinfo(escolhido)
                    if info.file_size > 150 * 1024 * 1024:
                        raise ValueError("O CSV descompactado excede o limite de 150 MB")
                    return self._ler_csv(pacote.read(escolhido))
            except zipfile.BadZipFile as exc:
                raise ValueError("O arquivo enviado não é um ZIP válido") from exc
        if not nome.endswith(".csv"):
            raise ValueError("Formato não suportado. Envie um arquivo CSV ou ZIP com um CSV dentro")
        return self._ler_csv(conteudo)

    def validar_arquivo(self, nome, conteudo, data_referencia=None):
        if len(conteudo) > 40 * 1024 * 1024:
            raise ValueError("O arquivo enviado excede o limite de 40 MB")
        notas = self._ler_arquivo(nome, conteudo)
        return self._processar(notas, data_referencia, self.somente_fundo_do_json)

    def processar(self, data_referencia=None, somente_fundo_do_json=None):
        notas = self._carregar_padrao()
        if somente_fundo_do_json is None:
            somente_fundo_do_json = self.somente_fundo_do_json
        return self._processar(notas, data_referencia, somente_fundo_do_json)

    def _processar(self, notas_brutas, data_referencia=None, somente_fundo_do_json=False):
        inicio = datetime.now()
        referencia = self._parse_data(data_referencia)
        resultado = processar_notas(
            notas_brutas,
            self.config,
            data_referencia=referencia,
            somente_fundo_do_json=bool(somente_fundo_do_json),
        )
        por_linha = {}
        for grupo, status in ((resultado["aprovadas"], "APROVADA"),
                              (resultado["reprovadas"], "REPROVADA"),
                              (resultado["invalidas"], "INVALIDA"),
                              (resultado["duplicadas"], "DUPLICADA")):
            for item in grupo:
                if hasattr(item, "model_dump"):
                    item = {
                        "linha_csv": item.linha_csv,
                        "nu_documento": item.nu_documento,
                        "doc_cedente": item.doc_cedente,
                        "doc_sacado": item.doc_sacado,
                        "tipo_recebivel": item.tipo_recebivel,
                        "valor_nominal": float(item.valor_nominal),
                        "data_vencimento": item.data_vencimento_original.isoformat(),
                        "motivos": [],
                    }
                por_linha[item["linha_csv"]] = (item, status)

        taxa = Decimal(str(self.config.get("precificacao", {}).get("taxa_mensal_percentual", 0)))
        base_dias = Decimal(str(self.config.get("precificacao", {}).get("base_dias", 30)))
        registros = []
        for bruto in notas_brutas:
            linha = bruto.get("linha_csv")
            par = por_linha.get(linha)
            if not par:
                continue
            item, status = par
            motivos = item.get("motivos", [])
            motivo = "; ".join(str(m.get("mensagem", "")) for m in motivos if m.get("mensagem"))
            codigo = motivos[0].get("codigo", "") if motivos else ""
            valor_bruto = item.get("valor_nominal", bruto.get("VALOR_NOMINAL", ""))
            vencimento = item.get("data_vencimento", bruto.get("DATA_VENCIMENTO_ORIGINAL", ""))
            desconto = None
            liquido = None
            if status == "APROVADA":
                try:
                    valor_dec = Decimal(str(valor_bruto))
                    venc = date.fromisoformat(str(vencimento)) if "-" in str(vencimento) else datetime.strptime(str(vencimento), "%d/%m/%Y").date()
                    dias = max(0, (venc - referencia).days)
                    desconto_dec = valor_dec * taxa / Decimal(100) * Decimal(dias) / base_dias
                    desconto = round(float(desconto_dec), 2)
                    liquido = round(float(valor_dec - desconto_dec), 2)
                except (ValueError, ArithmeticError, TypeError):
                    desconto = 0.0
                    try:
                        liquido = round(float(valor_bruto), 2)
                    except (ValueError, TypeError):
                        liquido = None
            registros.append({
                "id": str(linha),
                "linha_csv": linha,
                "nu_documento": str(item.get("nu_documento") or bruto.get("NU_DOCUMENTO") or ""),
                "nome_sacado": str(bruto.get("NOME_SACADO", "")),
                "data_vencimento": str(vencimento),
                "valor_nominal": valor_bruto,
                "desconto": desconto,
                "valor_liquido": liquido,
                "status": status,
                "codigo_regra": codigo,
                "motivo_titulo": "Nota aprovada" if status == "APROVADA" else (motivos[0].get("codigo", "Nota não elegível").replace("_", " ").title() if motivos else "Nota não elegível"),
                "motivo": motivo or ("A nota passou pelos validadores ativos do fundo." if status == "APROVADA" else "Não foi possível validar a nota com os dados fornecidos."),
                "motivos": motivos,
                "doc_cedente": item.get("doc_cedente", bruto.get("DOC_CEDENTE", "")),
                "doc_sacado": item.get("doc_sacado", bruto.get("DOC_SACADO", "")),
                "tipo_recebivel": item.get("tipo_recebivel", bruto.get("TIPO_RECEBIVEL", "")),
            })

        contagens = {
            "APROVADA": sum(r["status"] == "APROVADA" for r in registros),
            "REPROVADA": sum(r["status"] == "REPROVADA" for r in registros),
            "INVALIDA": sum(r["status"] == "INVALIDA" for r in registros),
            "DUPLICADA": sum(r["status"] == "DUPLICADA" for r in registros),
        }
        self._resultados = registros
        self._data_referencia = referencia
        self._tempo_processamento_s = (datetime.now() - inicio).total_seconds()
        self._resumo = {
            "total_lidas_csv": len(notas_brutas),
            "total_processadas": len(registros),
            "contagens": contagens,
            "ignoradas": resultado["ignoradas"],
            "regras_pendentes": resultado["regras_pendentes"],
            "regras_nao_implementadas": resultado["regras_nao_implementadas"],
            "tempo_processamento_s": round(self._tempo_processamento_s, 3),
            "data_referencia": referencia.isoformat(),
            "fundo": self.config.get("fundo", {}).get("nome", ""),
        }
        return self.resumo()

    def resumo(self):
        return {**self._resumo, "total_aprovado_liquido": round(sum(float(r["valor_liquido"] or 0) for r in self._resultados if r["status"] == "APROVADA"), 2)}

    def regras(self):
        return self.config

    def atualizar_regras(self, nova_config):
        """Valida a estrutura genérica, persiste e aplica o JSON recebido."""
        import json
        import tempfile

        if not isinstance(nova_config, dict):
            raise ValueError("A configuração deve ser um objeto JSON")
        fundo = nova_config.get("fundo")
        if not isinstance(fundo, dict) or not isinstance(fundo.get("cnpj"), str):
            raise ValueError("A configuração precisa conter um objeto 'fundo' com o campo 'cnpj'")
        validadores = nova_config.get("validadores")
        if not isinstance(validadores, list):
            raise ValueError("A configuração precisa conter uma lista 'validadores'")
        if "precificacao" in nova_config and not isinstance(nova_config["precificacao"], dict):
            raise ValueError("O campo 'precificacao' precisa ser um objeto JSON")
        codigos = set()
        for indice, validador in enumerate(validadores, start=1):
            if not isinstance(validador, dict):
                raise ValueError(f"O validador {indice} deve ser um objeto JSON")
            codigo = validador.get("codigo")
            if not isinstance(codigo, str) or not codigo.strip():
                raise ValueError(f"O validador {indice} precisa ter um código")
            if codigo in codigos:
                raise ValueError(f"Código de validador repetido: {codigo}")
            codigos.add(codigo)
            if "ativo" in validador and not isinstance(validador["ativo"], bool):
                raise ValueError(f"O campo 'ativo' do validador {codigo} precisa ser verdadeiro ou falso")
            if "parametros" in validador and not isinstance(validador["parametros"], dict):
                raise ValueError(f"Os parâmetros do validador {codigo} precisam ser um objeto JSON")
        pasta = os.path.dirname(os.path.abspath(self.caminho_config))
        arquivo_temporario = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=pasta, delete=False) as destino:
                arquivo_temporario = destino.name
                json.dump(nova_config, destino, ensure_ascii=False, indent=2)
                destino.write("\n")
            os.replace(arquivo_temporario, self.caminho_config)
        except OSError as exc:
            if arquivo_temporario and os.path.exists(arquivo_temporario):
                os.unlink(arquivo_temporario)
            raise RuntimeError(f"Não foi possível salvar o JSON de validadores: {exc}") from exc
        self.config = nova_config
        return self.config

    def filtros_regras(self):
        """Metadados dos filtros derivados dos validadores do JSON ativo."""
        return [
            {
                "codigo": str(item.get("codigo", "")),
                "nome": str(item.get("nome") or str(item.get("codigo", "")).replace("_", " ").title()),
                "ativo": bool(item.get("ativo", False)),
            }
            for item in self.config.get("validadores", [])
            if item.get("codigo")
        ]

    def obter(self, linha_csv):
        return next((dict(r) for r in self._resultados if r["linha_csv"] == linha_csv), None)

    def todos(self):
        """Retorna cada linha processada, na ordem original do CSV."""
        return [dict(r) for r in self._resultados]

    def listar(self, status=None, motivo=None, busca=None, fundo=None, ordenar="linha_csv", direcao="asc", pagina=1, tamanho=50):
        if pagina < 1 or tamanho < 1 or tamanho > 1000:
            raise ValueError("pagina deve ser >= 1 e tamanho deve estar entre 1 e 1000")
        itens = list(self._resultados)
        if status:
            wanted = status.upper()
            itens = [r for r in itens if r["status"] == wanted]
        if motivo:
            termo = motivo.casefold()
            itens = [r for r in itens if termo in r["motivo"].casefold() or termo in r["codigo_regra"].casefold()]
        if busca:
            termo = busca.casefold()
            itens = [r for r in itens if termo in r["nu_documento"].casefold() or termo in r["nome_sacado"].casefold()]
        if fundo:
            termo = fundo.casefold()
            itens = [r for r in itens if termo in str(r.get("fundo", "")).casefold()]
        if ordenar not in {"linha_csv", "nu_documento", "valor_nominal", "data_vencimento", "status"}:
            ordenar = "linha_csv"
        itens.sort(key=lambda r: str(r.get(ordenar, "")), reverse=direcao.lower() == "desc")
        inicio = (pagina - 1) * tamanho
        return {"total": len(itens), "pagina": pagina, "tamanho": tamanho, "notas": itens[inicio:inicio + tamanho]}
