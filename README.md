# tse-eleicoes-dados — Dados eleitorais públicos do TSE

Produto de dados do Miolo Dados construído a partir de fontes públicas do Tribunal Superior Eleitoral (TSE), com foco inicial nas Eleições 2026 e possibilidade de expansão parametrizada para outros pleitos.

O projeto evolui de uma ingestão rastreável das fontes oficiais para uma arquitetura de dados em três camadas: **Bronze, Silver e Gold**. A arquitetura e os contratos estão descritos em [docs/data_architecture.md](docs/data_architecture.md).

## Arquitetura

| Camada | Responsabilidade | Situação |
|---|---|---|
| **Bronze** | Preservar dados das fontes oficiais, seu grão e proveniência, com ajustes técnicos/salvaguardas documentados. | Camada atualmente implementada, conforme o inventário e o dicionário. |
| **Silver** | Padronizar e interpretar dados, construir fatos derivados e dimensões conformadas com regras versionadas. | Evolução planejada. |
| **Gold** | Publicar indicadores, agregações e produtos analíticos orientados a perguntas. | Evolução planejada. |

A tabela Bronze `fact_urna_logs` representa registros físicos dos arquivos de log. Ela não deve ser confundida com `fact_urna_event`, que será uma interpretação estruturada desses registros, nem com `fact_voting_session`, que exigirá reconstrução de sessões a partir de eventos.

O status de implementação de cada tabela deve ser consultado no [dicionário de dados](docs/data_dictionary.md). Nomes mencionados em documentação ou no planejamento não significam, por si só, que a tabela já esteja publicada.

## Execução e publicação

**Toda a execução oficial do pipeline acontece no Kaggle.** Isso inclui ingestão/atualização da Bronze, transformações Silver, produtos Gold, validações, geração dos artefatos e publicação de versões do dataset.

- **GitHub:** versionamento de notebooks, código auxiliar, configurações, testes e documentação.
- **Kaggle:** ambiente oficial de execução, processamento, validação e publicação do dataset.
- **Consumidores:** leem as camadas publicadas; não implementam ETL. O TS-Zé é um desses consumidores.

Não existe etapa local ou em CI que produza os artefatos oficiais do dataset. Consulte [docs/data_architecture.md](docs/data_architecture.md) para os contratos e o fluxo operacional.

## Dataset no Kaggle

O identificador canônico para consumo e publicação é **`miolodados/tse-eleicoes-dados`**, alinhado ao nome deste repositório. O identificador legado `miolodados/tse-analises-eleicoes` será substituído de forma coordenada no processo de release. Novos notebooks, configurações, instruções e consumidores devem usar o identificador canônico.

## Fontes, atribuição e privacidade

As fontes utilizadas são dados públicos disponibilizados pelo TSE. O catálogo `configs/sources.yml` registra a situação de licença e a autorização de redistribuição por fonte; as entradas atualmente utilizadas estão marcadas com `redistribution_allowed: true`, inclusive Comparecimento e Abstenção do Sistema ELO.

A atribuição às fontes oficiais e a proveniência são preservadas. Salvaguardas de privacidade aplicáveis à ingestão, como mascaramento de identificadores em mensagens e omissão de campos de autenticação, são documentadas nos contratos correspondentes.

## Estrutura do repositório

```text
tse-eleicoes-dados/
├── configs/
│   └── sources.yml
├── docs/
│   ├── data_architecture.md
│   ├── source_inventory.md
│   └── data_dictionary.md
├── notebooks/
├── src/
└── tests/
```

## Ambiente de desenvolvimento

O ambiente local pode ser utilizado para editar e revisar código e documentação. Ele não substitui o Kaggle como ambiente oficial de processamento e publicação dos dados.

Utilizando `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

## Verificações de código

As verificações estáticas e os testes de código podem ser executados durante o desenvolvimento:

```bash
uv run ruff check .
uv run pytest -v
```
