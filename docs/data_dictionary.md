# Dicionário de Dados — Schemas 1:1 das Fontes Reais 2026 (`data_dictionary`)

Este documento descreve os contratos de dados das tabelas do projeto `tse-analysis` para as **Eleições 2026**.

Todas as tabelas refletem **fielmente o formato original da fonte (1:1)** em **Parquet ZSTD particionado** (`election_year=2026/turn={1,2}/uf={UF}`), com validação de integridade física (hashes `.sha512`, contagem exata de linhas e tipos nativos):
- **Logs da Urna (`fact_urna_logs`):** Preserva a estrutura tabulada original de `logd.dat` mantendo `message_text` (com números de identificação de mesário/eleitor de 5+ dígitos mascarados como `<ID_REDACTED>`) e omitindo o campo final de código de autenticação hexadecimal (`mac_code`), o que evita ~35 GB de entropia aleatória incompressível e permite altíssima compressão por dicionário em Parquet ZSTD para publicação no Kaggle.
- **Tabelas Tabulares e Dimensões:** Mantêm 100% dos arquivos e colunas originais dos CSVs de 2026 do TSE, aproveitando o *dictionary encoding* nativo do Parquet ZSTD para comprimir colunas descritivas repetidas sem perda de fidelidade à fonte.
- **Comparecimento e Abstenção (`fact_comparecimento_abstencao`):** Incorporada integralmente ao dataset público no schema 1:1 (`redistribution_allowed: true`), considerando a ausência de `license_id` no metadado CKAN como omissão formal do portal para dados públicos abertos do TSE.

---

## 1. Chaves Naturais de Contexto (`SECTION_TURN_KEY_SCHEMA`)

| Coluna Lógica | Coluna Original TSE | Tipo PyArrow / Polars | Descrição |
|---|---|---|---|
| `election_year` | `ANO_ELEICAO` / `AA_ELEICAO` | `int16` / `Int16` | Ano da eleição (`2026`). |
| `turn` | `NR_TURNO` | `int8` / `Int8` | Número do turno (`1` ou `2`). |
| `uf` | `SG_UF` | `string` / `String` | Sigla da Unidade Federativa (`AC`..`TO`, `BR`, `ZZ`). |
| `municipio_code` | `CD_MUNICIPIO` | `int32` / `Int32` | Código TSE do município (5 dígitos). |
| `zone_num` | `NR_ZONA` | `int16` / `Int16` | Número da zona eleitoral (4 dígitos). |
| `section_num` | `NR_SECAO` | `int32` / `Int32` | Número da seção eleitoral (4 dígitos). |

---

## 2. Tabelas Fato, Pontes e Dimensões (Schemas 1:1 Inferidos dos Arquivos Reais de 2026)

### 2.1. `fact_urna_logs`
- **Fonte Primária:** `totalizacao_arquivos_transmitidos` (`https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_{turn}t_{uf}.zip` $\rightarrow$ arquivos `o<pleito:5><uf:2><mun:5><zona:4><secao:4>-log.jez` $\rightarrow$ `logd.dat` e segmentos rotacionados) e `ecossistema_urna_log_docs` (`https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/log-do-ecossistema/@@display-file/file/log-do-ecossistema.pdf`).
- **Grão:** Linha física do arquivo de log da urna (`urna_log_event`), ordenada por `file_seq`.
- **Schema (`15 colunas`):**
  - `election_year` (`Int16`): Ano da eleição (`2026`).
  - `turn` (`Int8`): Turno (`1` ou `2`).
  - `uf` (`String`): UF (`AC`..`TO`, `ZZ`).
  - `cd_pleito` (`Int32`): Código do pleito extraído do nome do `.jez` (ex.: `3220` no 1º turno de 2026).
  - `cd_municipio` (`Int32`): Código TSE do município extraído do nome do `.jez` (ex.: `1015`).
  - `nr_zona` (`Int16`): Zona eleitoral extraída do nome do `.jez` (ex.: `2`).
  - `nr_secao` (`Int32`): Seção eleitoral extraída do nome do `.jez` (ex.: `88`).
  - `source_jez_file` (`String`): Nome do arquivo `.jez` de origem dentro do pacote da UF.
  - `source_log_member` (`String`): Membro interno do `.jez` (`logd.dat`, `logd.dat.1`, etc.).
  - `file_seq` (`Int64`): Número sequencial monotônico da linha dentro do arquivo `.jez` (`1..N`).
  - `raw_timestamp` (`Datetime("us")`): Data e hora registradas no 1º campo tabulado de `logd.dat` (`DD/MM/YYYY HH:MM:SS`).
  - `log_level` (`String`): Nível de severidade original do 2º campo tabulado (`INFO`, `ALERTA`, `ERRO`, `DEBUG`).
  - `urna_serial` (`String`): Número de série da urna do 3º campo tabulado (ex.: `"02263093"`).
  - `application` (`String`): Aplicativo emissor do 4º campo tabulado (`LOGD`, `SCUE`, `VOTA`, `GAP`, `RED`, etc.).
  - `message_text` (`String`): Mensagem original do 5º campo tabulado de `logd.dat` (com números de 5+ dígitos mascarados como `<ID_REDACTED>` para proteção de privacidade e máxima compressão por dicionário no Parquet ZSTD; o 6º campo `mac_code` é omitido na persistência para eliminar entropia hexadecimal aleatória).

