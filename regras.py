"""Regras de negócio lidas do JSON de validadores.

Só roda os validadores com "ativo": true. Para criar uma regra nova:
escreva a função e registre no dicionário REGRAS_LINHA.
"""
import json
import re
from collections import defaultdict
from decimal import Decimal

PENDENTE = object()  # a regra não pôde ser avaliada (falta dado externo)


def carregar_config(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def regras_ativas(config: dict) -> dict:
    """{codigo: parametros} só dos validadores ativos."""
    return {
        v["codigo"]: v.get("parametros", {})
        for v in config["validadores"]
        if v.get("ativo")
    }


def cnpj_valido(cnpj: str) -> bool:
    d = re.sub(r"\D", "", cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False

    def digito(base, pesos):
        resto = sum(int(n) * p for n, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    return d[12] == digito(d[:12], pesos1) and d[13] == digito(d[:13], pesos2)


def raiz_cnpj(doc: str) -> str:
    return re.sub(r"\D", "", doc)[:8]


def prazo_dias(nota) -> int:
    # Prazo da operação: da aquisição até o vencimento.
    return (nota.data_vencimento_original - nota.data_aquisicao).days


# ---------------------------------------------------------------
# Regras de linha: devolvem a mensagem de erro, ou None se passou
# ---------------------------------------------------------------
def cnpj_sacado_valido(nota, p, ctx):
    if not cnpj_valido(nota.doc_sacado):
        return f"CNPJ do sacado inválido: {nota.doc_sacado}"


def situacao_cadastral_sacado(nota, p, ctx):
    consulta = ctx.get("consulta_situacao")
    if consulta is None:
        return PENDENTE  # o CSV não traz esse dado
    situacao = consulta(nota.doc_sacado)
    if situacao not in p["situacoes_aceitas"]:
        return f"Situação cadastral do sacado não aceita: {situacao}"


def tipo_recebivel(nota, p, ctx):
    if nota.tipo_recebivel not in p["tipos_aceitos"]:
        return f"Tipo de recebível não aceito: {nota.tipo_recebivel}"


def valor_minimo(nota, p, ctx):
    minimo = Decimal(str(p["valor_minimo"]))
    if nota.valor_nominal < minimo:
        return f"Valor {nota.valor_nominal} abaixo do mínimo de {minimo}"


def nao_vencida(nota, p, ctx):
    if nota.data_vencimento_original < ctx["hoje"]:
        return f"Nota vencida em {nota.data_vencimento_original:%d/%m/%Y}"


def prazo_maximo(nota, p, ctx):
    if prazo_dias(nota) > p["prazo_maximo_dias"]:
        return f"Prazo de {prazo_dias(nota)} dias acima do máximo de {p['prazo_maximo_dias']}"


def prazo_minimo(nota, p, ctx):
    if prazo_dias(nota) < p["prazo_minimo_dias"]:
        return f"Prazo de {prazo_dias(nota)} dias abaixo do mínimo de {p['prazo_minimo_dias']}"


REGRAS_LINHA = {
    "CNPJ_SACADO_VALIDO": cnpj_sacado_valido,
    "SITUACAO_CADASTRAL_SACADO": situacao_cadastral_sacado,
    "TIPO_RECEBIVEL": tipo_recebivel,
    "VALOR_MINIMO": valor_minimo,
    "NAO_VENCIDA": nao_vencida,
    "PRAZO_MAXIMO": prazo_maximo,
    "PRAZO_MINIMO": prazo_minimo,
}

REGRAS_CARTEIRA = {"CONCENTRACAO_MAXIMA_SACADO", "CONCENTRACAO_MAXIMA_CEDENTE"}


def regras_nao_implementadas(ativas: dict) -> list:
    return [c for c in ativas if c not in REGRAS_LINHA and c not in REGRAS_CARTEIRA]


def avaliar_linha(nota, ativas: dict, ctx: dict) -> list:
    """Roda as regras de linha ativas. Devolve a lista de motivos de reprovação."""
    motivos = []
    for codigo, params in ativas.items():
        funcao = REGRAS_LINHA.get(codigo)
        if funcao is None:
            continue
        msg = funcao(nota, params, ctx)
        if msg is PENDENTE:
            ctx["pendentes"].add(codigo)
        elif msg:
            motivos.append({"codigo": codigo, "mensagem": msg})
    return motivos


# ---------------------------------------------------------------
# Regras de carteira: precisam do total, então rodam numa 2ª passada
# ---------------------------------------------------------------
def avaliar_concentracao(notas: list, ativas: dict) -> dict:
    """Devolve {linha_csv: [motivos]} das notas cujo grupo passou do limite.

    O percentual é calculado por fundo: soma do grupo / soma de todas as
    notas do fundo que chegaram até aqui. Todas as notas do grupo são
    reprovadas quando o limite estoura.
    """
    verificacoes = []
    if "CONCENTRACAO_MAXIMA_SACADO" in ativas:
        p = ativas["CONCENTRACAO_MAXIMA_SACADO"]
        if p.get("agrupamento") == "RAIZ_CNPJ":
            chave = lambda n: raiz_cnpj(n.doc_sacado)
        else:
            chave = lambda n: n.doc_sacado
        verificacoes.append(("CONCENTRACAO_MAXIMA_SACADO", p, chave, "sacado"))
    if "CONCENTRACAO_MAXIMA_CEDENTE" in ativas:
        p = ativas["CONCENTRACAO_MAXIMA_CEDENTE"]
        verificacoes.append(("CONCENTRACAO_MAXIMA_CEDENTE", p, lambda n: n.doc_cedente, "cedente"))

    reprovadas = defaultdict(list)
    for codigo, p, chave, rotulo in verificacoes:
        limite = Decimal(str(p["percentual_maximo"]))
        total_fundo = defaultdict(Decimal)
        total_grupo = defaultdict(Decimal)
        for n in notas:
            total_fundo[n.doc_fundo] += n.valor_nominal
            total_grupo[(n.doc_fundo, chave(n))] += n.valor_nominal
        for n in notas:
            pct = total_grupo[(n.doc_fundo, chave(n))] / total_fundo[n.doc_fundo] * 100
            if pct > limite:
                reprovadas[n.linha_csv].append({
                    "codigo": codigo,
                    "mensagem": f"Concentração do {rotulo} em {pct:.2f}% acima do máximo de {limite}%",
                })
    return reprovadas
