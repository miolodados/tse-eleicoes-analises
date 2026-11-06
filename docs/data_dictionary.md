# Dicionário de Dados e Contratos Analíticos (`data_dictionary`)

Este documento descreve a unidade central de análise (`section_turn`), os contratos de tipos em PyArrow/Polars, os schemas preliminares das tabelas analíticas e dimensões do projeto `tse-analysis`, a política de armazenamento Parquet ZSTD e os guardrails obrigatórios de privacidade e minimização.

---

## 1. Unidade Central de Análise (`section_turn`)

A unidade central de integração entre resultados eleitorais, perfil do eleitorado, correspondências de urna e métricas agregadas de sessão é a **seção eleitoral por turno** (`section_turn`), parametrizada por `election_year` (padrão `2026`, suportando `2022` e `2024`).

### Contrato Canônico de Chaves (`SECTION_TURN_KEY_SCHEMA`)

| Coluna | Tipo PyArrow / Polars | Nulabilidade | Origem Física TSE | Descrição |
|---|---|---|---|---|
| `election_year` | `int16` / `Int16` | `NOT NULL` | `ANO_ELEICAO` | Ano da eleição (`2026`, `2024`, `2022`). |
| `turn` | `int8` / `Int8` | `NOT NULL` | `NR_TURNO` | Número do turno (`1` ou `2`). |
| `uf` | `string` / `String` | `NOT NULL` | `SG_UF` | Sigla da Unidade Federativa (`AC`..`TO`, `BR`, `ZZ`). |
| `municipio_code` | `int32` / `Int32` | `NOT NULL` | `CD_MUNICIPIO` | Código TSE do município. |
| `zone_num` | `int16` / `Int16` | `NOT NULL` | `NR_ZONA` | Número da zona eleitoral. |
| `section_num` | `int32` / `Int32` | `NOT NULL` | `NR_SECAO` | Número da seção eleitoral. |

---

## 2. Tabelas Fato e Agregadas (Modelo Analítico)

### 2.1. `fact_urna_event`
- **Fonte Primária**: `totalizacao_arquivos_transmitidos` e `ecossistema_urna_log_docs`.
- **Grão**: Evento técnico de log da urna (`urna_log_event`), preservando `file_seq` como ordem canônica de gravação.
- **Colunas Principais**:
  - `election_year` (`Int16`), `turn` (`Int8`), `uf` (`String`), `municipio_code` (`Int32`), `zone_num` (`Int16`), `section_num` (`Int32`)
  - `urna_serial` (`String`): Número de série da urna eletrônica.
  - `file_seq` (`Int64`): Sequencial monotônico de linha dentro do arquivo de log (ordem canônica).
  - `raw_timestamp` (`Datetime`): Timestamp registrado na linha de log.
  - `has_timestamp_regression` (`Boolean`): Indicador de regressão temporal em relação ao `file_seq` anterior.
  - `application` (`String`): Aplicativo emissor do evento (ex.: `VOTA`, `GAP`, `RED`).
  - `log_level` (`String`): Nível de severidade do evento (`INFO`, `WARN`, `ERRO`).
  - `event_code` (`String`): Código padronizado na allowlist (`configs/event_catalog.yml`) ou `UNKNOWN_EVENT`.

### 2.2. `fact_voting_session`
- **Fonte Derivada**: Reconstruída via máquina de estados sobre `fact_urna_event` (Fase 2).
- **Grão**: Sessão individual de votação (`Eleitor foi habilitado` $\rightarrow$ `O voto do eleitor foi computado`).
- **Colunas Principais**:
  - Chaves de `section_turn` + `urna_serial` (`String`) + `session_seq` (`Int32`)
  - `start_file_seq` (`Int64`), `end_file_seq` (`Int64`)
  - `start_timestamp` (`Datetime`), `end_timestamp` (`Datetime`), `duration_seconds` (`Float64`)
  - `auth_modality` (`String`): Classificação em `biometric_recognized`, `no_biometric_registered`, `biometric_not_recognized_manual_path` ou `unknown`.
  - `biometric_attempts` (`Int8`): Contagem de tentativas biométricas na sessão.
  - `session_status` (`String`): Status de fechamento da sessão técnica (`COMPLETED`, `INTERRUPTED`, `CONTINGENCY`).

### 2.3. `agg_voting_session_metrics`
- **Fonte Derivada**: Agregação de `fact_voting_session` (Fase 4).
- **Grão**: `urna_serial` $\times$ `section_turn` $\times$ `auth_modality` $\times$ `time_window_15m`.
- **Colunas Principais**:
  - Chaves de `section_turn`, `urna_serial` (`String`), `auth_modality` (`String`), `time_window_start` (`Datetime`)
  - `session_count` (`Int32`), `duration_mean_sec` (`Float64`), `duration_p50_sec` (`Float64`), `duration_p90_sec` (`Float64`).

