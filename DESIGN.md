# UserZero — DESIGN.md

> Contexto técnico consolidado na véspera do Hack2L, como **arquitetura da solução** (preparação explicitamente permitida pelo regulamento). Nenhuma linha de código do projeto existe antes de 08/08; este arquivo é a fonte de contexto para o time e para o AI coder no dia. O design é genérico — nada aqui depende de um app-alvo específico.

> **Atualização pós-kickoff:** o stack pivotou de TypeScript/Claude Agent SDK para **Python + LangChain + Featherless** (modelo servido através da abstração da lib `openai`, com as chaves da Featherless — ver `src/common/llm.py`). Cartógrafo e Compilador já estão implementados; as seções abaixo foram atualizadas para refletir decisões reais tomadas durante a implementação — o plano original de dry-run/confirmação, em particular, mudou de forma quando ficou claro que só o Compilador tem contexto (URL, credenciais, o texto do fluxo) para recompilar caso o usuário rejeite o fluxo.

## Visão em uma frase

Plataforma de usuários sintéticos que verifica se produtos de IA cumprem **contratos de comportamento**: fluxos compilados executam N vezes, cada execução é julgada, e o veredito é estatístico, comparado a baseline, com evidência anexada.

## Princípios de engenharia

Pipeline de arquivos inspecionáveis: cada componente lê um artefato e escreve outro; qualquer etapa re-executa isolada, e o time trabalha em paralelo contra artefatos escritos à mão. LLM em exatamente três pontos — Compilador (1× por fluxo; inclui a execução agêntica e uma segunda chamada barata e não-agêntica para formalizar contratos a partir da descrição do usuário, ambas contam como "o ponto do Compilador"), Healer (só em falha de passo), juízes semânticos (estreitos) — e todo o resto é código determinístico. Uma execução que falha é dado, não retry silencioso.

## Pipeline de artefatos

| Componente | Consome | Produz |
|---|---|---|
| Cartógrafo (agêntico, 1×/app) | URL + credenciais do alvo | `graph.json` + `map.md` |
| Compilador (agêntico, 1×/fluxo) | frase em linguagem natural + `graph.json` | `spec.yaml` candidato |
| Executor em dry-run (determinístico, n=1) | `spec.yaml` candidato | storyboard (screenshots + capturas) para aprovação |
| Executor em produção (determinístico, n=N) | `spec.yaml` aprovado | `run-001.json` … `run-N.json` + screenshots |
| Healer (agêntico, sub-rotina do Executor) | passo falho + `goal` + snapshot a11y + nó do grafo | patch em `spec.yaml`/`graph.json` + episódio logado |
| Juízes (funções puras + Haiku) | `run-*.json` | `judgments.json` |
| Veredito (determinístico) | `judgments.json` + `baseline.json` | `report.html` + novo baseline |

O Compilador recebe, além da frase do fluxo, uma descrição opcional em linguagem natural do comportamento esperado (`--contracts` — vazia por padrão, nunca inventada). Entre Compilador e Executor-em-produção existe um passo de confirmação (`compile_and_confirm`, dono do loop, vive no Compilador — ver seção própria abaixo) que chama o Executor em dry-run para obter dados reais antes de aprovar.

## Setup inicial do app-alvo (Cartógrafo)

Acontece uma vez por app (e incrementalmente depois). Inputs: `BASE_URL`, credenciais de **staging/conta de teste**, e opcionalmente uma instrução de foco ("mapeie os fluxos de relatório"). O agente (LangChain + Featherless + Playwright MCP) explora em largura com orçamento explícito — `max_states`, `max_depth`, `max_minutes` — registrando cada estado visitado e cada ação disponível, com screenshot por estado. **Guardrails:** a exploração é *read-mostly*; ações destrutivas ou com efeito externo (excluir, pagar, enviar e-mail/convite) ficam numa blocklist por padrão e só entram com whitelist explícita. Durante a exploração, o Cartógrafo **escuta o tráfego de rede** (network interception) para associar cada ação de UI à chamada de API subjacente — é essa associação que habilita o modo `api` (volume) mais tarde.