### 2.2. `fact_boletim_urna`
- **Fonte Primária:** `resultados_boletim_urna` (`buweb/bweb_{turn}t_{uf}_<DDMMYYYYHHMM>.zip`, validado contra o respectivo `.sha512`).
- **Grão:** `bu_section_cargo_vote` (Seção $\times$ Turno $\times$ Cargo/Pergunta $\times$ Votável).
- **Schema 1:1 (45 colunas nativas do CSV de 2026):**
  `DT_GERACAO`, `HH_GERACAO`, `ANO_ELEICAO`, `CD_TIPO_ELEICAO`, `NM_TIPO_ELEICAO`, `CD_PLEITO`, `DT_PLEITO`, `NR_TURNO`, `CD_ELEICAO`, `DS_ELEICAO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `NR_LOCAL_VOTACAO`, `CD_CARGO_PERGUNTA`, `DS_CARGO_PERGUNTA`, `NR_PARTIDO`, `SG_PARTIDO`, `NM_PARTIDO`, `DT_BU_RECEBIDO`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES`, `CD_TIPO_URNA`, `DS_TIPO_URNA`, `CD_TIPO_VOTAVEL`, `DS_TIPO_VOTAVEL`, `NR_VOTAVEL`, `NM_VOTAVEL`, `QT_VOTOS`, `NR_URNA_EFETIVADA`, `CD_CARGA_1_URNA_EFETIVADA`, `CD_CARGA_2_URNA_EFETIVADA`, `CD_FLASHCARD_URNA_EFETIVADA`, `DT_CARGA_URNA_EFETIVADA`, `DS_CARGO_PERGUNTA_SECAO`, `DS_SECOES_AGREGADAS`, `DT_ABERTURA`, `DT_ENCERRAMENTO`, `QT_ELEI_BIOM_SEM_HABILITACAO`, `DT_EMISSAO_BU`, `NR_JUNTA_APURADORA`, `NR_TURMA_APURADORA`.

