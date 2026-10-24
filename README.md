> Visão Geral:

O projeto é uma aplicação local em Python, servida por uma API HTTP simples. A interface fica em front/index.html e é servida pelo mesmo processo da API. O fluxo principal é: a interface envia CSV/ZIP → o serviço lê as linhas → a validação aplica os validadores ativos do JSON → a API devolve os resultados e os grava no histórico SQLite.


> Execução da Aplicação:

# Antecipe — interface + backend integrados
A API aplica os validadores ativos e os parâmetros carregados de `validadores_antecipe.json` a todas as linhas do CSV. Por padrão, não filtra por fundo. O resultado conta linhas lidas e processadas; linhas malformadas geram erro explícito em vez de serem ignoradas silenciosamente.

## Executar no Windows (CMD)

1. Extraia o pacote ZIP.
2. Abra o CMD na pasta `Antecipe-integrado` (a que contém `api.py` e `requirements.txt`).
3. Instale os requisitos:

```cmd
py -m pip install -r requirements.txt
```

4. Inicie o servidor:

```cmd
py api.py
```

5. Abra `http://127.0.0.1:8000` no navegador. Selecione o CSV ou ZIP que deseja analisar e clique em **Analisar lote**. Mantenha o CMD aberto durante o uso; `Ctrl+C` encerra o servidor.

O pacote carrega o estoque ZIP incluído como lote demonstrativo ao iniciar. O arquivo escolhido na interface é processado novamente, integralmente, sem filtro de fundo. Para processar somente o fundo descrito no JSON, use `py api.py --somente-fundo-do-json`.

## Configuração sem valores fixos no código

`validadores_antecipe.json` é a fonte de verdade dos parâmetros do fundo, validadores ativos e precificação. Na interface, use **Editar validadores** para ativar/desativar cada entrada e alterar seu objeto de parâmetros em JSON. A lista é montada diretamente do arquivo carregado, sem opções de validador fixadas na interface. Salvar grava o JSON no disco e aplica a configuração às próximas análises; as análises já concluídas não são recalculadas. Também é possível editar/substituir o JSON manualmente e reiniciar o servidor, ou indicar outro arquivo:

```cmd
py api.py --config "C:\caminho\para\validadores_antecipe.json"
```

A implementação contém o código dos tipos de regra suportados, mas não fixa no código os limites, listas de tipos aceitos, fundo ou taxa: esses dados são lidos do JSON. Um validador novo requer suporte de implementação correspondente antes de poder ser executado.

## Arquivos de entrada

Aceita CSV separado por ponto e vírgula (`;`) ou ZIP contendo CSV. A API envia todos os resultados para a interface. Se o CSV tiver linhas malformadas, a importação informa o erro para que nenhuma linha seja descartada sem aviso.

Na tabela de resultados, além da busca e do filtro de status, há um filtro por regra. As opções são geradas da lista `validadores` no JSON carregado, exibindo regras ativas e inativas; ao escolher um código, a tabela mostra as notas que têm aquele código entre os motivos retornados pelo backend. O botão **Análises anteriores** abre os lotes persistidos no banco SQLite local (`antecipe_historico.sqlite3`); selecione um item para consultar novamente seus resultados e filtros. Uma análise é salva automaticamente ao concluir o upload.

## API

- `GET /api/saude` — estado do servidor.
- `GET /api/resumo` — resumo, incluindo linhas lidas e processadas.
- `GET /api/regras` — configuração ativa carregada do JSON.
- `PUT /api/regras` — valida e salva uma configuração JSON, aplicada às próximas análises.
- `GET /api/historico` — lista análises salvas localmente.
- `GET /api/historico/{id}` — abre uma análise anterior.
- `GET /api/notas` — notas paginadas.
- `GET /api/notas/{linha_csv}` — detalhe de uma nota.
- `POST /api/recebiveis/validar-lote` — multipart/form-data, arquivo no campo `arquivo`.
- `POST /api/reprocessar` — reprocessa o estoque inicial com JSON opcional `data_referencia` e `somente_fundo_do_json`.

A situação cadastral do sacado permanece como regra pendente quando não há fonte externa para consultá-la; o CSV não traz esse dado. Respostas JSON grandes são comprimidas automaticamente quando o cliente aceita gzip. O histórico usa SQLite da biblioteca padrão do Python e fica junto ao aplicativo; a localização pode ser alterada com a variável de ambiente `ANTECIPE_DB_PATH`.