Outputs:

```json
// graph.json
{
  "nodes": [
    { "id": "reports", "url": "/reports", "title": "Relatórios",
      "fingerprint": "hash-do-DOM-estrutural (dedup de estados)",
      "screenshot": "reports.png" }
  ],
  "edges": [
    { "from": "reports", "to": "report-view", "action": "click",
      "selector": "[data-testid=\"generate\"]", "label": "Gerar relatório",
      "api": { "method": "POST", "path": "/api/reports" } }
  ]
}
```

`map.md`: descrição da plataforma em linguagem natural (o que cada área faz, o vocabulário do produto) — é o que permite ao Compilador ancorar "gere um relatório a partir do PDF" nos nós certos. Re-mapeamentos posteriores diffam contra o grafo existente (base da seleção de testes por impacto — roadmap). **Versão do hackathon:** semi-guiada — o humano aponta os 2–3 fluxos e o agente mapeia só esse corredor; a exploração autônoma completa é o primeiro corte pré-decidido.

## Setup de um teste (Compilador + dry-run + confirmação)

Usuário descreve o fluxo em linguagem natural e, opcionalmente, o comportamento esperado (`--contracts`, também em linguagem natural — vazio por padrão, nunca inventado pelo Compilador). O Compilador ancora no grafo (`graph.json`/`map.md` do Cartógrafo), executa o fluxo uma vez agenticamente num browser real (a única execução cara do setup, ~US$ 3–4 / ~700k tokens) e emite o `spec.yaml` com os `steps` compilados. Separadamente, uma chamada barata e não-agêntica (`derive_contracts`, sem browser) formaliza a descrição de contratos nos tipos do catálogo, vinculada apenas a capturas/steps que realmente existem no spec — se o usuário não descreveu comportamento nenhum, `contracts` fica vazio; a descrição também pode pedir grounding contra conteúdo que o próprio fluxo digitou (ex. o texto de um documento que ele mesmo cadastrou), mas nunca contra um documento pré-existente que o fluxo só selecionou sem nunca ler.

Em seguida, `compile_and_confirm` (dono do loop; vive no Compilador, não no Executor) chama o Executor em dry-run (n=1, sem LLM, centavos) para obter o storyboard real, e conduz a confirmação em duas perguntas, **fluxo primeiro, contratos depois** — nessa ordem porque contratos são vinculados ao fluxo: rejeitar o fluxo invalidaria qualquer contrato já derivado dele, então não faz sentido confirmar contratos antes:

1. **Fluxo:** mostra os steps compilados + o resultado real observado no dry-run (passo a passo, capturas, screenshots). Se o usuário rejeitar, o Compilador **recompila do zero com o feedback anexado** ao invés de um agente de reparo dedicado — mais simples de manter, mas com o mesmo custo da compilação original, não é um patch barato — e o ciclo (compilar → dry-run → confirmar) se repete.
2. **Contratos:** só chega aqui se o fluxo foi aprovado. Mostra os contratos declarados mais uma linha `"sugestões automáticas: em breve"` (heurísticas sobre valores observados no dry-run — idioma detectado, timing real, seções encontradas — ficam para depois de existirem Juízes para consumi-las; não fazem parte do v0). Se o usuário rejeitar, dispara só um novo `derive_contracts` com o feedback anexado — chamada barata, sem browser, sem recompilar o fluxo.

Aprovados os dois, o spec vira o artefato ativo — exatamente o que o Executor roda N vezes depois. Setup sempre em staging/conta de teste.

## Orquestração e os três pontos de entrada

Três CLIs, mesma lógica reaproveitada, sem duplicar o loop de confirmação:

