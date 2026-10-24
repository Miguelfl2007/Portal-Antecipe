import os
from collections import Counter

from leitura import carregar_notas_brutas
from regras import carregar_config
from validacao import processar_notas

PASTA = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    config = carregar_config(os.path.join(PASTA, "validadores_antecipe.json"))
    r = processar_notas(carregar_notas_brutas(), config)

    print(f"Aprovadas: {len(r['aprovadas'])} | Reprovadas: {len(r['reprovadas'])} | "
          f"Inválidas: {len(r['invalidas'])} | Duplicadas: {len(r['duplicadas'])} | "
          f"Ignoradas: {r['ignoradas']}")

    por_regra = Counter(m["codigo"] for rep in r["reprovadas"] for m in rep["motivos"])
    print("\nMotivos de reprovação (uma nota pode ter mais de um):")
    for codigo, qtd in por_regra.most_common():
        print(f"  {codigo}: {qtd}")

    if r["regras_pendentes"]:
        print("\nRegras ativas não avaliadas (falta dado):", r["regras_pendentes"])
    if r["regras_nao_implementadas"]:
        print("Regras ativas sem implementação:", r["regras_nao_implementadas"])
