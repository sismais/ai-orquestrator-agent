// Validação falha-fechada do output do reviewer (contrato devkit-core/schemas/review-findings).
// Espelha a semântica do parser estrito da plataforma (ai-orquestrator-agent, findings.py):
// último objeto JSON do texto contendo ao menos um dos baldes; balde não-array vira [];
// texto sem objeto com balde -> null (NUNCA aprovar por ausência de parse).
// Divergência conhecida e benigna: json.loads (Python) aceita NaN/Infinity, JSON.parse não —
// aqui o caso degrada para falha-fechada (exit 2), nunca para aprovação indevida.
//
// Comandos:
//   parse-review --file <raw>   -> normaliza {blocks,fixNow,suggestions} (contrato com o loop/plataforma)
//   bucket --file <raw> ...     -> converte achados PLANOS (findings[]) nos 3 baldes por regra
//                                  determinística. Tira a decisão de balde do modelo: o mesmo
//                                  achado cai sempre no mesmo balde entre iterações do loop.
//   stamp --file <relatorio.md> -> carimba o frontmatter do relatório (escopo, commit, rodada e
//                                  as duas datas). Idempotente: preserva a `data-criacao`.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Varre objetos JSON válidos no texto por balanceamento de chaves (tolera prosa e cercas ```json).
export function* iterJsonObjects(text) {
  let depth = 0;
  let start = -1;
  let inStr = false;
  let escape = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      if (escape) escape = false;
      else if (ch === '\\') escape = true;
      else if (ch === '"') inStr = false;
      continue;
    }
    if (ch === '"') {
      inStr = true;
    } else if (ch === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (ch === '}') {
      if (depth > 0) {
        depth -= 1;
        if (depth === 0 && start !== -1) {
          const candidate = text.slice(start, i + 1);
          try {
            const obj = JSON.parse(candidate);
            if (obj && typeof obj === 'object' && !Array.isArray(obj)) yield obj;
          } catch { /* candidato inválido — segue a varredura */ }
          start = -1;
        }
      }
    }
  }
}

const asList = (v) => (Array.isArray(v) ? v : []);
const BUCKETS = ['blocks', 'fixNow', 'suggestions'];

// null quando o texto não contém nenhum objeto JSON com os baldes (falha-fechada).
export function parseReviewFindingsStrict(text) {
  if (!text) return null;
  let found = null;
  for (const obj of iterJsonObjects(text)) {
    if (BUCKETS.some((k) => k in obj)) found = obj;
  }
  if (found === null) return null;
  return {
    blocks: asList(found.blocks),
    fixNow: asList(found.fixNow),
    suggestions: asList(found.suggestions)
  };
}

// ---------------------------------------------------------------------------
// Bucket determinístico (achados planos -> baldes)
// ---------------------------------------------------------------------------

// Classes que impedem merge. Default genérico do devkit; o projeto sobrepõe via
// `.sismais-dev.json` (blockingClasses) ou --blocking, porque a lista canônica é
// do projeto (ex.: docs/PR_REVIEW_CHECKLIST.md do GMS Web).
// `regressao` ficou de fora de propósito: é vaga o bastante para virar balde de
// "mudou algo e eu não gostei" — foi o que produziu um falso bloqueio ao remover
// duas páginas stub inalcançáveis. Regressão que importa já é `bug` ou
// `breaking-contrato`; a que não altera comportamento observável não bloqueia nada.
export const DEFAULT_BLOCKING_CLASSES = [
  'bug', 'seguranca', 'rls', 'multi-tenant', 'perda-dados',
  'silent-failure', 'breaking-contrato', 'comment-errado', 'pipeline'
];
export const DEFAULT_MIN_CONF = 80;

// Sem acento e caixa baixa — o modelo escreve "pré-existente" ou "pre-existente"
// conforme o dia, e isso não pode mudar o balde.
const fold = (v) => String(v ?? '')
  .normalize('NFD').replace(/\p{Diacritic}/gu, '')
  .toLowerCase().trim();

// Valor RECONHECÍVEL do contrato, ou null. Existe separado de normalizeAttribution
// porque o juiz pode corrigir a atribuição, e ali "não reconheci o que ele escreveu"
// tem de preservar o que a lente disse — não virar PR-ativado por baixo do pano.
export function parseAttribution(value) {
  const v = fold(value);
  if (v.startsWith('pre-existente') || v.startsWith('preexistente')) return 'pre-existente';
  if (v.startsWith('pr-introduzido') || v.startsWith('introduzido')) return 'PR-introduzido';
  if (v.startsWith('pr-ativado') || v.startsWith('ativado')) return 'PR-ativado';
  return null;
}

