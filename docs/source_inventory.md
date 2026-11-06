# Inventário de Fontes Primárias do TSE (`source_inventory`)

Este documento consolida o inventário técnico, os formatos físicos, os templates de URL parametrizáveis por `election_year` (foco inicial em **2026**, com suporte nativo a **2022** e **2024**), o grão original (`native_grain`) e a matriz de governança de licenças das 7 famílias de dados primários do Portal de Dados Abertos (CKAN) do Tribunal Superior Eleitoral (TSE), em sincronia estrita com `configs/sources.yml`.

---

## 1. Parametrização Transversal (`election_year`, `turn`, `uf`)

Todas as fontes catalogadas são parametrizadas por:
- `election_year`: Ano do pleito eleitoral (`2026` como padrão v1.0; `2022` e `2024` suportados para validação histórica e regressão).
- `turn`: Turno eleitoral (`1` ou `2`).
- `uf`: Sigla da Unidade Federativa (`AC`..`TO`, além de `BR` e `ZZ` para exterior quando aplicável).

Quando um recurso para determinado `election_year` (ex.: `2026` antes da publicação oficial pelo TSE), `turn` ou `uf` ainda não está publicado no CDN/CKAN do TSE (HTTP `404`), o inspetor registra explicitamente `availability_status = "UNAVAILABLE"` e valores `NULL`, **nunca** inferindo zero registros ou zero ocorrências.

---

## 2. Catálogo das 7 Famílias de Fontes Primárias

| `source_id` | Título | `file_format` | Encoding / Delimitador | `native_grain` | `target_table` | Regra de Filtro |
|---|---|---|---|---|---|---|
| `totalizacao_arquivos_transmitidos` | Arquivos Transmitidos para Totalização | `zip_bundle` (`.jez`, `.bu`, `.rdv`, `.vscmr`, `.imgbu`) | `latin1` / `null` | `urna_transmission_package` | `fact_urna_event` | `situacao: "Totalizado"` |
| `ecossistema_urna_log_docs` | Log dos Aplicativos do Ecossistema da Urna — Documentação Técnica | `pdf_doc` (`.pdf`) | `utf-8` / `\t` | `urna_log_event` | `fact_urna_event` | `allowlist_catalog: "configs/event_catalog.yml"` |
| `resultados_boletim_urna` | Resultados — Boletim de Urna (BU) por UF e Turno | `zip_csv` (`.csv`, `.pdf`, `.sha512`) | `latin1` / `;` | `bu_section_cargo_vote` | `fact_bu_record` | `situacao: "Totalizado"` |
| `resultados_apuracao_secao` | Resultados — Detalhe da Apuração e Votação por Seção Eleitoral | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `section_turn` | `fact_result_section` | `situacao: "Totalizado"` |
| `eleitorado_perfil` | Eleitorado — Perfil por Seção, Local de Votação, PCD e Transferência Temporária | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `municipality_zone_profile` | `fact_electorate_profile` | `{}` |
| `comparecimento_abstencao` | Comparecimento e Abstenção (Sistema ELO) | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `municipality_zone_profile` | `fact_turnout_profile` | `{}` |
| `correspondencias_esperadas_efetivadas` | Correspondências Esperadas e Efetivadas (1º e 2º Turnos por UF) | `zip_csv` (`.csv`, `.pdf`, `.sha512`) | `latin1` / `;` | `urna_correspondence_turn` | `bridge_urna_section` | `situacao: "Totalizado"` |

---

## 3. Detalhamento Técnico por Fonte

### 3.1. `totalizacao_arquivos_transmitidos`
- **Slug CKAN**: `resultados-{election_year}-arquivos-transmitidos-para-totalizacao`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{election_year}/arqtranstot/bu_imgbu_logjez_rdv_vscmr_{election_year}_{turn}t_{uf}.zip`
- **Artefatos Internos**: `.jez` (logs comprimidos SevenZip/LZMA contendo `logd.dat`), `.bu`, `.rdv`, `.vscmr`, `.imgbu`.
- **Grão Nativo**: `urna_transmission_package` (eventos internos em `urna_log_event`).
- **Tabela Alvo**: `fact_urna_event` (alimentando `fact_voting_session` e `agg_voting_session_metrics`).
- **Chaves Naturais**: `["election_year", "turn", "uf", "municipio_code", "zone_num", "section_num"]`.
- **Regra de Filtragem**: Exclusivamente pacotes com `situacao == "Totalizado"`.

### 3.2. `ecossistema_urna_log_docs`
- **Slug CKAN**: `ecossistema-da-urna-log-dos-aplicativos`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/odsele/log_urna/formato_arquivos_log_urna_{election_year}.pdf`
- **Grão Nativo**: `urna_log_event`.
- **Tabela Alvo**: `fact_urna_event`.
- **Chaves Naturais**: `["election_year", "turn", "uf", "municipio_code", "zone_num", "section_num", "urna_serial", "file_seq"]`.
- **Observações**: Define o layout tabulado das linhas de log (`raw_timestamp`, `log_level`, `urna_serial`, `application`, `message_text`, `mac_code`), regras de rotação de arquivo, contingência e eventos do aplicativo VOTA.