- **`compilador`** sozinho: compila, roda `compile_and_confirm`, e ao final só imprime `Test case is ready under <path>`. Não avança para produção.
- **`executor --compilador-dir X --mode dry|batch`** sozinho: aponta para um `spec.yaml` já existente e o executa (n=1 ou n=N) sem nenhuma UI de confirmação — confirmar é decisão de quem compila, não de quem executa; o Executor standalone só roda o que já existe e devolve dados estruturados.
- **`userzero`** (orquestrador): chama `compilador.compile_and_confirm`; aprovado, imprime `---EXECUTOR STEP---` e roda o Executor em produção (n=N, mesmo console); ao chegar nos Juízes (não construídos ainda), imprime `JUDGES BEING IMPLEMENTED` e para.

O Executor não sabe nada sobre Compilador nem sobre a UI de confirmação — é 100% determinístico e plain Playwright (`playwright.async_api`), não o Playwright MCP que Cartógrafo/Compilador usam (MCP é para um LLM dirigir o browser via tool calls; sem LLM no loop, o Executor fala com o Playwright direto, sem subprocess, sem interceptors). Sem Healer construído ainda, qualquer falha de passo marca o run como `blocked` de imediato (`heals: []` sempre vazio por ora).

## Schema do spec (exemplo genérico: gerador de relatório qualquer)

```yaml
flow: gerar-relatorio
mode: ui                     # ui (browser) | api (volume)
steps:
  - { id: s1, action: goto,  url: "${BASE_URL}/reports" }
  - { id: s2, action: upload, selector: '[data-testid="source-upload"]',
      file: fixtures/fonte.pdf, goal: "anexar o documento-fonte" }
  - { id: s3, action: click, selector: '[data-testid="generate"]', goal: "iniciar a geração" }
  - { id: s4, action: wait_for, selector: '[data-testid="report-body"]', timeout_ms: 300000,
      capture: { name: report_text, latency: true } }
  - { id: s5, action: fill,  selector: '[data-testid="chat-input"]',
      value: "Reescreva apenas a seção 2, mais curta.", goal: "pedir edição localizada" }
  - { id: s6, action: click, selector: '[data-testid="send"]' }
  - { id: s7, action: wait_for, selector: '[data-testid="report-body"][data-version="2"]',
      timeout_ms: 120000, capture: { name: report_text_v2, latency: true } }
contracts:
  - { type: language,     target: report_text, expect: pt-BR }
  - { type: format,       target: report_text, sections: [Resumo, Análise, Riscos], no_placeholders: true }
  - { type: latency,      from: s3, to: s4, p95_max_s: 180 }
  - { type: grounding,    target: report_text, sources: [fixtures/fonte.pdf] }   # semântico
  - { type: change_scope, before: report_text, after: report_text_v2, allowed_section: 2 }
```

Regras do schema: todo passo é timestampado automaticamente pelo Executor, então um contrato de `latency` pode referenciar qualquer par `from`/`to` — as "fases" são declaradas no spec, não no código. `capture` nomeia conteúdo extraído (do DOM em modo ui; do body em modo api) e é a ponte entre execução e julgamento: juízes referenciam capturas por nome. `goal` é o contexto que o Healer usa. Seletores em ordem de preferência: test-id > role/aria > texto. `data-testid` é a convenção genérica de mercado (default do `getByTestId` do Playwright), mas o Cartógrafo detecta a variante usada pelo alvo (`data-test`, `data-qa`, `data-cy`) e configura o Playwright de acordo; sem test-id nenhum, a escada cai para role/aria. Nota: a ordem é deliberadamente invertida em relação à recomendação dos manuais (role primeiro) — aquela otimiza testes escritos por humanos; a nossa otimiza estabilidade de seletores mantidos por máquina, pois role+nome quebra quando o copy muda ou o app é traduzido. Ações v0: `goto`, `click`, `fill`, `upload`, `wait_for`.

## Shape do run.json (um por execução)

```json
{
  "run": 17,
  "status": "ok | blocked | error",
  "steps": [ { "id": "s3", "ok": true, "t_start_ms": 1754640000123, "t_end_ms": 1754640000889 } ],
  "captures": { "report_text": "…", "report_text_v2": "…" },
  "artifacts": { "screenshots": ["s1.png"], "console": "console.log" },
  "heals": [ { "step": "s4", "old_selector": "…", "new_selector": "…", "reason": "…" } ]
}
```

