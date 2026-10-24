from datetime import date

from pydantic import ValidationError

import regras
from modelos import NotaFiscal


def _motivos_leitura(erro: ValidationError) -> list:
    motivos = []
    for err in erro.errors():
        campo = ".".join(str(p) for p in err["loc"]) or "nota"
        msg = err["msg"].removeprefix("Value error, ")
        motivos.append({"codigo": "DADO_INVALIDO", "mensagem": f"{campo}: {msg}"})
    return motivos


def _resumo_nota(nota: NotaFiscal, motivos: list) -> dict:
    return {
        "linha_csv": nota.linha_csv,
        "nu_documento": nota.nu_documento,
        "doc_cedente": nota.doc_cedente,
        "doc_sacado": nota.doc_sacado,
        "tipo_recebivel": nota.tipo_recebivel,
        "valor_nominal": float(nota.valor_nominal),
        "data_vencimento": nota.data_vencimento_original.isoformat(),
        "motivos": motivos,
    }


def processar_notas(
    notas_brutas,
    config,
    data_referencia=None,
    consulta_situacao=None,
    somente_fundo_do_json=False,
):
    """Lê, deduplica e aplica as regras do JSON.

    data_referencia: "hoje" para NAO_VENCIDA (padrão: data do computador).
    consulta_situacao: função doc_cnpj -> situação ("ATIVA"...). Sem ela,
        SITUACAO_CADASTRAL_SACADO fica pendente e não reprova ninguém.
    somente_fundo_do_json: True avalia só as notas do fundo do JSON.
    """
    ativas = regras.regras_ativas(config)
    ctx = {
        "hoje": data_referencia or date.today(),
        "consulta_situacao": consulta_situacao,
        "pendentes": set(),
    }
    cnpj_fundo = config["fundo"]["cnpj"]

    aprovadas, reprovadas, invalidas, duplicadas = [], [], [], []
    candidatas = []          # passaram nas regras de linha
    chaves_vistas = set()
    ignoradas = 0

    for bruta in notas_brutas:
        if somente_fundo_do_json and bruta.get("DOC_FUNDO", "").strip() != cnpj_fundo:
            ignoradas += 1
            continue

        # 1) leitura e conversão
        try:
            nota = NotaFiscal(**bruta)
        except ValidationError as e:
            invalidas.append({
                "linha_csv": bruta["linha_csv"],
                "nu_documento": bruta.get("NU_DOCUMENTO"),
                "motivos": _motivos_leitura(e),
            })
            continue

        # 2) duplicidade
        if nota.chave_duplicidade in chaves_vistas:
            duplicadas.append(_resumo_nota(
                nota, [{"codigo": "DUPLICADA", "mensagem": "Nota fiscal duplicada"}]
            ))
            continue
        chaves_vistas.add(nota.chave_duplicidade)

        # 3) regras de linha
        motivos = regras.avaliar_linha(nota, ativas, ctx)
        if motivos:
            reprovadas.append(_resumo_nota(nota, motivos))
        else:
            candidatas.append(nota)

    # 4) regras de carteira (precisam do total)
    motivos_carteira = regras.avaliar_concentracao(candidatas, ativas)
    for nota in candidatas:
        if nota.linha_csv in motivos_carteira:
            reprovadas.append(_resumo_nota(nota, motivos_carteira[nota.linha_csv]))
        else:
            aprovadas.append(nota)

    reprovadas.sort(key=lambda r: r["linha_csv"])

    return {
        "aprovadas": aprovadas,
        "reprovadas": reprovadas,
        "invalidas": invalidas,
        "duplicadas": duplicadas,
        "ignoradas": ignoradas,
        "regras_pendentes": sorted(ctx["pendentes"]),
        "regras_nao_implementadas": regras.regras_nao_implementadas(ativas),
    }