// Ausência e valor desconhecido caem em PR-ativado: erra para "revisa", nunca
// para "ignora" (só `pre-existente` é descartável, e por isso exige ser explícito).
export function normalizeAttribution(value) {
  return parseAttribution(value) ?? 'PR-ativado';
}

// Confiança/classe ausentes seguem o mesmo princípio: ausência de dado nunca
// resulta em silenciar achado. Sem conf, assume o corte; sem classe, assume `bug`.
const confOf = (f) => (typeof f.conf === 'number' && Number.isFinite(f.conf) ? f.conf : DEFAULT_MIN_CONF);
const classOf = (f) => (fold(f.classe) || 'bug');

// null quando o texto não contém objeto JSON com `findings` (falha-fechada).
export function parseCandidatesStrict(text) {
  if (!text) return null;
  let found = null;
  for (const obj of iterJsonObjects(text)) {
    if ('findings' in obj) found = obj;
  }
  if (found === null) return null;
  return asList(found.findings).filter((f) => f && typeof f === 'object' && !Array.isArray(f));
}

// Tudo que acompanha os achados sem SER achado. Vive fora de findings[] porque,
// dentro da lista, o juiz julgaria e o corte por confiança descartaria:
//   cobertura        o que enumerei e amostrei
//   verificado       risco levantado e DESCARTADO com evidência
//   naoVerificado    o que não deu para checar, e por quê
//   pendingQuestions decisão de produto — verdadeira, mas não é do agente
// `pendingQuestions` é o canal que faltava: sem ele o modelo baixa a CONFIANÇA
// para tirar o item do balde, usando o eixo errado (não duvida do fato, duvida
// de quem decide) — e a decisão nunca chega a quem devia tomá-la.
export function parseExtras(text) {
  const out = {};
  if (!text) return out;
  const strs = ['cobertura'];
  const lists = ['verificado', 'naoVerificado', 'pendingQuestions'];
  for (const obj of iterJsonObjects(text)) {
    if (!('findings' in obj)) continue;
    for (const k of strs) if (typeof obj[k] === 'string' && obj[k].trim()) out[k] = obj[k].trim();
    for (const k of lists) {
      const v = asList(obj[k]).filter((x) => (k === 'pendingQuestions' ? x && typeof x === 'object' : typeof x === 'string' && x.trim()));
      if (v.length) out[k] = [...(out[k] || []), ...v];
    }
  }
  return out;
}

export function parseVerdictsStrict(text) {
  if (!text) return null;
  let found = null;
  for (const obj of iterJsonObjects(text)) {
    if ('verdicts' in obj) found = obj;
  }
  if (found === null) return null;
  return asList(found.verdicts).filter((v) => v && typeof v === 'object' && !Array.isArray(v));
}

// O juiz decide a confiança final, a classe E a atribuição — os TRÊS eixos vêm da
// lente que achou, e é ela que tem viés de justificar (validade), de inflar
// (impacto) e de puxar para si a causalidade (atribuição) do próprio achado.
// Deixar a classe sem revisão era pior que deixar a confiança: é a classe que
// decide o bloqueio, então achado verdadeiro-mas-leve entrava em `blocks` e o loop
// iterava tentando "corrigir" o que não precisava. A atribuição entrou pelo mesmo
// argumento: `pre-existente` é regra de corte ANTES da classe em bucketFindings —
// tem o mesmo poder de decisão — e o juiz não tinha onde registrar que o caminho
// se comporta igual antes do diff. Sem campo, quem decidia era o orquestrador,
// que é exatamente o que o bucket determinístico existe para impedir.
// Refutado zera (cai fora do corte). Achado sem veredito mantém o que tinha e é
// contado em meta.semVeredito: degradar aqui erra para "reporta demais".
export function applyVerdicts(candidates, verdicts) {
  if (!verdicts || !verdicts.length) {
    return { findings: candidates, semVeredito: candidates.length, reclassificados: 0, reatribuidos: 0 };
  }
  const byId = new Map(verdicts.filter((v) => v.id != null).map((v) => [String(v.id), v]));
  let semVeredito = 0;
  let reclassificados = 0;
  let reatribuidos = 0;
  const findings = candidates.map((f) => {
    const v = f.id != null ? byId.get(String(f.id)) : undefined;
    if (!v) { semVeredito += 1; return f; }
    if (v.refutado === true) return { ...f, conf: 0, motivoJuiz: v.motivo };
    const conf = typeof v.conf === 'number' && Number.isFinite(v.conf) ? v.conf : confOf(f);
    const out = { ...f, conf, motivoJuiz: v.motivo };
    if (typeof v.classe === 'string' && v.classe.trim() && fold(v.classe) !== classOf(f)) {
      out.classeOriginal = classOf(f);
      out.classe = v.classe.trim();
      reclassificados += 1;
    }
    // Erro seguro: só um valor DO CONTRATO reatribui. Ausente ou irreconhecível
    // preserva o da lente — o juiz não silencia achado por escrever torto.
    const atribuicao = parseAttribution(v.atribuicao);
    if (atribuicao && atribuicao !== normalizeAttribution(f.atribuicao)) {
      out.atribuicaoOriginal = normalizeAttribution(f.atribuicao);
      out.atribuicao = atribuicao;
      reatribuidos += 1;
    }
    // Fusão declarada pelo juiz: ele é quem enxerga os achados lado a lado e sabe
    // que duas lentes ancoraram o MESMO defeito em linhas diferentes (a assinatura
    // da função, o comentário acima dela, o ramo do `if`). A chave arquivo:linha
    // não funde isso, e fundir na mão era o orquestrador decidindo duplicata.
    if (typeof v.duplicataDe === 'string' && v.duplicataDe.trim()) out.duplicataDe = v.duplicataDe.trim();
    return out;
  });
  return { findings, semVeredito, reclassificados, reatribuidos };
}

