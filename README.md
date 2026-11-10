# tse-eleicoes-analises — Análise do Comportamento Eleitoral (Dados Públicos do TSE)

Base analítica reproduzível em Parquet sobre o comportamento eleitoral brasileiro a partir dos dados públicos do Portal de Dados Abertos do TSE, com foco inicial nas **Eleições 2026** e arquitetura parametrizável por `election_year` para expansão a pleitos anteriores (`2022`, `2024`).

## Visão Geral e Arquitetura

O projeto adota uma estrutura modular em Python 3.11+ fundamentada em **Polars**, **PyArrow**, **DuckDB** e **Plotly**:

- **Unidade Central de Análise**: `section_turn` (`election_year`, `turn`, `uf`, `municipio_code`, `zone_num`, `section_num`).
- **Camada Granular de Urna**: Eventos brutos de log (`fact_urna_event`), sessões de votação reconstruídas via máquina de estados (`fact_voting_session`) e métricas agregadas (`agg_voting_session_metrics`).
- **Camada Eleitoral e Demográfica**: Boletim de Urna (`fact_bu_record`), apuração por seção (`fact_result_section`), perfil do eleitorado (`fact_electorate_profile`), comparecimento/abstenção (`fact_turnout_profile`) e correspondências (`bridge_urna_section`).
- **Governança de Licenças e Privacidade**: Rastreamento explícito de licença por fonte em `configs/sources.yml` (incluindo trava programática `redistribution_allowed: false` para dados brutos de Comparecimento e Abstenção do Sistema ELO) e minimização estrita (zero retenção de CPF, título eleitoral, texto livre bruto ou autenticadores).

## Estrutura do Repositório

```text
tse-analysis/
├── configs/
│   └── sources.yml              # Catálogo declarativo das 7 famílias de fontes do TSE
├── docs/
│   ├── source_inventory.md      # Inventário detalhado de fontes, formatos e licenças
│   └── data_dictionary.md       # Dicionário de dados, chaves section_turn e schemas Parquet
├── notebooks/                   # Notebooks analíticos e exploratórios
├── src/
│   └── tse_analysis/
│       ├── config.py            # Configuração de execução (election_year, turn, uf, partições)
│       └── inventory/           # Catálogo, inspetor em streaming (ZIP/CSV) e relatórios
└── tests/                       # Suíte de testes unitários com fixtures sintéticas
```

## Configuração do Ambiente

Utilizando `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

## Verificação de Qualidade e Testes

```bash
uv run ruff check .
uv run pytest -v
```