### 2.4. `fact_bu_record`
- **Fonte Primária**: `resultados_boletim_urna`.
- **Grão**: `bu_section_cargo_vote` (Seção $\times$ Turno $\times$ Cargo $\times$ Votável no Boletim de Urna).
- **Colunas Principais**:
  - Chaves de `section_turn`, `urna_serial_effective` (`String`), `cargo_code` (`Int16`), `votavel_num` (`Int32`), `vote_count` (`Int32`).

### 2.5. `fact_result_section`
- **Fonte Primária**: `resultados_apuracao_secao`.
- **Grão**: `section_turn` $\times$ `cargo_code`.
- **Colunas Principais**:
  - Chaves de `section_turn`, `cargo_code` (`Int16`), `eligible_voters_count` (`Int32`), `turnout_count` (`Int32`), `abstention_count` (`Int32`), `nominal_votes_count` (`Int32`), `blank_votes_count` (`Int32`), `null_votes_count` (`Int32`).

### 2.6. `fact_electorate_profile`
- **Fonte Primária**: `eleitorado_perfil`.
- **Grão**: `municipality_zone_profile` (Seção/Zona $\times$ Faixa Etária $\times$ Gênero $\times$ Escolaridade).
- **Colunas Principais**:
  - `election_year` (`Int16`), `uf` (`String`), `municipio_code` (`Int32`), `zone_num` (`Int16`), `section_num` (`Int32`), `gender_code` (`Int8`), `age_group_code` (`Int16`), `education_level_code` (`Int8`), `voters_profile_count` (`Int32`), `biometric_voters_count` (`Int32`), `pcd_voters_count` (`Int32`).

### 2.7. `fact_turnout_profile`
- **Fonte Primária**: `comparecimento_abstencao` (Sistema ELO — sujeito a `redistribution_allowed: false` para dado bruto).
- **Grão**: `municipality_zone_profile` por turno.
- **Colunas Principais**:
  - `election_year` (`Int16`), `turn` (`Int8`), `uf` (`String`), `municipio_code` (`Int32`), `zone_num` (`Int16`), `gender_code` (`Int8`), `age_group_code` (`Int16`), `education_level_code` (`Int8`), `eligible_count` (`Int32`), `turnout_count` (`Int32`), `abstention_count` (`Int32`).

### 2.8. `bridge_urna_section`
- **Fonte Primária**: `correspondencias_esperadas_efetivadas`.
- **Grão**: `urna_correspondence_turn` (Seção $\times$ Turno $\times$ Urna Esperada vs. Efetivada).
- **Colunas Principais**:
  - Chaves de `section_turn`, `urna_serial_expected` (`String`), `urna_serial_effective` (`String`), `carga_code_expected` (`String`), `carga_code_effective` (`String`), `is_contingency_replacement` (`Boolean`).

---

## 3. Tabelas de Dimensão (`Dimensions`)

- `dim_geography`: Hierarquia geográfica da Justiça Eleitoral (`uf`, `municipio_code`, `municipio_name`, `regiao`).
- `dim_section`: Cadastro de zonas, seções e locais de votação (`election_year`, `uf`, `municipio_code`, `zone_num`, `section_num`, `local_votacao_num`, `is_aggregated_section`).
- `dim_time`: Janelas temporais do dia da eleição (`time_window_15m`, `hour_of_day`, `period_of_day`).
- `dim_candidate`: Candidaturas e cargos por pleito (`election_year`, `turn`, `uf`, `cargo_code`, `votavel_num`, `party_num`).
- `dim_party`: Partidos políticos, federações e coligações (`election_year`, `party_num`, `party_sigla`, `federation_num`).

---

## 4. Política de Armazenamento Parquet e Particionamento

- **Formato Físico**: Apache Parquet com compressão **ZSTD** (nível 5 inicial, avaliado contra Snappy na Fase 5).
- **Particionamento Permitido (`ALLOWED_PARTITION_KEYS`)**: Exclusivamente `("election_year", "turn", "uf")` ou `("turn", "uf")`.
- **Particionamento Proibido (`FORBIDDEN_PARTITION_KEYS`)**: É estritamente proibido particionar por `section_num`, `urna_serial`, `municipio_code` ou `raw_timestamp`, prevenindo explosão de pequenos arquivos (small-files problem) e riscos de reidentificação indireta.

---

## 5. Guardrails de Privacidade, Minimização e Qualidade

1. **Zero PII e Zero Texto Livre**: NUNCA reter, persistir ou publicar CPF, título de eleitor, códigos de identificação de mesários, autenticadores de linha (`mac_code`) ou mensagens de log em texto livre fora da allowlist (`configs/event_catalog.yml`). Eventos não mapeados recebem `event_code = "UNKNOWN_EVENT"`.
2. **Semântica de Ausência**: A ausência física de arquivo `.jez`, pacote ZIP ou correspondência é representada como `NULL` e `availability_status = "UNAVAILABLE"` — jamais como `0` ocorrências.
3. **Ordem Canônica**: Em logs de urna, `file_seq` é a ordem canônica de gravação; oscilações de relógio em `raw_timestamp` são sinalizadas via `has_timestamp_regression = True` sem reordenar os eventos.
