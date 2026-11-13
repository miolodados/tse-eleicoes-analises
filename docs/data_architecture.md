# Arquitetura de dados: Bronze, Silver e Gold

## 1. Objetivo e escopo

Este documento define a arquitetura lógica e operacional do produto de dados eleitorais do Miolo Dados. A arquitetura separa preservação de fontes, interpretação/estruturação e produtos analíticos em três camadas: Bronze, Silver e Gold.

A implementação atual é predominantemente uma ingestão 1:1 das fontes oficiais. Portanto, a existência de tabelas no catálogo ou em documentação histórica não significa que elas já estejam implementadas como fatos analíticos derivados. O status de cada tabela deve ser explicitado no dicionário de dados.

## 2. Princípios arquiteturais

1. **Fidelidade e proveniência:** toda informação publicada deve ter origem identificável e linhagem documentada.
2. **Separação de responsabilidades:** ingestão, interpretação e agregação não devem ser misturadas.
3. **Transformações explícitas:** regras semânticas são código/documentação versionados, nunca alterações silenciosas na Bronze.
4. **Reprodutibilidade:** parâmetros, fontes, código, regras e versões de entrada/saída devem ser registrados.
5. **Abstenção diante de incerteza:** registros ambíguos ou sem correspondência não devem receber classificações ou associações arbitrárias.
6. **Consumo desacoplado:** consumidores, incluindo o TS-Zé, leem as tabelas publicadas e não implementam o pipeline de transformação.
7. **Execução integral no Kaggle:** toda execução que produza ou valide artefatos oficiais do dataset acontece no ambiente Kaggle.

## 3. Camadas

### 3.1 Bronze — representação das fontes

**Responsabilidade:** armazenar dados provenientes das fontes oficiais preservando, tanto quanto possível, estrutura, conteúdo e grão nativos.

Inclui:
- ingestão e conversão técnica para formatos de armazenamento, como Parquet;
- metadados de fonte, arquivo, data de extração, parâmetros e execução;
- validações físicas, como schema, contagem de registros e hashes quando fornecidos pela fonte;
- salvaguardas documentadas de privacidade e segurança.

A Bronze não deve:
- classificar semanticamente eventos;
- reconstruir sessões ou processos;
- conformar entidades entre fontes;
- calcular indicadores analíticos.

A expressão 1:1 descreve a intenção de preservar o grão e o conteúdo da fonte, não uma promessa de cópia byte a byte. Qualquer mascaramento, omissão de campo ou ajuste técnico deve ser explicitado no contrato da tabela.

**Exemplo atual:** `fact_urna_logs`, cuja linha representa um registro físico de log conforme o contrato documentado.

### 3.2 Silver — dados estruturados e interpretados

**Responsabilidade:** transformar dados Bronze em estruturas consistentes, com semântica explícita, relacionamentos e regras versionadas.

Pode incluir:
- normalização de tipos e identificadores;
- fatos derivados e dimensões conformadas;
- interpretação de mensagens e códigos;
- reconstrução de processos a partir de sequências de registros;
- resolução documentada de duplicidades e inconsistências.

Toda tabela Silver deve documentar:
- grão;
- fontes Bronze utilizadas;
- regras de transformação e versão;
- chaves e relacionamentos;
- tratamento de ausências, ambiguidades e registros não classificados;
- limitações conhecidas.

