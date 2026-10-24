from datetime import date

from regras import carregar_config
from validacao import processar_notas

base = {
    "linha_csv": 2,
    "NOME_FUNDO": "ANTECIPE FIDC", "DOC_FUNDO": "92.234.400/0001-80",
    "NOME_CEDENTE": "X", "DOC_CEDENTE": "10.062.050/0001-57",
    "NOME_SACADO": "Y", "DOC_SACADO": "22.144.961/0001-02",
    "NU_DOCUMENTO": "1", "TIPO_RECEBIVEL": "Duplicata",
    "VALOR_NOMINAL": "500,00",
    "DATA_VENCIMENTO_ORIGINAL": "07/12/2026", "DATA_AQUISICAO": "27/10/2026",
}

linhas = [
    base,                                                                   # aprovada
    {**base, "linha_csv": 3},                                               # duplicada
    {**base, "linha_csv": 4, "DATA_VENCIMENTO_ORIGINAL": "07/01/2027"},     # outra parcela: aprovada
    {**base, "linha_csv": 5, "NU_DOCUMENTO": "2", "VALOR_NOMINAL": "50,00"},          # VALOR_MINIMO
    {**base, "linha_csv": 6, "NU_DOCUMENTO": "3", "TIPO_RECEBIVEL": "Cheque"},        # TIPO_RECEBIVEL
    {**base, "linha_csv": 7, "NU_DOCUMENTO": "4", "DATA_VENCIMENTO_ORIGINAL": "01/10/2026",
     "DATA_AQUISICAO": "01/09/2026"},                                                 # NAO_VENCIDA
    {**base, "linha_csv": 8, "NU_DOCUMENTO": "5", "DATA_VENCIMENTO_ORIGINAL": "01/12/2027"},  # PRAZO_MAXIMO
    {**base, "linha_csv": 9, "NU_DOCUMENTO": "6", "DOC_SACADO": "11.111.111/1111-11"},        # CNPJ inválido
    {**base, "linha_csv": 10, "NU_DOCUMENTO": "7", "VALOR_NOMINAL": "abc"},                   # ilegível
]

config = carregar_config("validadores_antecipe.json")

# A concentração depende do tamanho da carteira. Este teste tem poucas notas,
# então ela fica desligada aqui (é exercitada ao rodar o main.py com o CSV).
for v in config["validadores"]:
    if v["codigo"].startswith("CONCENTRACAO"):
        v["ativo"] = False
r = processar_notas(linhas, config, data_referencia=date(2026, 10, 24))

print("aprovadas:", [n.linha_csv for n in r["aprovadas"]])
for chave in ("reprovadas", "invalidas", "duplicadas"):
    print(f"\n{chave}:")
    for item in r[chave]:
        print(" ", item["linha_csv"], [m["codigo"] for m in item["motivos"]])
print("\npendentes:", r["regras_pendentes"])
