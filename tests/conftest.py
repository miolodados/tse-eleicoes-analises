"""Fixtures sintéticas para testes unitários offline da Fase 0."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tse_analysis.inventory.catalog import SourceCatalog, load_source_catalog

SENSITIVE_ROW_SENTINEL = "CPF_SENSIVEL_99988877766_TEXTO_LIVRE_URNA"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Retorna o diretório raiz do repositório tse-analysis."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def catalog(repo_root: Path) -> SourceCatalog:
    """Carrega o catálogo oficial configs/sources.yml."""
    return load_source_catalog(repo_root / "configs" / "sources.yml")


@pytest.fixture()
def latin1_csv_file(tmp_path: Path) -> Path:
    """Cria um CSV sintético codificado em ISO-8859-1 (latin1) no padrão TSE."""
    csv_path = tmp_path / "bweb_1t_AC_051020261403.csv"
    header = (
        '"ANO_ELEICAO";"NR_TURNO";"SG_UF";"CD_MUNICIPIO";"NR_ZONA";'
        '"NR_SECAO";"CD_CARGO_PERGUNTA";"NR_VOTAVEL";"QT_VOTOS";'
        '"NR_URNA_EFETIVADA";"DS_OBSERVACAO_SEÇÃO"\r\n'
    )
    row = (
        f'"2026";"1";"AC";"01392";"0001";"0010";"1";"13";"210";'
        f'"2099111";"Município Rio Branco - {SENSITIVE_ROW_SENTINEL}"\r\n'
    )
    csv_path.write_bytes((header + row).encode("latin1"))
    return csv_path


@pytest.fixture()
def utf8_csv_file(tmp_path: Path) -> Path:
    """Cria um CSV sintético codificado em UTF-8."""
    csv_path = tmp_path / "votacao_secao_2026_SP.csv"
    header = (
        '"ANO_ELEICAO";"NR_TURNO";"SG_UF";"CD_MUNICIPIO";"NR_ZONA";'
        '"NR_SECAO";"CD_CARGO";"NR_VOTAVEL";"QT_VOTOS"\n'
    )
    row = f'"2026";"1";"SP";"71072";"0001";"0001";"1";"13";"320";"{SENSITIVE_ROW_SENTINEL}"\n'
    csv_path.write_bytes((header + row).encode("utf-8"))
    return csv_path


@pytest.fixture()
def zip_with_latin1_csv(tmp_path: Path, latin1_csv_file: Path) -> Path:
    """Cria um pacote ZIP contendo um CSV em Latin-1 e um arquivo de hash .sha512."""
    zip_path = tmp_path / "bweb_1t_AC_051020261403.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bweb_1t_AC_051020261403.csv", latin1_csv_file.read_bytes())
        zf.writestr("bweb_1t_AC_051020261403.sha512", b"deadbeef  bweb_1t_AC_051020261403.csv\n")
        zf.writestr("leiame_boletim_urna.pdf", b"%PDF-1.4 synthetic doc")
    return zip_path


@pytest.fixture()
def zip_totalizacao_with_jez(tmp_path: Path) -> Path:
    """Cria um pacote ZIP simulando arquivos transmitidos para totalização contendo .jez."""
    zip_path = tmp_path / "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o00407-0139200010010.jez", b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32)
        zf.writestr("o00407-0139200010010.bu", b"\x30\x82\x01\x0a")
        zf.writestr("o00407-0139200010010.rdv", b"\x30\x82\x01\x0b")
        zf.writestr("o00407-0139200010010.vscmr", b"\x30\x82\x01\x0c")
        zf.writestr("o00407-0139200010010.imgbu", b"BOLETIM DE URNA")
    return zip_path


@pytest.fixture()
def zip_totalizacao_without_jez(tmp_path: Path) -> Path:
    """Cria um pacote ZIP de totalização sem arquivo .jez (testando ausência explícita)."""
    zip_path = tmp_path / "bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o00407-0301800010001.bu", b"\x30\x82\x01\x0a")
        zf.writestr("o00407-0301800010001.rdv", b"\x30\x82\x01\x0b")
    return zip_path
