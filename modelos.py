from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotaFiscal(BaseModel):
    """Lê e converte uma linha do CSV (texto -> tipos Python).

    Aqui só entra o que impede a nota de ser lida (campo vazio, data ou valor
    ilegível). As regras de negócio do JSON ficam em regras.py.
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    linha_csv: int
    nome_fundo: str = Field(alias="NOME_FUNDO")
    doc_fundo: str = Field(alias="DOC_FUNDO")
    nome_cedente: str = Field(alias="NOME_CEDENTE")
    doc_cedente: str = Field(alias="DOC_CEDENTE")
    nome_sacado: str = Field(alias="NOME_SACADO")
    doc_sacado: str = Field(alias="DOC_SACADO")
    nu_documento: str = Field(alias="NU_DOCUMENTO")
    tipo_recebivel: str = Field(alias="TIPO_RECEBIVEL")
    valor_nominal: Decimal = Field(alias="VALOR_NOMINAL")
    data_vencimento_original: date = Field(alias="DATA_VENCIMENTO_ORIGINAL")
    data_aquisicao: date = Field(alias="DATA_AQUISICAO")

    @field_validator(
        "nome_fundo", "doc_fundo", "nome_cedente", "doc_cedente",
        "nome_sacado", "doc_sacado", "nu_documento", "tipo_recebivel",
    )
    @classmethod
    def obrigatorio(cls, v: str) -> str:
        if not v:
            raise ValueError("Campo obrigatório vazio")
        return v

    # "2278,08" -> Decimal("2278.08")
    @field_validator("valor_nominal", mode="before")
    @classmethod
    def converter_valor(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Valor vazio")
            try:
                return Decimal(v.replace(".", "").replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"Valor com formato inválido: {v}")
        return v

    # "07/10/2026" -> date(2026, 10, 7)
    @field_validator("data_vencimento_original", "data_aquisicao", mode="before")
    @classmethod
    def converter_data(cls, v):
        if isinstance(v, str):
            try:
                return datetime.strptime(v.strip(), "%d/%m/%Y").date()
            except ValueError:
                raise ValueError(f"Data inválida (esperado DD/MM/AAAA): {v!r}")
        return v

    @property
    def chave_duplicidade(self) -> tuple:
        # O mesmo NU_DOCUMENTO aparece em parcelas diferentes,
        # por isso o vencimento entra na chave.
        return (
            self.doc_cedente,
            self.doc_sacado,
            self.nu_documento,
            self.data_vencimento_original,
        )