### 2.3. `fact_votacao_secao`, `fact_detalhe_votacao_secao`, `dim_candidato_munzona` e `dim_partido_munzona`
- **Fonte Primária:** `resultados_apuracao_secao` (`resultados-2026`).
- **Tabelas 1:1 dos CSVs de 2026:**
  1. `fact_votacao_secao` (`votacao_secao_2026_{uf}.zip`, 26 colunas): `DT_GERACAO`, `HH_GERACAO`, `ANO_ELEICAO`, `CD_TIPO_ELEICAO`, `NM_TIPO_ELEICAO`, `NR_TURNO`, `CD_ELEICAO`, `DS_ELEICAO`, `DT_ELEICAO`, `TP_ABRANGENCIA`, `SG_UF`, `SG_UE`, `NM_UE`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `DS_CARGO`, `NR_VOTAVEL`, `NM_VOTAVEL`, `QT_VOTOS`, `NR_LOCAL_VOTACAO`, `SQ_CANDIDATO`, `NM_LOCAL_VOTACAO`, `DS_LOCAL_VOTACAO_ENDERECO`.
  2. `fact_detalhe_votacao_secao` (`detalhe_votacao_secao_2026.zip`, 37 colunas): `DT_GERACAO`, `HH_GERACAO`, `ANO_ELEICAO`, `CD_TIPO_ELEICAO`, `NM_TIPO_ELEICAO`, `NR_TURNO`, `CD_ELEICAO`, `DS_ELEICAO`, `DT_ELEICAO`, `TP_ABRANGENCIA`, `SG_UF`, `SG_UE`, `NM_UE`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `DS_CARGO`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES`, `QT_VOTOS_NOMINAIS`, `QT_VOTOS_BRANCOS`, `QT_VOTOS_NULOS`, `QT_VOTOS_LEGENDA`, `QT_VOTOS_ANULADOS_APU_SEP`, `NR_LOCAL_VOTACAO`, `NM_LOCAL_VOTACAO`, `DS_LOCAL_VOTACAO_ENDERECO`, `DT_RECEBIMENTO_BU_HOR_TSE`, `DT_PRIM_TOT_PARCIAL_HOR_TSE`, `DS_ORIGEM_VOTO`, `ST_SECAO_INSTALADA`, `ST_SECAO_ANULADA`, `CD_MODELO_URNA`, `DS_MODELO_URNA`.
  3. `fact_detalhe_votacao_munzona` (`detalhe_votacao_munzona_2026.zip`, 47 colunas).
  4. `dim_candidato_munzona` (`votacao_candidato_munzona_2026.zip`, 50 colunas) e `dim_partido_munzona` (`votacao_partido_munzona_2026.zip`, 38 colunas).

### 2.4. `fact_eleitorado_perfil_secao`, `dim_local_votacao_secao`, `fact_eleitorado_deficiencia` e `fact_transferencia_temporaria_secao`
- **Fonte Primária:** `eleitorado_perfil` (`eleitorado-2026`).
- **Tabelas 1:1 dos CSVs de 2026:**
  1. `fact_eleitorado_perfil_secao` (`perfil_eleitor_secao_2026_{uf}.zip`, 30 colunas): `DT_GERACAO`, `HH_GERACAO`, `AA_ELEICAO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `NR_LOCAL_VOTACAO`, `NM_LOCAL_VOTACAO`, `CD_GENERO`, `DS_GENERO`, `CD_ESTADO_CIVIL`, `DS_ESTADO_CIVIL`, `CD_FAIXA_ETARIA`, `DS_FAIXA_ETARIA`, `CD_GRAU_ESCOLARIDADE`, `DS_GRAU_ESCOLARIDADE`, `CD_RACA_COR`, `DS_RACA_COR`, `CD_IDENTIDADE_GENERO`, `DS_IDENTIDADE_GENERO`, `CD_QUILOMBOLA`, `DS_QUILOMBOLA`, `CD_INTERPRETE_LIBRAS`, `DS_INTERPRETE_LIBRAS`, `QT_ELEITORES`, `QT_ELEITORES_BIOMETRIA`, `QT_ELEITORES_DEFICIENCIA`, `QT_ELEITORES_NOME_SOCIAL`.
  2. `fact_eleitorado_perfil_munzona` (`perfil_eleitorado_2026.zip`, 27 colunas).
  3. `dim_local_votacao_secao` (`eleitorado_local_votacao_2026.zip`, 41 colunas): cadastro geográfico completo de seções e locais de votação (`DS_ENDERECO`, `NM_BAIRRO`, `NR_CEP`, `NR_LATITUDE`, `NR_LONGITUDE`, `CD_TIPO_SECAO_AGREGADA`, `NR_SECAO_PRINCIPAL`, `QT_ELEITOR_SECAO`, etc.).
  4. `fact_eleitorado_deficiencia` (`perfil_eleitor_deficiencia_2026.zip`, 30 colunas) e `fact_transferencia_temporaria_secao` (`transf_temporaria_secao_2026.zip`, 17 colunas) / `fact_transferencia_temporaria_mun` (`transferencia_temporaria_2026.zip`, 13 colunas).