### 3.3. `resultados_boletim_urna`
- **Slug CKAN**: `resultados-{election_year}-boletim-de-urna`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{election_year}/buweb/bweb_{turn}t_{uf}_{election_year}.zip`
- **Grão Nativo**: `bu_section_cargo_vote`.
- **Tabela Alvo**: `fact_bu_record`.
- **Colunas Esperadas (Chaves Físicas)**: `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO_PERGUNTA`, `NR_VOTAVEL`, `QT_VOTOS`, `NR_URNA_EFETIVADA`.

### 3.4. `resultados_apuracao_secao`
- **Slug CKAN**: `resultados-{election_year}`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_{election_year}_{uf}.zip`
- **Grão Nativo**: `section_turn`.
- **Tabela Alvo**: `fact_result_section`.
- **Colunas Esperadas (Chaves Físicas)**: `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES`.

### 3.5. `eleitorado_perfil`
- **Slug CKAN**: `eleitorado-{election_year}`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_{election_year}_{uf}.zip`
- **Grão Nativo**: `municipality_zone_profile`.
- **Tabela Alvo**: `fact_electorate_profile`.
- **Colunas Esperadas (Chaves Físicas)**: `ANO_ELEICAO`, `SG_UF`, `CD_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_GENERO`, `CD_FAIXA_ETARIA`, `CD_GRAU_ESCOLARIDADE`, `QT_ELEITORES_PERFIL`, `QT_ELEITORES_BIOMETRIA`, `QT_ELEITORES_DEFICIENCIA`.

### 3.6. `comparecimento_abstencao` (Sistema ELO)
- **Slug CKAN**: `comparecimento-e-abstencao-{election_year}`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_comparecimento_abstencao/perfil_comparecimento_abstencao_{election_year}.zip`
- **Grão Nativo**: `municipality_zone_profile`.
- **Tabela Alvo**: `fact_turnout_profile`.
- **Colunas Esperadas (Chaves Físicas)**: `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NR_ZONA`, `CD_GENERO`, `CD_FAIXA_ETARIA`, `CD_GRAU_ESCOLARIDADE`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCAO`.
- **Restrição Crítica de Licença**: Veja Seção 4 abaixo.

### 3.7. `correspondencias_esperadas_efetivadas`
- **Slug CKAN**: `resultados-{election_year}-correspondencias-esperadas-e-efetivadas`
- **Template de URL**: `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{election_year}/corresp/corresp_{election_year}_{turn}t_{uf}.zip`
- **Grão Nativo**: `urna_correspondence_turn`.
- **Tabela Alvo**: `bridge_urna_section`.
- **Colunas Esperadas (Chaves Físicas)**: `ANO_ELEICAO`, `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `NR_URNA_ESPERADA`, `NR_URNA_EFETIVADA`, `CD_CARGA_1_URNA_ESPERADA`, `CD_CARGA_1_URNA_EFETIVADA`.

---

## 4. Matriz de Governança de Licenças e Trava de Redistribuição

| `source_id` | `license_status` | `redistribution_allowed` | Diretriz de Governança |
|---|---|---|---|
| `totalizacao_arquivos_transmitidos` | `open_documented` | `true` | Dados abertos do TSE; proibida publicação de texto livre bruto de log ou autenticadores. |
| `ecossistema_urna_log_docs` | `open_documented` | `true` | Documentação técnica pública do TSE. |
| `resultados_boletim_urna` | `open_documented` | `true` | Dados abertos do TSE (Boletim de Urna). |
| `resultados_apuracao_secao` | `open_documented` | `true` | Dados abertos do TSE (Resultados por Seção). |
| `eleitorado_perfil` | `open_documented` | `true` | Dados abertos agregados do TSE (Perfil do Eleitorado). |
| `comparecimento_abstencao` | `unspecified_no_license` | `false` | **BLOQUEIO ATIVO**: Página oficial do Sistema ELO declara `"Nenhuma Licença Fornecida"`. Proibido republicar ou redistribuir dado bruto. |
| `correspondencias_esperadas_efetivadas` | `open_documented` | `true` | Dados abertos do TSE (Correspondências Esperadas e Efetivadas). |

> **Aviso Importante sobre `comparecimento_abstencao` (Sistema ELO)**:
> A página oficial do conjunto de dados de Comparecimento e Abstenção no Portal de Dados Abertos do TSE declara explicitamente **"Nenhuma Licença Fornecida"** (`license_status: "unspecified_no_license"`). O módulo `tse_analysis.inventory.catalog` impõe `redistribution_allowed: false` e bloqueia programaticamente qualquer rotina de exportação ou redistribuição do dado bruto via `assert_redistribution_allowed()`, lançando `LicenseRestrictionError`.