**Exemplos planejados:** `fact_urna_event`, derivada de `fact_urna_logs), e `fact_voting_session`, reconstruída a partir dos eventos interpretados. Esses nomes representam entregas planejadas até que sejam efetivamente implementadas e publicadas.

Uma sessão reconstruída é uma interpretação dos registros disponíveis, não um fato diretamente observado. Métricas temporais devem descrever exatamente o intervalo observado e não ser apresentadas como duração total de votação ou atendimento sem evidência.

### 3.3 Gold — produtos analíticos

**Responsabilidade:** publicar tabelas e views orientadas a perguntas, indicadores e consumo recorrente.

Pode incluir:
- agregações por dimensões e períodos;
- indicadores com numeradores, denominadores e filtros formalizados;
- tabelas de cobertura e qualidade;
- produtos analíticos especializados.

Toda tabela Gold deve documentar pergunta atendida, grão, definição das métricas, filtros, tratamento de valores ausentes, testes e limitações. Gold deve derivar das estruturas Silver publicadas, evitando reimplementar transformações semânticas diretamente sobre fontes Bronze.

## 4. Contratos e nomenclatura

- Os nomes físicos das tabelas devem ser estáveis, em snake_case, e refletir a entidade ou produto representado.
- Prefixos como `fact_`, `dim_`, `bridge_` e `agg_` indicam o papel lógico, mas não substituem a documentação do grão.
- O dicionário de dados é a referência para schema, grão, chaves, camada e status de implementação.
- Status recomendados: `planned`, `implemented`, `published` e `deprecated`.
- Uma tabela só pode ser descrita como publicada quando existir no artefato versionado do Kaggle correspondente.

## 5. Organização lógica da publicação

A organização abaixo é uma proposta lógica para os artefatos publicados. O formato físico final e a estrutura de diretórios podem ser ajustados conforme limites e convenções do Kaggle, sem alterar a separação conceitual das camadas.

```text
tse-eleicoes-dados/
├── bronze/
│   ├── fact_urna_logs/
│   └── ...
├── silver/
│   ├── fact_urna_event/
│   ├── fact_voting_session/
│   └── ...
├── gold/
│   └── ...
└── manifest.json
```

Cada publicação deve permitir identificar a camada, tabela, parâmetros e versão. O manifesto deve relacionar os artefatos de saída às fontes e versões de entrada, ao código executado e às regras aplicadas.

### Identidade do dataset publicado

O identificador canônico do dataset no Kaggle deve acompanhar o nome do repositório: **`miolodados/tse-eleicoes-dados`**. O identificador legado `miolodados/tse-analises-eleicoes` deve ser tratado apenas como referência histórica durante a migração, não como destino de novas publicações.

A migração do identificador deve ser coordenada com a atualização de notebooks, configurações, documentação, comandos Kaggle CLI e consumidores externos. A issue de release deve validar a publicação e o consumo pelo identificador novo antes de considerar a migração concluída.

## 6. Fluxo operacional: GitHub → Kaggle → Kaggle Dataset

**GitHub é o repositório de desenvolvimento e versionamento. Kaggle é o ambiente oficial de execução e publicação.**

1. Código, notebooks, documentação, configurações e testes são versionados no GitHub.
2. O notebook de execução é disponibilizado/atualizado no Kaggle a partir da versão revisada.
3. A execução no Kaggle obtém as entradas necessárias, executa ingestão e transformações, valida os resultados e gera os artefatos.
4. A publicação/versionamento do dataset é realizada a partir do ambiente Kaggle.
5. O manifesto registra a versão do código/notebook, parâmetros, fontes, regras e artefatos produzidos.

### Regra obrigatória de execução

**100% do processamento oficial do pipeline deve ocorrer no Kaggle**, incluindo:
- ingestão e atualização da Bronze;
- transformações Silver;
- geração de produtos Gold;
- validações de qualidade e cobertura;
- geração de Parquet, relatórios e manifesto;
- publicação de novas versões do dataset.

Não deve haver etapa local ou em CI que processe os dados e produza os artefatos oficiais publicados. Ferramentas locais podem ser usadas para editar e revisar código/documentação, mas não substituem a execução oficial no Kaggle.

O Kaggle CLI pode ser utilizado para transportar/publicar versões e automatizar operações compatíveis, mas os comandos e o fluxo efetivamente suportados devem ser documentados na instrução operacional de release. Não se presume aqui um comando específico de publicação.

## 7. Parâmetros e particionamento

Parâmetros de execução, como `election_year`, `turn` e `uf`, devem ser explícitos, validados e registrados no manifesto. A aplicabilidade varia por fonte: nem toda fonte possui partição por UF ou turno, e códigos como `BR` ou `ZZ` não devem ser tratados como UFs ordinárias sem regra documentada.

O particionamento físico deve respeitar os contratos documentados no dicionário de dados. A arquitetura lógica não autoriza alterar chaves de particionamento sem avaliar impacto em compatibilidade e consumo.

## 8. Proveniência, versionamento e reprodutibilidade

Para cada execução, registrar quando aplicável:
- identificador e timestamp da execução;
- parâmetros utilizados;
- identificadores/URLs e datas das fontes;
- versão ou hash dos arquivos de entrada, quando disponível;
- commit Git e versão dos notebooks/código;
- versão das regras de transformação;
- schemas e contagens de entrada/saída;
- resultados das validações;
- identificadores/versões dos artefatos publicados.

A linhagem deve ser navegável:
- Silver → registros/tabelas Bronze de origem;
- Gold → tabelas Silver utilizadas;
- manifesto → execução e versões responsáveis pelos artefatos.

## 9. Qualidade e critérios de publicação

As validações devem considerar, conforme o contrato de cada tabela:
- schema e tipos;
- grão e unicidade esperada;
- completude e cobertura por ano/turno/UF;
- integridade referencial;
- contagens e reconciliações;
- rastreabilidade e proveniência;
- consistência das regras semânticas;
- regressões em relação à versão publicada anterior.

Falhas críticas devem impedir a publicação. Alertas não bloqueantes precisam ser registrados e explicados. Cobertura esperada deve ser definida por fonte e não presumida como uma matriz universal de 27 UFs por turno.

## 10. Responsabilidade dos consumidores

O TS-Zé e outros consumidores consultam as tabelas publicadas, seus schemas e metadados. Eles não extraem fontes, não transformam Bronze em Silver, não constroem Gold e não corrigem dados publicados. Lacunas identificadas por consumidores devem ser documentadas e encaminhadas ao repositório de dados.

## 11. Fora do escopo desta arquitetura

Este documento não define ainda:
- schema final de `fact_urna_event` ou `fact_voting_session`;
- taxonomia definitiva dos eventos;
- máquina de estados definitiva;
- conjunto final de dimensões conformadas;
- primeiro produto Gold;
- layout físico definitivo do dataset Kaggle.

Esses contratos serão definidos nas respectivas etapas de modelagem, com base na inspeção das fontes e evidências disponíveis.