### 2.5. `fact_comparecimento_abstencao`, `fact_comparecimento_abstencao_pcd` e `fact_comparecimento_abstencao_tte`
- **Fonte Primária:** `comparecimento_abstencao` (`comparecimento-e-abstencao-2026` — Sistema ELO, incorporado ao dataset público com schema 1:1).
- **Tabelas 1:1 dos CSVs de 2026:**
  1. `fact_comparecimento_abstencao` (`perfil_comparecimento_abstencao_2026.zip`, 45 colunas): `DT_GERACAO`, `HH_GERACAO`, `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `CD_GENERO`, `DS_GENERO`, `CD_ESTADO_CIVIL`, `DS_ESTADO_CIVIL`, `CD_FAIXA_ETARIA`, `DS_FAIXA_ETARIA`, `CD_GRAU_INSTRUCAO`, `DS_GRAU_INSTRUCAO`, `CD_COR_RACA`, `DS_COR_RACA`, `CD_QUILOMBOLA`, `DS_QUILOMBOLA`, `CD_INTERPRETE_LIBRAS`, `DS_INTERPRETE_LIBRAS`, `CD_IDENTIDADE_GENERO`, `DS_IDENTIDADE_GENERO`, `CD_IDIOMA_INDIGENA`, `DS_IDIOMA_INDIGENA`, `CD_GRUPO_INDIGENA`, `DS_GRUPO_INDIGENA`, `CD_IDIOMA_QUILOMBOLA`, `DS_IDIOMA_QUILOMBOLA`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCAO`, `QT_COMPARECIMENTO_DEFICIENCIA`, `QT_ABSTENCAO_DEFICIENCIA`, `QT_COMPARECIMENTO_TTE`, `QT_ABSTENCAO_TTE`, `QT_COMPAREC_FACULTATIVO`, `QT_ABST_FACULTATIVO`, `QT_COMPAREC_OBRIGATORIO`, `QT_ABST_OBRIGATORIO`, `QT_COMPAREC_DEFIC_FACULTATIVO`, `QT_ABST_DEFIC_FACULTATIVO`, `QT_COMPAREC_DEFIC_OBRIGATORIO`, `QT_ABST_DEFIC_OBRIGATORIO`.
  2. `fact_comparecimento_abstencao_pcd` (`perfil_comparecimento_abstencao_eleitor_deficiente_2026.zip`, 20 colunas).
  3. `fact_comparecimento_abstencao_tte` (`perfil_comparecimento_abstencao_eleitor_tte_2026.zip`, 25 colunas).

### 2.6. `bridge_correspondencia_esperada` e `bridge_correspondencia_efetivada`
- **Fonte Primária:** `correspondencias_esperadas_efetivadas` (1º e 2º turnos, validado contra `.sha512`).
- **Tabelas 1:1 dos CSVs de 2026:**
  1. `bridge_correspondencia_esperada` (`correspesp/CESP_{turn}t_{uf}_<DDMMYYYYHHMM>.zip`, 21 colunas): `DT_GERACAO`, `HH_GERACAO`, `AA_ELEICAO`, `CD_PLEITO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `NR_LOCAL_VOTACAO`, `NR_URNA_ESPERADA`, `CD_CARGA_URNA_ESPERADA`, `CD_FLASHCARD_URNA_ESPERADA`, `DT_CARGA_URNA_ESPERADA`, `ST_CORRESP_ALTERADA`, `NM_MAQUINA_GERACAO_MIDIA`, `NR_SRI_TPM_GERACAO_MIDIA`, `NR_SRI_INSTAL_GERACAO_MIDIA`, `NM_MAQUINA_TRANSM_CORRESP`, `NR_SRI_TPM_TRANSM_CORRESP`, `NR_SRI_INSTAL_TRANSM_CORRESP`.
  2. `bridge_correspondencia_efetivada` (`correspefet/CEFT_{turn}t_{uf}_<DDMMYYYYHHMM>.zip`, 36 colunas): `DT_GERACAO` .. `AA_ELEICAO`, `DT_PLEITO`, `CD_PLEITO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `NR_LOCAL_VOTACAO`, `SQ_CORRESPONDENCIA_ESPERADA`, `NR_URNA_ESPERADA`, `CD_CARGA_URNA_ESPERADA`, `CD_CARGA_1_URNA_ESPERADA`, `CD_CARGA_2_URNA_ESPERADA`, `CD_FLASHCARD_URNA_ESPERADA`, `DT_CARGA_URNA_ESPERADA`, `DT_RECBTO_URNA_ESPERADA`, `SQ_CORRESPONDENCIA_EFETIVADA`, `NR_URNA_EFETIVADA`, `CD_CARGA_URNA_EFETIVADA`, `CD_CARGA_1_URNA_EFETIVADA`, `CD_CARGA_2_URNA_EFETIVADA`, `CD_FLASHCARD_URNA_EFETIVADA`, `DT_CARGA_URNA_EFETIVADA`, `DT_RECBTO_URNA_EFETIVADA`, `CD_ORIGEM_VOTO`, `DS_ORIGEM_VOTO`, `TP_DIVERGENCIA`, etc.

---

## 3. Política de Armazenamento Parquet e Particionamento

- **Formato Físico:** Apache Parquet com compressão **ZSTD** (nível 5).
- **Particionamento Permitido (`ALLOWED_PARTITION_KEYS`):** Exclusivamente `("election_year", "turn", "uf")` ou `("turn", "uf")`.
- **Particionamento Proibido (`FORBIDDEN_PARTITION_KEYS`):** É proibido particionar por `section_num`, `urna_serial`, `municipio_code` ou `raw_timestamp`.