## Executor — regras

Loop `1..N` com concorrência via p-limit; um browser, N `browserContexts`; bloquear imagens/fontes por route interception nos contexts de carga; headless; nunca lançar exceção por falha de run — registrar status com evidência e seguir o batch. Em `wait_for` com `latency: true`, registrar também o tempo até o primeiro conteúdo quando o alvo faz streaming. Modo `api` reusa o mesmo spec quando os passos têm endpoint mapeado no grafo. Gravação dupla por execução em modo fidelidade: `recordVideo` no contexto (`.webm`) + `tracing.start`/`stop` (`trace.zip`, replayável no Trace Viewer). Em modo carga, gravação por amostragem (2–3 contexts de N) ou desligada, com latência medida apenas nos contexts sem gravação — encodar vídeo custa CPU por contexto e infla a métrica que se quer medir; trace leve (screenshots off) pode ficar ligado. Modo `api` não tem browser: a evidência é o body capturado. Todo tráfego sintético carimbado — header `X-UserZero-Synthetic: 1` + sufixo identificável no user-agent — com filtro de exclusão documentado para o analytics do cliente (PostHog e afins) não ser contaminado por usuários que não existem.

Dry-run e produção compartilham exatamente o mesmo runner (`play_spec`, um passo do spec por vez contra uma página real) — a diferença é só `n=1` vs `n=N` e o que a chamada faz com o resultado (storyboard para a confirmação do Compilador vs. arquivo `run-NNN.json` para os Juízes).

## Healer — contrato de comportamento

Dispara em seletor não encontrado ou timeout de *ação* (não de geração). Recebe o passo falho (com `goal`), o snapshot de acessibilidade da página e o nó do grafo; devolve o seletor corrigido. O Executor tenta de novo; no sucesso, patcheia spec e grafo e registra o episódio em `heals[]`; após K=2 falhas, marca o run como `blocked` com evidência e o batch continua. Episódios de cura são a semente do flywheel de dados.

## Juízes v0 — catálogo

Assinatura única: `judge(run, params) → { pass: boolean, evidence: string | object }`. Rodam sobre os `run-*.json`, nunca sobre o browser — re-executáveis e paralelizáveis. O *catálogo de tipos* é fixo (código nosso); *quais instâncias* rodam, com quais parâmetros e sobre qual captura, é declaração do spec.

Determinísticos (construir amanhã): `language` (detector, ex. tinyld), `format` (parse de seções/JSON + placeholders + truncamento), `latency` (aritmética sobre timestamps `from`/`to`), `change_scope` (split por seção + hash + diff — verifica que só a seção permitida mudou).

Semânticos (amanhã se der: `grounding`; roadmap: `rubric`): chamada a um modelo leve via Featherless (`get_llm()`, mesmo client de todo o resto do pipeline) com output estruturado, **um modo de falha por juiz**. `grounding` recebe claims extraídas da captura + chunks das fontes e devolve claims não suportadas, com citação. `rubric(criterion)` é template fixo parametrizado por um critério em texto; a origem futura do parâmetro é a mineração dos pares gerado→aprovado do cliente (camada 2 — **não construir amanhã**; é slide).

## Veredito

Agregações: pass-rate por contrato com intervalo de confiança (Wilson); latências min/p50/p95/max por fase declarada; comparação contra `baseline.json` do release anterior; piores K exemplos com evidência (screenshot, diff, trace do Playwright e, quando o alvo tem Langfuse, URL do trace casada por janela de tempo). Trilha Vindler: os mesmos specs contra `main` e contra o branch do PR → dois vereditos → o diff entre eles é o parecer, com prova executável.

## Evidência e retenção

