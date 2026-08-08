# UserZero — DESIGN.md

> Contexto técnico consolidado na véspera do Hack2L, como **arquitetura da solução** (preparação explicitamente permitida pelo regulamento). Nenhuma linha de código do projeto existe antes de 08/08; este arquivo é a fonte de contexto para o time e para o AI coder no dia. O design é genérico — nada aqui depende de um app-alvo específico.

## Visão em uma frase

Plataforma de usuários sintéticos que verifica se produtos de IA cumprem **contratos de comportamento**: fluxos compilados executam N vezes, cada execução é julgada, e o veredito é estatístico, comparado a baseline, com evidência anexada.

## Princípios de engenharia

Pipeline de arquivos inspecionáveis: cada componente lê um artefato e escreve outro; qualquer etapa re-executa isolada, e o time trabalha em paralelo contra artefatos escritos à mão. LLM em exatamente três pontos — Compilador (1× por fluxo), Healer (só em falha de passo), juízes semânticos (Haiku, estreitos) — e todo o resto é código determinístico. Uma execução que falha é dado, não retry silencioso.

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

## Setup inicial do app-alvo (Cartógrafo)

Acontece uma vez por app (e incrementalmente depois). Inputs: `BASE_URL`, credenciais de **staging/conta de teste**, e opcionalmente uma instrução de foco ("mapeie os fluxos de relatório"). O agente (Claude + Playwright MCP) explora em largura com orçamento explícito — `max_states`, `max_depth`, `max_minutes` — registrando cada estado visitado e cada ação disponível, com screenshot por estado. **Guardrails:** a exploração é *read-mostly*; ações destrutivas ou com efeito externo (excluir, pagar, enviar e-mail/convite) ficam numa blocklist por padrão e só entram com whitelist explícita. Durante a exploração, o Cartógrafo **escuta o tráfego de rede** (network interception) para associar cada ação de UI à chamada de API subjacente — é essa associação que habilita o modo `api` (volume) mais tarde.

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

## Setup de um teste (Compilador + dry-run)

Usuário descreve o fluxo em linguagem natural. O Compilador ancora no grafo, executa uma vez agenticamente num browser real (a única execução cara, ~US$ 3–4) e emite o `spec.yaml`. O Executor roda o spec em dry-run (n=1, sem LLM, centavos) e produz o storyboard; na tela de aprovação, heurísticas determinísticas sobre os valores observados **propõem contratos** (idioma detectado → `language`; latência medida com margem → `latency`; seções parseadas → `format`; opcionalmente 1 chamada Haiku propõe semânticos, ex. `grounding` contra o arquivo subido no fluxo). O usuário aprova, ajusta limiares ou pede mudança de caminho — nesse caso o Compilador re-ancora só os passos afetados e dispara novo dry-run. Aprovado, o spec vira ativo. Aprova-se exatamente o artefato que rodará N vezes. Setup sempre em staging/conta de teste (duas execuções reais acontecem antes da aprovação).

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

## Healer — contrato de comportamento

Dispara em seletor não encontrado ou timeout de *ação* (não de geração). Recebe o passo falho (com `goal`), o snapshot de acessibilidade da página e o nó do grafo; devolve o seletor corrigido. O Executor tenta de novo; no sucesso, patcheia spec e grafo e registra o episódio em `heals[]`; após K=2 falhas, marca o run como `blocked` com evidência e o batch continua. Episódios de cura são a semente do flywheel de dados.

## Juízes v0 — catálogo

Assinatura única: `judge(run, params) → { pass: boolean, evidence: string | object }`. Rodam sobre os `run-*.json`, nunca sobre o browser — re-executáveis e paralelizáveis. O *catálogo de tipos* é fixo (código nosso); *quais instâncias* rodam, com quais parâmetros e sobre qual captura, é declaração do spec.

Determinísticos (construir amanhã): `language` (detector, ex. tinyld), `format` (parse de seções/JSON + placeholders + truncamento), `latency` (aritmética sobre timestamps `from`/`to`), `change_scope` (split por seção + hash + diff — verifica que só a seção permitida mudou).

