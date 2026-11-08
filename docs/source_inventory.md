# Inventário de Fontes Primárias do TSE (`source_inventory`)

Este documento consolida o inventário técnico, os links reais verificados no Portal de Dados Abertos (CKAN) e no CDN oficial do Tribunal Superior Eleitoral (TSE) para as **Eleições 2026**, os formatos físicos, os cabeçalhos reais inspecionados nos arquivos de 2026, o grão original (`native_grain`) e a matriz de governança de licenças, em sincronia estrita com `configs/sources.yml`.

---

## 1. Referências Oficiais e Páginas de Conjuntos de Dados (Verificadas)

1. **Log dos aplicativos do Ecossistema da Urna — Documentação Técnica (setembro de 2026):**  
   `https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/log-do-ecossistema/@@display-file/file/log-do-ecossistema.pdf`
2. **Resolução TSE nº 23.759, de 2 de março de 2026 (Procedimentos de identificação, biometria e votação):**  
   `https://www.tse.jus.br/legislacao/compilada/res/2026/resolucao-no-23-759-de-26-de-fevereiro-de-2026`
3. **Resultados 2026 — Arquivos transmitidos para totalização:**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-arquivos-transmitidos-para-totalizacao`
4. **Resultados 2026 — Boletim de Urna:**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/resultados-2026-boletim-de-urna`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-boletim-de-urna`
5. **Resultados 2026 (Apuração e Votação por Seção / Município-Zona):**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/resultados-2026`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026`
6. **Eleitorado 2026 (Perfil, Seção, Local de Votação, PCD e Transferência Temporária):**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/eleitorado-2026`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=eleitorado-2026`
7. **Comparecimento e Abstenção 2026 (Sistema ELO):**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/comparecimento-e-abstencao-2026`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=comparecimento-e-abstencao-2026`
8. **Correspondências esperadas e efetivadas — 1º turno de 2026:**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/resultados-2026-correspondencias-esperadas-e-efetivadas-1-turno`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-correspondencias-esperadas-e-efetivadas-1-turno`
9. **Correspondências esperadas e efetivadas — 2º turno de 2026:**  
   - Página CKAN: `https://dadosabertos.tse.jus.br/dataset/resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno`  
   - API CKAN: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno`

---

## 2. Catálogo das 7 Famílias de Fontes Primárias (`configs/sources.yml`)

| `source_id` | Título | `file_format` | Encoding / Delimitador | `native_grain` | `target_table` | Licença CKAN |
|---|---|---|---|---|---|---|
| `totalizacao_arquivos_transmitidos` | Arquivos Transmitidos para Totalização | `zip_bundle` (`.jez`, `.bu`, `.rdv`, `.vscmr`, `.imgbu`) | `latin1` / `\t` (em `logd.dat`) | `urna_transmission_package` | `fact_urna_logs` | `cc-by` (`redistribution_allowed: true`) |
| `ecossistema_urna_log_docs` | Log dos Aplicativos do Ecossistema da Urna — Documentação Técnica | `pdf_doc` (`.pdf`) | `utf-8` / `\t` | `urna_log_event` | `fact_urna_logs` | `open_documented` (`redistribution_allowed: true`) |
| `resultados_boletim_urna` | Resultados — Boletim de Urna (BU) por UF e Turno | `zip_csv` (`.csv`, `.pdf`, `.sha512`) | `latin1` / `;` | `bu_section_cargo_vote` | `fact_boletim_urna` | `cc-by` (`redistribution_allowed: true`) |
| `resultados_apuracao_secao` | Resultados — Detalhe da Apuração e Votação por Seção Eleitoral | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `section_turn` | `fact_votacao_secao` | `cc-by` (`redistribution_allowed: true`) |
| `eleitorado_perfil` | Eleitorado — Perfil por Seção, Local de Votação, PCD e Transferência Temporária | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `municipality_zone_profile` | `fact_eleitorado_perfil_secao` | `cc-by` (`redistribution_allowed: true`) |
| `comparecimento_abstencao` | Comparecimento e Abstenção (Sistema ELO) | `zip_csv` (`.csv`, `.pdf`) | `latin1` / `;` | `municipality_zone_profile` | `fact_comparecimento_abstencao` | Omissão no CKAN ("Nenhuma Licença Fornecida" — autorizado para o dataset público com schema 1:1, `redistribution_allowed: true`) |
| `correspondencias_esperadas_efetivadas` | Correspondências Esperadas e Efetivadas (1º e 2º Turnos por UF) | `zip_csv` (`.csv`, `.pdf`, `.sha512`) | `latin1` / `;` | `urna_correspondence_turn` | `bridge_correspondencia_efetivada` | `cc-by` (`redistribution_allowed: true`) |

---

## 3. URLs Físicas Reais Verificadas no CDN do TSE (`cdn.tse.jus.br`) — Eleições 2026

### 3.1. `totalizacao_arquivos_transmitidos` (`fact_urna_logs`)
- **URL direta verificada por UF e turno (`1t` e `2t`, 56 pacotes ZIP):**
  - Padrão: `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{election_year}/arqurnatot/bu_imgbu_logjez_rdv_vscmr_{election_year}_{turn}t_{uf}.zip`
  - Exemplo real verificado (1º turno AC, HTTP 200, 393.5 MB):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip`
  - Exemplo real verificado (2º turno AC, HTTP 200, 512.1 MB):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_2t_AC.zip`
- **Nomenclatura interna real dos arquivos por seção (inspecionada no pacote 2026):**
  - `o<pleito:5><uf:2><municipio:5><zona:4><secao:4>-log.jez` (ex.: `o03220ac0101500020088-log.jez`)
  - `o<pleito:5><uf:2><municipio:5><zona:4><secao:4>-bu.dat`
  - `o<pleito:5><uf:2><municipio:5><zona:4><secao:4>-rdv.dat`
  - `o<pleito:5><uf:2><municipio:5><zona:4><secao:4>-vota.vsc`
- **Regra de Filtragem:** Considera apenas arquivos na situação `"Totalizado"`.

### 3.2. `ecossistema_urna_log_docs`
- **URL oficial verificada:**  
  `https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/log-do-ecossistema/@@display-file/file/log-do-ecossistema.pdf`
- **Estrutura real da linha em `logd.dat` (6 colunas separadas por `\t`):**  
  `DD/MM/YYYY HH:MM:SS \t SEVERIDADE (INFO/ALERTA/ERRO) \t SERIAL_URNA \t APLICATIVO (LOGD/SCUE/VOTA/GAP/RED) \t MENSAGEM \t MAC_HEX_16`

### 3.3. `resultados_boletim_urna` (`fact_boletim_urna`)
- **Descoberta via API CKAN (pois os nomes físicos em `buweb/` carregam o timestamp `DDMMYYYYHHMM` de geração):**  
  `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-boletim-de-urna`
- **Exemplos reais verificados no CDN (HTTP 200):**
  - 1º Turno AC (ZIP + SHA-512):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_AC_051020261403.zip`  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_AC_051020261403.zip.sha512`
  - 2º Turno AC (ZIP + SHA-512):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_2t_AC_261020260742.zip`  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_2t_AC_261020260742.zip.sha512`
- **Cabeçalho real inspecionado (45 colunas):**  
  `DT_GERACAO;HH_GERACAO;ANO_ELEICAO;CD_TIPO_ELEICAO;NM_TIPO_ELEICAO;CD_PLEITO;DT_PLEITO;NR_TURNO;CD_ELEICAO;DS_ELEICAO;SG_UF;CD_MUNICIPIO;NM_MUNICIPIO;NR_ZONA;NR_SECAO;NR_LOCAL_VOTACAO;CD_CARGO_PERGUNTA;DS_CARGO_PERGUNTA;NR_PARTIDO;SG_PARTIDO;NM_PARTIDO;DT_BU_RECEBIDO;QT_APTOS;QT_COMPARECIMENTO;QT_ABSTENCOES;CD_TIPO_URNA;DS_TIPO_URNA;CD_TIPO_VOTAVEL;DS_TIPO_VOTAVEL;NR_VOTAVEL;NM_VOTAVEL;QT_VOTOS;NR_URNA_EFETIVADA;CD_CARGA_1_URNA_EFETIVADA;CD_CARGA_2_URNA_EFETIVADA;CD_FLASHCARD_URNA_EFETIVADA;DT_CARGA_URNA_EFETIVADA;DS_CARGO_PERGUNTA_SECAO;DS_SECOES_AGREGADAS;DT_ABERTURA;DT_ENCERRAMENTO;QT_ELEI_BIOM_SEM_HABILITACAO;DT_EMISSAO_BU;NR_JUNTA_APURADORA;NR_TURMA_APURADORA`

### 3.4. `resultados_apuracao_secao` (`resultados-2026`)
- **URLs diretas verificadas no CDN (HTTP 200):**
  1. **Votação por seção eleitoral (por UF + `BR` para Presidente):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_{uf}.zip`  
     (Ex.: `https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_AC.zip` e `votacao_secao_2026_BR.zip` — 26 colunas)
  2. **Detalhe da apuração por seção eleitoral (pacote nacional com CSVs por UF):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip` (37 colunas)
  3. **Votação nominal por município e zona (inclui dados completos de candidatos e situação):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2026.zip` (50 colunas)
  4. **Votação em partido por município e zona (inclui partidos, federações e coligações):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/votacao_partido_munzona_2026.zip` (38 colunas)
  5. **Detalhe da apuração por município e zona:**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_2026.zip` (47 colunas)

