"""Testes unitários para o pipeline autocontido de ingestão das 17 tabelas eleitorais (Fase 1)."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tse_analysis.inventory.catalog import assert_redistribution_allowed, load_source_catalog


def _load_notebook_namespace(repo_root: Path) -> dict[str, Any]:
    """Carrega as definições declarativas e funções das células 1 a 3 do notebook 02."""
    nb_path = (
        repo_root
        / "notebooks"
        / "02_ingest_electoral_tables"
        / "02_ingest_electoral_tables.ipynb"
    )
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [c for c in nb_data["cells"] if c.get("cell_type") == "code"]
    namespace: dict[str, Any] = {}
    # Executa as 3 células de definição (catálogo, CKAN/SHA-512/ZIP e motor de ingestão/manifesto)
    for cell in code_cells[:3]:
        source_code = "".join(cell.get("source", []))
        exec(compile(source_code, str(nb_path), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def nb_ns(repo_root: Path) -> dict[str, Any]:
    return _load_notebook_namespace(repo_root)


def test_electoral_tables_catalog_17_tables_and_exact_column_counts(
    nb_ns: dict[str, Any],
) -> None:
    expected_all_ufs = [
        "AC",
        "AL",
        "AM",
        "AP",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MG",
        "MS",
        "MT",
        "PA",
        "PB",
        "PE",
        "PI",
        "PR",
        "RJ",
        "RN",
        "RO",
        "RR",
        "RS",
        "SC",
        "SE",
        "SP",
        "TO",
        "ZZ",
    ]
    assert nb_ns["ALL_UFS"] == expected_all_ufs
    assert len(nb_ns["ALL_UFS"]) == 28
    assert nb_ns["TARGET_UFS"] == expected_all_ufs
    assert len(nb_ns["TARGET_UFS"]) == 28

    catalog: dict[str, dict[str, Any]] = nb_ns["ELECTORAL_TABLES_CATALOG"]
    expected_counts = {
        "fact_boletim_urna": 45,
        "fact_votacao_secao": 26,
        "fact_detalhe_votacao_secao": 37,
        "fact_detalhe_votacao_munzona": 47,
        "dim_candidato_munzona": 50,
        "dim_partido_munzona": 38,
        "fact_eleitorado_perfil_secao": 30,
        "fact_eleitorado_perfil_munzona": 27,
        "dim_local_votacao_secao": 41,
        "fact_eleitorado_deficiencia": 30,
        "fact_transferencia_temporaria_secao": 17,
        "fact_transferencia_temporaria_mun": 13,
        "fact_comparecimento_abstencao": 45,
        "fact_comparecimento_abstencao_pcd": 20,
        "fact_comparecimento_abstencao_tte": 25,
        "bridge_correspondencia_esperada": 21,
        "bridge_correspondencia_efetivada": 36,
    }
    assert list(catalog.keys()) == list(expected_counts.keys())
    assert len(catalog) == 17

    forbidden_prefix = "bronze" + "_"
    for table_name, spec in catalog.items():
        assert not table_name.startswith(forbidden_prefix)
        assert spec["expected_cols"] == expected_counts[table_name]
        assert spec["partition_cols"] == ["election_year", "turn", "uf"]
        if spec["family"] in ("eleitorado", "correspondencias"):
            assert spec["year_col"] == "AA_ELEICAO"
        else:
            assert spec["year_col"] == "ANO_ELEICAO"


def test_verify_sha512_success_and_tamper_rejection(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    verify_sha512 = nb_ns["verify_sha512"]
    payload = b"PK\x03\x04conteudo-oficial-boletim-urna-2026-AC"
    expected_hex = hashlib.sha512(payload).hexdigest()

    zip_file = tmp_path / "bweb_1t_AC_051020261403.zip"
    zip_file.write_bytes(payload)
    sha_file = tmp_path / "bweb_1t_AC_051020261403.zip.sha512"
    sha_file.write_text(f"{expected_hex}  bweb_1t_AC_051020261403.zip\n", encoding="latin1")

    assert verify_sha512(payload, f"{expected_hex}  bweb_1t_AC_051020261403.zip\n") == expected_hex
    assert verify_sha512(zip_file, sha_file) == expected_hex

    tampered = payload + b"X"
    with pytest.raises(ValueError, match="SHA-512"):
        verify_sha512(tampered, sha_file)

    with pytest.raises(ValueError, match="inválido"):
        verify_sha512(payload, "hash_invalido_curto  arquivo.zip")


def test_select_csv_members_excludes_brasil_when_uf_files_exist(
    nb_ns: dict[str, Any],
) -> None:
    select_csv_members = nb_ns["select_csv_members"]
    members_with_brasil = [
        "leiame.pdf",
        "detalhe_votacao_secao_2026_AC.csv",
        "detalhe_votacao_secao_2026_SP.csv",
        "detalhe_votacao_secao_2026_BRASIL.csv",
    ]
    selected_ac = select_csv_members(members_with_brasil, target_ufs=["AC"])
    assert selected_ac == ["detalhe_votacao_secao_2026_AC.csv"]

    selected_all_ufs = select_csv_members(members_with_brasil, target_ufs=None)
    assert "detalhe_votacao_secao_2026_BRASIL.csv" not in selected_all_ufs
    assert selected_all_ufs == [
        "detalhe_votacao_secao_2026_AC.csv",
        "detalhe_votacao_secao_2026_SP.csv",
    ]

    # Quando há apenas um CSV nacional único sem sufixo de UF, preserva o membro único
    single_national = ["leiame.pdf", "transferencia_temporaria_2026.csv"]
    assert select_csv_members(single_national, target_ufs=["AC"]) == [
        "transferencia_temporaria_2026.csv"
    ]

    # Em pacotes CESP, prioriza csec_ (seção, 21 colunas) sobre ccont_ (contingência, 19 colunas)
    cesp_members = ["ccont_1t_AC_041020261259.csv", "csec_1t_AC_041020261259.csv"]
    assert select_csv_members(cesp_members, target_ufs=["AC"]) == [
        "csec_1t_AC_041020261259.csv"
    ]


def test_executed_notebook_outputs_contain_17_tables_head_tail_and_disk_sum(
    repo_root: Path, nb_ns: dict[str, Any]
) -> None:
    nb_path = (
        repo_root
        / "notebooks"
        / "02_ingest_electoral_tables"
        / "02_ingest_electoral_tables.ipynb"
    )
    nb_raw = nb_path.read_text(encoding="utf-8")
    nb_data = json.loads(nb_raw)

    # Garante ausência de prefixo proibido ou jargões internos em todo o notebook
    forbidden_prefix = "bronze" + "_"
    assert forbidden_prefix not in nb_raw
    assert "Decisão A1" not in nb_raw

    # Extrai exclusivamente o texto de stdout das células de código EFETIVAMENTE EXECUTADAS
    code_cells = [c for c in nb_data["cells"] if c.get("cell_type") == "code"]
    assert len(code_cells) >= 4
    for cell in code_cells:
        assert cell.get("execution_count") is not None, "Célula de código não executada!"

    executed_stdout = "".join(
        "".join(out.get("text", []))
        for cell in code_cells
        for out in cell.get("outputs", [])
        if out.get("output_type") == "stream" and out.get("name") == "stdout"
    )

    for table_name in nb_ns["ELECTORAL_TABLES_CATALOG"]:
        assert f"--- {table_name} : HEAD(5) ---" in executed_stdout
        assert f"--- {table_name} : TAIL(5) ---" in executed_stdout

    assert "RELATÓRIO DE ARMAZENAMENTO PARQUET ZSTD POR ARQUIVO GERADO" in executed_stdout

    # Valida que cada arquivo Parquet individual teve seu tamanho em bytes e KB/MB impresso
    file_regex = re.compile(
        r"^\d+\.\s+(data/exports/\S+\.parquet)\s+\|\s+rows=([\d,]+)\s+\|\s+cols=(\d+)\s+\|\s+"
        r"size=([\d,]+)\s+bytes\s+\(([\d.]+)\s+KB\s+/\s+([\d.]+)\s+MB\)$",
        re.MULTILINE,
    )
    matches = file_regex.findall(executed_stdout)
    assert len(matches) >= 17, f"Esperados >= 17 Parquets listados, encontrados {len(matches)}"

    individual_sizes = [int(m[3].replace(",", "")) for m in matches]
    assert all(sz > 0 for sz in individual_sizes)

    # Valida que a SOMA TOTAL EM DISCO impressa bate com a soma dos arquivos individuais
    sum_match = re.search(
        r"SOMA TOTAL EM DISCO \(\d+ arquivos Parquet ZSTD, 17 tabelas\):\s+"
        r"([\d,]+)\s+bytes\s+\(([\d,.]+)\s+KB\s+/\s+([\d.]+)\s+MB\)",
        executed_stdout,
    )
    assert sum_match is not None, "Linha de SOMA TOTAL EM DISCO não encontrada no output executado"
    printed_total_bytes = int(sum_match.group(1).replace(",", ""))
    assert printed_total_bytes == sum(individual_sizes)
    assert "Auditoria concluída com 100% de sucesso" in executed_stdout


def test_adversarial_corrupted_sha512_aborts_ingestion_and_cleans_staging(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Stress test: SHA-512 adulterado aborta escrita, não suja manifesto e limpa staging."""
    ingest_single_table = nb_ns["ingest_single_table"]
    load_manifest = nb_ns["load_manifest"]

    zip_path = tmp_path / "bweb_1t_AC_051020261403.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bweb_1t_AC_051020261403.csv", b'"ANO_ELEICAO";"SG_UF"\n2026;"AC"\n')
    zip_bytes = zip_path.read_bytes()
    real_sha512 = hashlib.sha512(zip_bytes).hexdigest()
    # Adultera o último caractere hexadecimal do digest SHA-512 oficial
    corrupted_char = "0" if real_sha512[-1] != "0" else "f"
    corrupted_sha512 = real_sha512[:-1] + corrupted_char
    corrupted_sha_payload = f"{corrupted_sha512}  bweb_1t_AC_051020261403.zip\n".encode("latin1")

    class _MockResp:
        def __init__(self, payload: bytes | dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            assert isinstance(self._payload, dict)
            return self._payload

        def __enter__(self) -> _MockResp:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def iter_bytes(self, chunk_size: int = 1024):
            assert isinstance(self._payload, bytes)
            yield self._payload

    class _TamperedCkanClient:
        def get(self, url: str, headers: dict[str, str] | None = None) -> _MockResp:
            return _MockResp(
                {
                    "success": True,
                    "result": {
                        "resources": [
                            {
                                "url": "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_AC_051020261403.zip"
                            }
                        ]
                    },
                }
            )

        def stream(self, method: str, url: str) -> _MockResp:
            if url.endswith(".sha512"):
                return _MockResp(corrupted_sha_payload)
            return _MockResp(zip_bytes)

        def close(self) -> None:
            pass

    nb_ns["_CKAN_CACHE"].clear()
    staging_dir = tmp_path / "staging_tampered"
    exports_dir = tmp_path / "exports_tampered"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    spec = dict(nb_ns["ELECTORAL_TABLES_CATALOG"]["fact_boletim_urna"])

    with pytest.raises(ValueError, match="Divergência criptográfica SHA-512"):
        ingest_single_table(
            table_name="fact_boletim_urna",
            spec=spec,
            election_year=2026,
            turns=[1],
            target_ufs=["AC"],
            staging_dir=staging_dir,
            exports_dir=exports_dir,
            manifest_path=manifest_path,
            skip_existing=True,
            force_refresh=False,
            stream_range_max_bytes=None,
            client=_TamperedCkanClient(),
        )

    assert list(staging_dir.glob("*")) == [], "Staging deve ser limpo mesmo após falha de SHA-512"
    assert list(exports_dir.rglob("*.parquet")) == [], (
        "Nenhum Parquet deve ser gravado com SHA-512 inválido"
    )
    assert list(exports_dir.rglob("*.tmp")) == [], "Nenhum arquivo .tmp órfão deve restar"
    manifest = load_manifest(manifest_path)
    assert manifest["partitions"] == {}


def test_csv_to_parquet_reconciliation_idempotency_and_storage_report(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    ingest_single_table = nb_ns["ingest_single_table"]
    compute_parquet_storage_report = nb_ns["compute_parquet_storage_report"]
    load_manifest = nb_ns["load_manifest"]

    # Monta um CSV sintético de 13 colunas para fact_transferencia_temporaria_mun
    cols = [
        "DT_GERACAO",
        "HH_GERACAO",
        "AA_ELEICAO",
        "NR_TURNO",
        "TP_TTE",
        "TP_ABRANGENCIA_TTE",
        "SG_UF_ORIGEM",
        "CD_MUNICIPIO_ORIGEM",
        "NM_MUNICIPIO_ORIGEM",
        "SG_UF_DESTINO",
        "CD_MUNICIPIO_DESTINO",
        "NM_MUNICIPIO_DESTINO",
        "QT_ELEITOR",
    ]
    rows = [
        (
            '"08/11/2026";"06:30:09";2026;1;"Voto em Trânsito";"Federal";'
            '"SP";"71072";"SÃO PAULO";"AC";"01392";"RIO BRANCO";4'
        ),
        (
            '"08/11/2026";"06:30:09";2026;1;"Voto em Trânsito";"Federal";'
            '"AM";"02550";"MANAUS";"AC";"01074";"CRUZEIRO DO SUL";2'
        ),
        (
            '"08/11/2026";"06:30:09";2026;2;"Voto em Trânsito";"Federal";'
            '"SP";"71072";"SÃO PAULO";"AC";"01392";"RIO BRANCO";3'
        ),
    ]
    csv_bytes = (";".join(f'"{c}"' for c in cols) + "\n" + "\n".join(rows) + "\n").encode("latin1")
    rr_row = (
        '"08/11/2026";"06:30:09";2026;1;"Voto em Trânsito";"Federal";'
        '"SP";"71072";"SÃO PAULO";"RR";"03018";"BOA VISTA";7'
    )
    rr_csv_bytes = (";".join(f'"{c}"' for c in cols) + "\n" + rr_row + "\n").encode("latin1")

    zip_path = tmp_path / "source_tte.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("transferencia_temporaria_2026_AC.csv", csv_bytes)
        zf.writestr("transferencia_temporaria_2026_RR.csv", rr_csv_bytes)
        # _BRASIL.csv com 20 linhas duplicadas para garantir que sua exclusão evita dupla contagem
        zf.writestr(
            "transferencia_temporaria_2026_BRASIL.csv",
            csv_bytes + (rows[0].encode("latin1") + b"\n") * 20,
        )

    class _MockStreamResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> _MockStreamResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self, chunk_size: int = 1024):
            yield self._data

    class _MockHttpClient:
        def __init__(self, zip_bytes: bytes) -> None:
            self.zip_bytes = zip_bytes
            self.download_calls = 0

        def stream(self, method: str, url: str) -> _MockStreamResponse:
            self.download_calls += 1
            return _MockStreamResponse(self.zip_bytes)

        def close(self) -> None:
            pass

    mock_client = _MockHttpClient(zip_path.read_bytes())
    staging_dir = tmp_path / "staging"
    exports_dir = tmp_path / "exports"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    spec = dict(nb_ns["ELECTORAL_TABLES_CATALOG"]["fact_transferencia_temporaria_mun"])

    summary_1 = ingest_single_table(
        table_name="fact_transferencia_temporaria_mun",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=mock_client,
    )

    assert summary_1["csv_row_count"] == 3
    assert summary_1["parquet_row_count"] == 3
    assert summary_1["column_count"] == 13
    assert summary_1["partitions_count"] == 2
    assert mock_client.download_calls == 1
    assert list(staging_dir.glob("*")) == []
    assert manifest_path.exists()

    manifest = load_manifest(manifest_path)
    assert len(manifest["partitions"]) == 2
    parquet_files_run1 = sorted(exports_dir.rglob("*.parquet"))
    mtimes_run1 = {p: p.stat().st_mtime_ns for p in parquet_files_run1}

    # Segunda execução idempotente (SKIP_EXISTING=True): não baixa nem reescreve Parquets
    summary_2 = ingest_single_table(
        table_name="fact_transferencia_temporaria_mun",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=mock_client,
    )
    assert mock_client.download_calls == 1
    assert summary_2["parquet_row_count"] == 3
    mtimes_run2 = {p: p.stat().st_mtime_ns for p in sorted(exports_dir.rglob("*.parquet"))}
    assert mtimes_run1 == mtimes_run2, "Parquets não devem ser reescritos quando skip_existing=True"

    # Terceira execução com target_ufs=["AC", "RR"]: preserva AC, adiciona RR e ignora _BRASIL.csv
    summary_3 = ingest_single_table(
        table_name="fact_transferencia_temporaria_mun",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC", "RR"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=mock_client,
    )
    assert mock_client.download_calls == 2
    assert summary_3["parquet_row_count"] == 4
    for p, mtime_ns in mtimes_run1.items():
        assert p.stat().st_mtime_ns == mtime_ns, "Partições de AC não devem ser reescritas"

    # Verifica cálculo de tamanho por arquivo Parquet ZSTD e soma total
    files_report, total_bytes = compute_parquet_storage_report(exports_dir)
    assert len(files_report) == 3
    assert total_bytes > 0
    assert total_bytes == sum(f["size_bytes"] for f in files_report)
    assert sum(f["row_count"] for f in files_report) == 4
    for f_info in files_report:
        assert f_info["column_count"] == 13
        assert f_info["size_bytes"] > 0
        assert pl.read_parquet(f_info["parquet_path"]).width == 13


def test_comparecimento_abstencao_license_policy_in_catalog(repo_root: Path) -> None:
    catalog = load_source_catalog(repo_root / "configs" / "sources.yml")
    entry = catalog.get("comparecimento_abstencao")
    assert entry.license_status == "open_documented"
    assert entry.redistribution_allowed is True
    assert_redistribution_allowed(entry)


def test_fact_votacao_secao_zz_maps_to_br_zip_url(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Garante que fact_votacao_secao usa votacao_secao_2026_BR.zip quando uf == 'ZZ'."""
    ingest_single_table = nb_ns["ingest_single_table"]
    spec = dict(nb_ns["ELECTORAL_TABLES_CATALOG"]["fact_votacao_secao"])
    cols = [
        "DT_GERACAO",
        "HH_GERACAO",
        "ANO_ELEICAO",
        "CD_TIPO_ELEICAO",
        "NM_TIPO_ELEICAO",
        "NR_TURNO",
        "CD_ELEICAO",
        "DS_ELEICAO",
        "DT_ELEICAO",
        "TP_ABRANGENCIA",
        "SG_UF",
        "SG_UE",
        "NM_UE",
        "CD_MUNICIPIO",
        "NM_MUNICIPIO",
        "NR_ZONA",
        "NR_SECAO",
        "CD_CARGO",
        "DS_CARGO",
        "NR_VOTAVEL",
        "NM_VOTAVEL",
        "QT_VOTOS",
        "NR_LOCAL_VOTACAO",
        "SQ_CANDIDATO",
        "NM_LOCAL_VOTACAO",
        "DS_LOCAL_VOTACAO_ENDERECO",
    ]
    row = ";".join(
        [
            '"05/10/2026"',
            '"14:00:00"',
            "2026",
            "2",
            '"Eleição Ordinária"',
            "1",
            "626",
            '"Eleição Presidencial 2026"',
            '"04/10/2026"',
            '"F"',
            '"ZZ"',
            '"ZZ"',
            '"EXTERIOR"',
            "99999",
            '"LISBOA"',
            "1",
            "10",
            "1",
            '"Presidente"',
            "13",
            '"CANDIDATO"',
            "120",
            "101",
            "280001",
            '"EMBAIXADA"',
            '"RUA X"',
        ]
    )
    csv_bytes = (";".join(f'"{c}"' for c in cols) + "\n" + row + "\n").encode("latin1")
    zip_path = tmp_path / "votacao_secao_2026_BR.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("votacao_secao_2026_BR.csv", csv_bytes)
    zip_payload = zip_path.read_bytes()

    requested_urls: list[str] = []

    class _MockStream:
        def __enter__(self) -> _MockStream:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self, chunk_size: int = 1024):
            yield zip_payload

    class _MockClient:
        def stream(self, method: str, url: str) -> _MockStream:
            requested_urls.append(url)
            return _MockStream()

        def close(self) -> None:
            pass

    staging_dir = tmp_path / "staging_zz"
    exports_dir = tmp_path / "exports_zz"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    summary = ingest_single_table(
        table_name="fact_votacao_secao",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["ZZ"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=_MockClient(),
    )
    assert len(requested_urls) == 1
    assert requested_urls[0].endswith("/votacao_secao_2026_BR.zip")
    assert summary["column_count"] == 26
    assert summary["parquet_row_count"] == 1
    assert summary["head_df"].height == 1
    assert summary["tail_df"].height == 1



def test_national_table_cache_requires_all_source_observed_turn_uf_pairs(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    get_pairs = nb_ns["get_national_source_pairs"]
    cache_complete = nb_ns["is_national_table_cache_complete"]
    table = "dim_partido_munzona"
    parquet_path = tmp_path / "part-0.parquet"
    parquet_path.write_bytes(b"fixture")

    manifest = {
        "source_coverage": {
            table: [
                {"turn": 1, "uf": "AC", "row_count": 10},
                {"turn": 2, "uf": "AC", "row_count": 2},
                {"turn": 1, "uf": "SP", "row_count": 20},
            ]
        },
        "partitions": {
            f"{table}/election_year=2026/turn=1/uf=AC": {
                "table_name": table, "election_year": 2026, "turn": 1,
                "uf": "AC", "status": "completed", "parquet_path": str(parquet_path),
            },
            f"{table}/election_year=2026/turn=1/uf=SP": {
                "table_name": table, "election_year": 2026, "turn": 1,
                "uf": "SP", "status": "completed", "parquet_path": str(parquet_path),
            },
        },
    }

    assert get_pairs(manifest, table) == {(1, "AC"), (2, "AC"), (1, "SP")}
    assert cache_complete(table, 2026, manifest, tmp_path, ["AC", "SP"], [1, 2]) is False

    manifest["partitions"][f"{table}/election_year=2026/turn=2/uf=AC"] = {
        "table_name": table, "election_year": 2026, "turn": 2,
        "uf": "AC", "status": "completed", "parquet_path": str(parquet_path),
    }
    assert cache_complete(table, 2026, manifest, tmp_path, ["AC", "SP"], [1, 2]) is True


def test_national_table_cache_rejects_legacy_manifest_without_source_coverage(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    assert nb_ns["is_national_table_cache_complete"](
        "dim_partido_munzona",
        2026,
        {"partitions": {}},
        tmp_path,
        ["AC", "SP"],
        [1, 2],
    ) is False
