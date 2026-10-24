"""API HTTP do validador Antecipe (biblioteca padrão + pandas/pydantic).

Execute `python api.py` dentro desta pasta. A interface em ./front é servida
na mesma origem da API.
"""
import argparse
import gzip
import json
import mimetypes
import os
import re
import traceback
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from historico import Historico
from servico import Servico

PASTA = os.path.dirname(os.path.abspath(__file__))
PASTA_FRONT = os.path.join(PASTA, "front")
SERVICO = None
HISTORICO = Historico()
MAX_UPLOAD = 40 * 1024 * 1024


def _inteiro(q: dict, nome: str, padrao: int) -> int:
    try:
        return int(q.get(nome, padrao))
    except ValueError as exc:
        raise ValueError(f"{nome} deve ser um número inteiro") from exc


class Handler(BaseHTTPRequestHandler):
    server_version = "ValidadorFIDC/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, payload):
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        compactado = "gzip" in self.headers.get("Accept-Encoding", "").lower() and len(corpo) > 1024
        if compactado:
            corpo = gzip.compress(corpo, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        if compactado:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, status, mensagem):
        self._json(status, {"erro": mensagem})

    def log_message(self, formato, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {formato % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        caminho = url.path.rstrip("/") or "/"
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if caminho == "/api/saude":
                self._json(200, {"ok": True})
            elif caminho == "/api/resumo":
                self._json(200, SERVICO.resumo())
            elif caminho == "/api/regras":
                self._json(200, SERVICO.regras())
            elif caminho == "/api/historico":
                self._json(200, {"analises": HISTORICO.listar(_inteiro(q, "limite", 100))})
            elif re.fullmatch(r"/api/historico/[0-9a-f]{32}", caminho):
                analise = HISTORICO.obter(caminho.rsplit("/", 1)[1])
                if analise is None:
                    self._erro(404, "Análise anterior não encontrada")
                else:
                    self._json(200, analise)
            elif caminho == "/api/notas":
                self._json(200, SERVICO.listar(
                    status=q.get("status"), motivo=q.get("motivo"),
                    busca=q.get("busca"), fundo=q.get("fundo"),
                    ordenar=q.get("ordenar", "linha_csv"),
                    direcao=q.get("direcao", "asc"),
                    pagina=_inteiro(q, "pagina", 1),
                    tamanho=_inteiro(q, "tamanho", 50),
                ))
            elif re.fullmatch(r"/api/notas/\d+", caminho):
                nota = SERVICO.obter(int(caminho.rsplit("/", 1)[1]))
                if nota is None:
                    self._erro(404, "Nota não encontrada (linha fora do processamento atual)")
                else:
                    self._json(200, nota)
            elif caminho.startswith("/api"):
                self._erro(404, "Endpoint não encontrado")
            else:
                self._estatico(caminho)
        except ValueError as exc:
            self._erro(400, str(exc))
        except RuntimeError as exc:
            self._erro(503, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._erro(500, f"Erro interno: {exc}")

    def _receber_arquivo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0:
            raise ValueError("Envie um arquivo CSV ou ZIP no campo 'arquivo'")
        if tamanho > MAX_UPLOAD:
            raise ValueError("O arquivo enviado excede o limite de 40 MB")
        bruto = self.rfile.read(tamanho)
        tipo = self.headers.get("Content-Type", "")
        envelope = (f"Content-Type: {tipo}\r\nMIME-Version: 1.0\r\n\r\n").encode("utf-8") + bruto
        mensagem = BytesParser(policy=policy.default).parsebytes(envelope)
        if not mensagem.is_multipart():
            raise ValueError("O upload precisa usar multipart/form-data")
        for parte in mensagem.iter_parts():
            disposicao = parte.get_content_disposition()
            campo = parte.get_param("name", header="content-disposition")
            nome = parte.get_filename()
            if campo == "arquivo" and (disposicao == "form-data"):
                conteudo = parte.get_payload(decode=True) or b""
                if not conteudo:
                    raise ValueError("O arquivo enviado está vazio")
                return os.path.basename(nome or "arquivo.csv"), conteudo
        raise ValueError("Campo de upload 'arquivo' não encontrado")

    def do_POST(self):
        caminho = urlparse(self.path).path.rstrip("/")
        try:
            if caminho == "/api/recebiveis/validar-lote":
                nome, conteudo = self._receber_arquivo()
                resumo = SERVICO.validar_arquivo(nome, conteudo)
                resultados = SERVICO.todos()
                regras_filtro = SERVICO.filtros_regras()
                registro = HISTORICO.salvar(nome, resumo, regras_filtro, resultados)
                self._json(200, {
                    "resumo": resumo,
                    "resultados": resultados,
                    "regras": regras_filtro,
                    "analise_id": registro["id"],
                    "historico": registro,
                })
            elif caminho == "/api/reprocessar":
                tamanho = int(self.headers.get("Content-Length") or 0)
                if tamanho > 1024 * 1024:
                    return self._erro(413, "Corpo da requisição muito grande")
                bruto = self.rfile.read(tamanho) if tamanho else b""
                corpo = json.loads(bruto.decode("utf-8")) if bruto.strip() else {}
                if not isinstance(corpo, dict):
                    raise ValueError("O corpo deve ser um objeto JSON")
                resumo = SERVICO.processar(
                    data_referencia=corpo.get("data_referencia"),
                    somente_fundo_do_json=corpo.get("somente_fundo_do_json"),
                )
                self._json(200, resumo)
            else:
                self._erro(404, "Endpoint não encontrado")
        except json.JSONDecodeError:
            self._erro(400, "Corpo da requisição não é um JSON válido")
        except ValueError as exc:
            self._erro(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._erro(500, f"Erro interno: {exc}")

    def do_PUT(self):
        caminho = urlparse(self.path).path.rstrip("/")
        if caminho != "/api/regras":
            return self._erro(404, "Endpoint não encontrado")
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > 1024 * 1024:
                return self._erro(413, "Envie uma configuração JSON de até 1 MB")
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            configuracao = SERVICO.atualizar_regras(corpo)
            self._json(200, {
                "ok": True,
                "regras": configuracao,
                "filtros": SERVICO.filtros_regras(),
                "mensagem": "Configuração salva. Ela será usada nas próximas análises.",
            })
        except json.JSONDecodeError:
            self._erro(400, "O corpo não contém um JSON válido")
        except ValueError as exc:
            self._erro(400, str(exc))
        except RuntimeError as exc:
            self._erro(500, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._erro(500, f"Erro interno: {exc}")

    def _estatico(self, caminho):
        relativo = unquote(caminho).lstrip("/") or "index.html"
        arquivo = os.path.normpath(os.path.join(PASTA_FRONT, relativo))
        if not arquivo.startswith(PASTA_FRONT + os.sep):
            return self._erro(403, "Acesso negado")
        if os.path.isdir(arquivo):
            arquivo = os.path.join(arquivo, "index.html")
        if not os.path.isfile(arquivo):
            if relativo == "index.html":
                aviso = (
                    "<h3>API do validador no ar</h3>"
                    "<p>A interface não foi encontrada em <code>front/index.html</code>.</p>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(aviso)))
                self.end_headers()
                self.wfile.write(aviso)
                return
            return self._erro(404, "Arquivo não encontrado")
        tipo = mimetypes.guess_type(arquivo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        with open(arquivo, "rb") as arquivo_aberto:
            corpo = arquivo_aberto.read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(corpo)


def criar_servidor(servico, host="127.0.0.1", porta=8000):
    global SERVICO
    SERVICO = servico
    return ThreadingHTTPServer((host, porta), Handler)


def main():
    ap = argparse.ArgumentParser(description="API do validador de notas")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--arquivo", help="ZIP ou CSV de dados inicial (padrão: o ZIP desta pasta)")
    ap.add_argument("--config", default=os.path.join(PASTA, "validadores_antecipe.json"),
                    help="caminho do JSON de regras e parâmetros")
    ap.add_argument("--data-referencia", help="AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--somente-fundo-do-json", action="store_true",
                    help="opcionalmente filtra para o fundo declarado no JSON")
    args = ap.parse_args()

    servico = Servico(
        args.config,
        caminho_dados=args.arquivo,
        somente_fundo_do_json=args.somente_fundo_do_json,
    )
    print("Processando o estoque padrão...")
    resumo = servico.processar(args.data_referencia)
    contagens = resumo["contagens"]
    print(f"Pronto em {resumo['tempo_processamento_s']}s: "
          f"{resumo['total_processadas']} de {resumo['total_lidas_csv']} linhas processadas | "
          f"aprovadas {contagens['APROVADA']} | reprovadas {contagens['REPROVADA']} | "
          f"inválidas {contagens['INVALIDA']} | duplicadas {contagens['DUPLICADA']}")
    servidor = criar_servidor(servico, args.host, args.porta)
    print(f"Aplicação disponível em http://{args.host}:{args.porta} (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
        servidor.server_close()


if __name__ == "__main__":
    main()