### 3.5. `eleitorado_perfil` (`eleitorado-2026`)
- **URLs diretas verificadas no CDN (HTTP 200):**
  1. **Perfil do eleitorado por seção eleitoral (por UF, incluindo `ZZ`):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_2026_{uf}.zip`  
     (Ex.: `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_secao/perfil_eleitor_secao_2026_AC.zip` — 30 colunas)
  2. **Perfil geral do eleitorado (por município/zona):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/perfil_eleitorado_2026.zip` (27 colunas)
  3. **Eleitorado por local de votação (inclui endereço, bairro, CEP, latitude e longitude da seção):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip` (41 colunas)
  4. **Perfil do eleitorado com deficiência:**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_deficiente/perfil_eleitor_deficiencia_2026.zip` (30 colunas)
  5. **Transferência temporária do eleitorado (município e seção):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_tte/transferencia_temporaria_2026.zip` (13 colunas)  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitor_tte/transf_temporaria_secao_2026.zip` (17 colunas)

### 3.6. `comparecimento_abstencao` (`comparecimento-e-abstencao-2026` — Sistema ELO)
- **URLs diretas verificadas no CDN (HTTP 200):**
  1. **Perfil de Comparecimento e Abstenção:**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_comparecimento_abstencao/perfil_comparecimento_abstencao_2026.zip` (45 colunas)
  2. **Comparecimento e Abstenção — Pessoas com deficiência:**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_comparecimento_abstencao_eleitor_deficiente/perfil_comparecimento_abstencao_eleitor_deficiente_2026.zip` (20 colunas)
  3. **Comparecimento e Abstenção — Transferência temporária (TTE):**  
     `https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_comparecimento_abstencao_eleitor_tte/perfil_comparecimento_abstencao_eleitor_tte_2026.zip` (25 colunas)
- **Observação de Licença:** Embora a página CKAN omita o campo `license_id` ("Nenhuma Licença Fornecida"), por decisão de projeto trata-se de omissão formal no portal para dados públicos abertos do TSE, sendo autorizado seu uso e incorporação 1:1 ao dataset público (`redistribution_allowed: true`).

### 3.7. `correspondencias_esperadas_efetivadas` (1º e 2º Turnos)
- **Descoberta via API CKAN (os arquivos em `correspesp/` e `correspefet/` possuem timestamp `DDMMYYYYHHMM` no nome):**
  - 1º Turno: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-correspondencias-esperadas-e-efetivadas-1-turno`
  - 2º Turno: `https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno`
- **Exemplos reais verificados no CDN (HTTP 200):**
  - Correspondência Esperada (`CESP`, 21 colunas + `.sha512`):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspesp/CESP_1t_AC_041020261259.zip`  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspesp/CESP_2t_AC_251020261345.zip`
  - Correspondência Efetivada (`CEFT`, 36 colunas + `.sha512`):  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspefet/CEFT_1t_AC_051020261049.zip`  
    `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/correspefet/CEFT_2t_AC_261020261201.zip`