O Executor grava tudo em área de staging; a decisão de retenção acontece **depois do julgamento**, no Veredito — nunca no fim da execução, porque um run pode executar limpo e reprovar num contrato na etapa de Juízes. Regra: falha (de execução **ou** de contrato) promove os artefatos — vídeo, trace, screenshots, `run.json` — ao evidence store, retidos até o achado ser marcado como resolvido, com margem; sucesso agenda limpeza em 1h, preservando 1–3 exemplares por batch para o lado a lado do report. Em produção: lifecycle rule por prefixo no object storage (`passed/` expira, `failed/` segura). Precedente que valida o desenho: o test runner do Playwright tem `video: 'retain-on-failure'` como primitivo de configuração — como usamos a lib, a regra vive no finalizador do run, com a diferença de que o nosso *failure* inclui reprovação de contrato. **Versão do hackathon:** `recordVideo` + delete-on-pass no finalizador + link do `.webm` no report (~30–60 min); trace completo e amostragem sob carga entram se sobrar tempo.

## Decisões fechadas e armadilhas conhecidas

`retries=0` — run falho é dado. Rate limit (429) do alvo sob carga é achado do produto, não bug da demo: capturar a curva e apresentar. Em container: `--no-sandbox --disable-dev-shm-usage`; nunca herdar lockfile de outra plataforma na imagem (remover e reinstalar). Em fan-out na nuvem: `return_exceptions=true` para um worker morto não abortar o batch. Onda canário (n=3) antes de qualquer carga cheia. Custo: ~98% do custo agêntico é API de LLM — por isso o agente fica fora do loop de execução; juízes num modelo leve, agentes no modelo configurado via `MODEL`/Featherless (mesmo `get_llm()` para os dois — a diferença de custo é o número de chamadas, não o provider).

## Stack e papéis

**Stack real** (pivotado do plano original em TypeScript/Claude Agent SDK): monorepo Python (`src/`, com `pyproject.toml` — `pip install -e .` deixa `cartografo`/`compilador` importáveis e com entry point de CLI, sem precisar de `PYTHONPATH`). Agentes (Cartógrafo, Compilador): LangChain (`langchain.agents.create_agent`, um agente ReAct por módulo) + Playwright MCP via `langchain-mcp-adapters`. LLM: Featherless, servido pela abstração da lib `openai` através do `ChatOpenAI` do `langchain-openai` — único ponto de instanciação em `src/common/llm.py::get_llm()`, compartilhado por todo agente e pela extração de contratos. Infra compartilhada em `src/common/`: `llm.py`, `agent_logging.py` (streaming + transcript), `mcp_client.py`/`guardrails.py`/`snapshot_capture.py` (sessão MCP + blocklist de ações destrutivas + captura de snapshot, usados por Cartógrafo e Compilador), `budget.py` (limite genérico de contagem+tempo). Runner do Executor: Playwright puro (`playwright.async_api`), sem LLM, sem MCP. Juízes: catálogo ainda não implementado (roadmap imediato após o Executor — determinísticos primeiro). Persistência: arquivos JSON/YAML (`graph.json`, `spec.yaml`, `run-*.json`) — sem banco. O próprio UserZero instrumentado com Langfuse (`langfuse-langchain` CallbackHandler) desde a primeira hora. Report: HTML estático. Estágio B opcional (timebox 14h–14h45): Modal com um container por usuário sintético e alvo local exposto via cloudflared tunnel.

Papéis: quem domina browser fica com tudo que toca Playwright (esqueleto do runner primeiro, depois Cartógrafo e Healer); perfil LangChain A fica com juízes + agregação estatística; perfil LangChain B fica com report + instrumentação Langfuse + agente PRD→fluxos (trilha Vindler); quarta pessoa, se houver, é dona do Modal + vídeo/deck.

## Inegociáveis, cortes e a decisão das 9h

Inegociáveis: linguagem natural → spec compilado; N execuções com pass-rate de pelo menos dois contratos; um self-heal demonstrável. Cortes pré-decididos, nesta ordem: dashboard bonito (report estático resolve) → Cartógrafo autônomo (vira mapeamento semi-guiado) → mini-carga. Decisão das 9h: se o app da Vindler sobe com um comando, ele é o alvo e o time concorre aos dois prêmios; senão, alvo fallback preparado na véspera e foco no prêmio geral.