// Duplicata = mesma LINHA + mesma classe. Consolida na de maior confiança e
// preserva a autoria das duas (o guardrail anti-viés: o consolidador só funde
// duplicata, nunca apaga achado por discordar do mérito).
// Sem número de linha, o título entra na chave: dois bugs distintos no mesmo
// arquivo são achados diferentes, e fundi-los apagaria um deles.
//
// `grupo` NÃO entra na chave, de propósito. Ele rotula o mesmo defeito em locais
// DIFERENTES (o par simétrico, as três chamadas do mesmo invariante) — irmãos que
// precisam continuar contados e verificáveis um a um, senão o implementador
// corrige um e o gêmeo esquecido volta como achado novo na rodada seguinte.
// Grupo agrupa no relatório; fusão exige `duplicataDe` explícito do juiz.
function dedupeKey(f) {
  const arquivo = fold(f.arquivo);
  const temLinha = /:\d+$/.test(arquivo);
  return temLinha ? `${arquivo}|${classOf(f)}` : `${arquivo}|${classOf(f)}|${fold(f.titulo)}`;
}

// Chave final por achado, com `duplicataDe` do juiz redirecionando para a do alvo.
// Cadeia (c->b->a) resolve para a ponta; ciclo ou alvo inexistente cai na própria
// chave — erro do juiz não pode apagar achado nem travar o script.
function resolveKeys(findings) {
  const byId = new Map(findings.filter((f) => f.id != null).map((f) => [String(f.id), f]));
  const keys = new Map();
  for (const f of findings) {
    const vistos = new Set();
    let atual = f;
    while (atual.duplicataDe && !vistos.has(atual)) {
      vistos.add(atual);
      const alvo = byId.get(String(atual.duplicataDe));
      if (!alvo || alvo === f) break;
      atual = alvo;
    }
    keys.set(f, dedupeKey(atual));
  }
  return keys;
}

function dedupe(findings) {
  const keys = resolveKeys(findings);
  const byKey = new Map();
  let duplicatas = 0;
  for (const f of findings) {
    const key = keys.get(f);
    const prev = byKey.get(key);
    const locais = f.arquivo ? [f.arquivo] : [];
    if (!prev) { byKey.set(key, { ...f, agentes: f.agente ? [f.agente] : [], locais }); continue; }
    duplicatas += 1;
    const winner = confOf(f) > confOf(prev) ? { ...f } : { ...prev };
    winner.agentes = [...new Set([...(prev.agentes || []), ...(f.agente ? [f.agente] : [])])];
    // Todos os locais dos fundidos, não só o do vencedor: quando a fusão vem do
    // juiz, o perdedor pode carregar a âncora que o implementador precisa abrir.
    winner.locais = [...new Set([...(prev.locais || []), ...locais])];
    byKey.set(key, winner);
  }
  return { findings: [...byKey.values()], duplicatas };
}