Semânticos (amanhã se der: `grounding`; roadmap: `rubric`): chamada Haiku 4.5 com output estruturado, **um modo de falha por juiz**. `grounding` recebe claims extraídas da captura + chunks das fontes e devolve claims não suportadas, com citação. `rubric(criterion)` é template fixo parametrizado por um critério em texto; a origem futura do parâmetro é a mineração dos pares gerado→aprovado do cliente (camada 2 — **não construir amanhã**; é slide).

## Veredito

Agregações: pass-rate por contrato com intervalo de confiança (Wilson); latências min/p50/p95/max por fase declarada; comparação contra `baseline.json` do release anterior; piores K exemplos com evidência (screenshot, diff, trace do Playwright e, quando o alvo tem Langfuse, URL do trace casada por janela de tempo). Trilha Vindler: os mesmos specs contra `main` e contra o branch do PR → dois vereditos → o diff entre eles é o parecer, com prova executável.

## Evidência e retenção

O Executor grava tudo em área de staging; a decisão de retenção acontece **depois do julgamento**, no Veredito — nunca no fim da execução, porque um run pode executar limpo e reprovar num contrato na etapa de Juízes. Regra: falha (de execução **ou** de contrato) promove os artefatos — vídeo, trace, screenshots, `run.json` — ao evidence store, retidos até o achado ser marcado como resolvido, com margem; sucesso agenda limpeza em 1h, preservando 1–3 exemplares por batch para o lado a lado do report. Em produção: lifecycle rule por prefixo no object storage (`passed/` expira, `failed/` segura). Precedente que valida o desenho: o test runner do Playwright tem `video: 'retain-on-failure'` como primitivo de configuração — como usamos a lib, a regra vive no finalizador do run, com a diferença de que o nosso *failure* inclui reprovação de contrato. **Versão do hackathon:** `recordVideo` + delete-on-pass no finalizador + link do `.webm` no report (~30–60 min); trace completo e amostragem sob carga entram se sobrar tempo.

## Decisões fechadas e armadilhas conhecidas

`retries=0` — run falho é dado. Rate limit (429) do alvo sob carga é achado do produto, não bug da demo: capturar a curva e apresentar. Em container: `--no-sandbox --disable-dev-shm-usage`; nunca herdar lockfile de outra plataforma na imagem (remover e reinstalar). Em fan-out na nuvem: `return_exceptions=true` para um worker morto não abortar o batch. Onda canário (n=3) antes de qualquer carga cheia. Custo: ~98% do custo agêntico é API de LLM — por isso o agente fica fora do loop de execução; juízes em Haiku, agentes em Sonnet.

## Stack e papéis

Monorepo TypeScript. Agentes (Cartógrafo, Compilador, Healer): Claude Agent SDK + Playwright MCP. Runner: Playwright puro. Juízes: LangChain.js com `withStructuredOutput` + Haiku 4.5. O próprio UserZero instrumentado com Langfuse (`langfuse-langchain` CallbackHandler) desde a primeira hora. Persistência: arquivos JSON (SQLite só se sobrar tempo). Report: HTML estático. Estágio B opcional (timebox 14h–14h45): Modal com um container por usuário sintético e alvo local exposto via cloudflared tunnel.

Papéis: quem domina browser fica com tudo que toca Playwright (esqueleto do runner primeiro, depois Cartógrafo e Healer); perfil LangChain A fica com juízes + agregação estatística; perfil LangChain B fica com report + instrumentação Langfuse + agente PRD→fluxos (trilha Vindler); quarta pessoa, se houver, é dona do Modal + vídeo/deck.

## Inegociáveis, cortes e a decisão das 9h

Inegociáveis: linguagem natural → spec compilado; N execuções com pass-rate de pelo menos dois contratos; um self-heal demonstrável. Cortes pré-decididos, nesta ordem: dashboard bonito (report estático resolve) → Cartógrafo autônomo (vira mapeamento semi-guiado) → mini-carga. Decisão das 9h: se o app da Vindler sobe com um comando, ele é o alvo e o time concorre aos dois prêmios; senão, alvo fallback preparado na véspera e foco no prêmio geral.