/**
 * Regra de bucket, nesta ordem (a primeira que casar decide):
 *  1. conf < minConf                      -> descartado (fora dos baldes, preservado em abaixoDoCorte)
 *  2. atribuicao `pre-existente`          -> suggestions (nunca bloqueia merge)
 *  3. classe `nit`/`remover`              -> suggestions
 *  4. classe bloqueante                   -> blocks
 *  5. resto                               -> fixNow
 * Confiança mede certeza de que o achado é válido; classe mede o dano. Só a
 * classe decide bloqueio — conf alta em `nit` não bloqueia, e custo do fix nunca entra.
 */
export function bucketFindings(candidates, { blocking = DEFAULT_BLOCKING_CLASSES, minConf = DEFAULT_MIN_CONF, muted = [] } = {}) {
  const blockingSet = new Set(blocking.map(fold));
  // Classes que o projeto desligou (ex.: `teste-ausente` em MVP sem testes).
  // Vive aqui, e não só nos prompts, porque instrução um dia escapa: desligar a
  // lente de testes sem silenciar a classe faz o generalista absorver o trabalho
  // e o projeto continuar recebendo cobrança de teste, só que de outro agente.
  const mutedSet = new Set(muted.map(fold));
  const { findings, duplicatas } = dedupe(candidates);
  const out = { blocks: [], fixNow: [], suggestions: [] };
  const abaixoDoCorte = [];
  let descartados = 0;
  let silenciados = 0;
  for (const f of findings) {
    const conf = confOf(f);
    const classe = classOf(f);
    const atribuicao = normalizeAttribution(f.atribuicao);
    const item = {
      titulo: f.titulo ?? '(sem título)',
      arquivo: f.arquivo,
      porque: f.porque ?? '',
      fonte: f.fonte,
      conf,
      classe,
      atribuicao,
      ...(f.sugestao ? { sugestao: f.sugestao } : {}),
      // Critério de pronto, não a correção: é o que a lente de fechamento usa para
      // decidir "resolvido" por evidência em vez de por semelhança com a sugestão.
      ...(f.verificacao ? { verificacao: f.verificacao } : {}),
      // Rótulo do defeito comum (o invariante violado). O relatório agrupa por ele;
      // os irmãos seguem separados, cada um com o seu local editável.
      ...(f.grupo ? { grupo: f.grupo } : {}),
      ...(f.agentes && f.agentes.length ? { agentes: f.agentes } : {}),
      ...(f.locais && f.locais.length > 1 ? { locais: f.locais } : {})
    };
    if (mutedSet.has(classe)) { silenciados += 1; continue; }
    if (conf < minConf) {
      descartados += 1;
      // Conteúdo preservado, não só contado. Achado abaixo do corte não é achado
      // falso: é achado que a rodada não conseguiu sustentar. O código muda ao
      // redor, a confiança sobe, e sem isso ele só volta se as lentes o
      // redescobrirem do zero — três dos bloqueantes de uma rodada real vieram daí.
      abaixoDoCorte.push({ ...item, ...(f.motivoJuiz ? { motivoJuiz: f.motivoJuiz } : {}) });
      continue;
    }
    if (atribuicao === 'pre-existente') out.suggestions.push(item);
    else if (classe === 'nit' || classe === 'remover') out.suggestions.push(item);
    else if (blockingSet.has(classe)) out.blocks.push(item);
    else out.fixNow.push(item);
  }
  for (const k of BUCKETS) out[k].sort((a, b) => b.conf - a.conf);
  abaixoDoCorte.sort((a, b) => b.conf - a.conf);
  return {
    ...out,
    // Fora de `meta` pelo mesmo motivo das pendências: é material para a próxima
    // rodada, não estatística desta. O relatório declara a contagem e onde ficou.
    ...(abaixoDoCorte.length ? { abaixoDoCorte } : {}),
    meta: {
      candidatos: candidates.length, descartados, duplicatas, minConf,
      blocking: [...blockingSet],
      // silenciados sai no meta para o relatório poder DECLARAR o que ficou de
      // fora. Silêncio sem aviso é pior que cobrança: o humano lê review limpo e
      // conclui que aquilo passou pelo crivo.
      ...(mutedSet.size ? { silenciados, muted: [...mutedSet] } : {})
    }
  };
}

// Frontmatter do relatório de review. Mesmo contrato de formato do `stamp` do run-state.mjs
// (skill sismais-dev): chaves entre aspas, `data-criacao` preservada em recarimbagem, um único
// bloco. As duas implementações são separadas de propósito — moram em plugins diferentes e o
// custo de mais um alvo de sync do core é maior que o das ~15 linhas repetidas.
//
// Existe porque o relatório é lido SOLTO: cai em `<workRoot>/reviews/`, fora do diretório do run,
// e quem o abre (humano ou agente) recebe só o caminho. Sem cabeçalho, não dá para saber de que
// escopo é, contra qual commit rodou, nem se já foi superado por uma rodada posterior.
const FM_BLOCK = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

export function nowIso(now = new Date()) {
  return now.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function stampReport(filePath, meta = {}) {
  const raw = fs.readFileSync(filePath, 'utf8');
  const existing = raw.match(FM_BLOCK);
  const previous = existing ? (existing[1].match(/^data-criacao:\s*"?([^"\n]*)"?\s*$/m) || [])[1] : undefined;
  const now = nowIso();
  const fields = { tipo: 'review' };
  // Campo ausente não vira chave vazia: cabeçalho com `commit: ""` mente mais do que a omissão.
  for (const k of ['escopo', 'modo', 'base', 'commit', 'rodada']) {
    if (meta[k] !== undefined && meta[k] !== null && String(meta[k]) !== '') fields[k] = String(meta[k]);
  }
  fields['data-criacao'] = previous || now;
  fields['data-ultima-modificacao'] = now;
  const block = Object.entries(fields)
    .map(([k, v]) => `${k}: "${v.replace(/"/g, '\\"')}"`)
    .join('\n');
  fs.writeFileSync(filePath, `---\n${block}\n---\n` + raw.replace(FM_BLOCK, '').replace(/^\n+/, ''));
  return fields;
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    const val = argv[i + 1];
    if (val === undefined || val.startsWith('--')) throw new Error(`Argumento sem valor: --${key}`);
    args[key] = val;
  }
  return args;
}

function isMain() {
  return fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || '');
}

if (isMain()) {
  const [cmd, ...rest] = process.argv.slice(2);
  const a = parseArgs(rest);
  if (cmd === 'stamp') {
    stampReport(a.file, {
      escopo: a.escopo, modo: a.modo, base: a.base, commit: a.commit, rodada: a.rodada
    });
    process.stdout.write('ok\n');
  } else if (cmd === 'parse-review') {
    const text = fs.readFileSync(a.file, 'utf8');
    const findings = parseReviewFindingsStrict(text);
    if (findings === null) {
      process.stderr.write('review não parseável: nenhum JSON com blocks/fixNow/suggestions no texto (falha-fechada — não aprove).\n');
      process.exit(2);
    }
    process.stdout.write(JSON.stringify(findings, null, 2) + '\n');
  } else if (cmd === 'bucket') {
    const raw = fs.readFileSync(a.file, 'utf8');
    const candidates = parseCandidatesStrict(raw);
    if (candidates === null) {
      process.stderr.write('candidatos não parseáveis: nenhum JSON com findings[] no texto (falha-fechada — não aprove).\n');
      process.exit(2);
    }
    let findings = candidates;
    let semVeredito = candidates.length;
    let reclassificados = 0;
    let reatribuidos = 0;
    if (a.verdicts) {
      const verdicts = parseVerdictsStrict(fs.readFileSync(a.verdicts, 'utf8'));
      if (verdicts === null) {
        // Sem juiz o pipeline reporta DEMAIS, não de menos — degradar é seguro aqui
        // (o inverso de parse-review, onde a ausência aprovaria indevidamente).
        process.stderr.write('aviso: vereditos não parseáveis — seguindo com a confiança do achador.\n');
      } else {
        ({ findings, semVeredito, reclassificados, reatribuidos } = applyVerdicts(candidates, verdicts));
      }
    }
    const csv = (v) => v.split(',').map((s) => s.trim()).filter(Boolean);
    const result = bucketFindings(findings, {
      blocking: a.blocking ? csv(a.blocking) : DEFAULT_BLOCKING_CLASSES,
      minConf: a['min-conf'] !== undefined ? Number(a['min-conf']) : DEFAULT_MIN_CONF,
      muted: a.muted ? csv(a.muted) : []
    });
    result.meta.semVeredito = semVeredito;
    result.meta.reclassificados = reclassificados;
    result.meta.reatribuidos = reatribuidos;
    const { pendingQuestions, ...extras } = parseExtras(raw);
    Object.assign(result.meta, extras);
    // Fora de `meta` de propósito: pendência aberta é decisão pendente, não
    // metadado de rodada. O loop pausa por ela; o relatório abre seção própria.
    if (pendingQuestions?.length) result.pendingQuestions = pendingQuestions;
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } else {
    process.stderr.write(`comando desconhecido: ${cmd}\n`); process.exit(1);
  }
}
