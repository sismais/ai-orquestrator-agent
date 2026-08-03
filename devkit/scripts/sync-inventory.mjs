// Inventário de rupturas (decisão 2 do design): o que a NOSSA branch aboliu do contrato antigo,
// derivado do próprio diff — e não de uma lista escrita à mão que envelhece.
// Cada ruptura vira uma SONDA contra o outro lado: quem ainda usa o que não existe mais?
//
// Uso:
//   node sync-inventory.mjs --repo <path> [--theirs origin/staging] [--ours HEAD]
//                           [--against diff|worktree]   (default: diff)
//
// `--against worktree` roda DEPOIS do merge: sonda a árvore resultante em vez do diff deles.
// Saída: JSON no stdout (contrato: devkit-core/schemas/sync-inventory.schema.json).
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolveSyncConfig, git, revExists, mergeBase, parseDiff, deletedFiles } from './sync-lib.mjs';

const MAX_TOKENS = 300;
const MAX_HITS = 20;
const MIN_TOKEN = 4;

// Vocabulário de config de lint e de seletor de AST: aparece em toda regra e não é o que a
// branch proibiu. Sem esta lista o inventário afoga a ruptura real (um token) em dez de ruído.
const LINT_STOPWORDS = new Set([
  'error', 'errors', 'warn', 'warning', 'always', 'never', 'message', 'messages',
  'selector', 'selectors', 'options', 'rules', 'rule', 'plugins', 'plugin', 'extends', 'ignore',
  'ignores', 'files', 'paths', 'patterns', 'group', 'groups', 'allow', 'disallow', 'severity',
  'true', 'false', 'null', 'string', 'object', 'array', 'import', 'imports', 'name', 'names',
  // nós ESTree e chaves de seletor
  'literal', 'value', 'identifier', 'property', 'callee', 'arguments', 'source', 'declaration',
  'memberexpression', 'callexpression', 'newexpression', 'importdeclaration', 'objectexpression',
  'variabledeclarator', 'jsxattribute', 'jsxidentifier', 'tsinterfacedeclaration', 'expression'
]);
// Linha de texto humano: a mensagem da regra explica a proibição, não a nomeia.
const LINT_TEXTO_HUMANO = /^\s*["'`]?(message|messages|description|desc|help|hint|label|url|docs)["'`]?\s*:/i;
// Chave de regra (`'no-restricted-syntax': [`): é o nome da regra, não o token proibido.
const LINT_CHAVE = /^\s*(["'`])([^"'`]+)\1\s*:/;

const LINT_FILE = /(^|\/)(\.?eslintrc|eslint\.config|biome|ruff|\.flake8|tslint|stylelint|\.golangci)/i;
// Nome entre aspas pode ter espaço ("Tenant admins can view"). Capturar só o primeiro
// identificador transformaria a política numa sonda pela palavra "Tenant" — que casa com
// meio repositório. O nome citado vale inteiro ou não vale.
const SQL_DROP = /\bdrop\s+(function|procedure|table|view|materialized\s+view|policy|trigger|type|domain|index|column|constraint|sequence|schema)\s+(?:if\s+exists\s+)?(?:"([^"]+)"|'([^']+)'|([a-zA-Z_][\w.$]*))/gi;
const SQL_CREATE = /\bcreate\s+(?:or\s+replace\s+)?(?:unique\s+)?(?:function|procedure|table|view|materialized\s+view|policy|trigger|type|domain|index|sequence|schema)\s+(?:if\s+not\s+exists\s+)?(?:"([^"]+)"|'([^']+)'|([a-zA-Z_][\w.$]*))/gi;
// Identificador que um projeto proíbe é quase sempre COMPOSTO (`sessao_ativa`,
// `useTenantNavigate`). Palavra solta de dicionário vinda da mensagem da regra
// ("empresa", "ativa", "legado") vira sonda que casa com o repositório inteiro.
const COMPOSTO = /_|\.|[a-z][A-Z]/;
// Acima disto o token é genérico demais para ser fila de trabalho — continua no relatório,
// mas marcado, porque descartar calado esconderia um símbolo abolido de uso legítimo amplo.
const HITS_RUIDOSO = 60;
const DEF_PATTERNS = [
  /\bexport\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)/g,
  /\bexport\s+(?:const|let|var|class|interface|type|enum)\s+([A-Za-z_]\w*)/g,
  /\b(?:def|class)\s+([A-Za-z_]\w*)\s*[(:]/g,
  /\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(/g,
  /\bcreate\s+(?:or\s+replace\s+)?(?:function|procedure|view|table)\s+["']?([a-zA-Z_][\w.$]*)["']?/gi
];

function addRuptura(map, tipo, token, origem, evidencia, modo = 'token') {
  const t = String(token).trim();
  if (t.length < MIN_TOKEN) return;
  // Chave é o token, não o par tipo+token: a mesma ruptura pega por duas sondas
  // (o DROP e a regra de lint) é uma ruptura só — duplicar infla o relatório.
  const key = t.toLowerCase();
  if (map.has(key)) return;
  map.set(key, { tipo, token: t, modo, origem, evidencia: evidencia.trim().slice(0, 200), hits: [], hitsTotal: 0 });
}

function matchAll(re, text, fn) {
  re.lastIndex = 0;
  let m;
  while ((m = re.exec(text)) !== null) fn(m);
}

/** Tokens que ainda existem na nossa revisão — não foram abolidos, só movidos/renomeados por perto. */
function tokensVivos(repoRoot, rev, tokens) {
  if (!tokens.length) return new Set();
  const res = spawnSync('git', ['grep', '-F', '-o', '-h', '-f', '-', rev], {
    cwd: repoRoot, encoding: 'utf8', input: tokens.join('\n') + '\n', maxBuffer: 64 * 1024 * 1024, windowsHide: true
  });
  if (res.error || (res.status !== 0 && res.status !== 1)) return new Set();
  const vivos = new Set();
  for (const line of (res.stdout || '').split(/\r?\n/)) {
    const hit = line.includes(':') ? line.slice(line.lastIndexOf(':') + 1) : line;
    if (hit) vivos.add(hit.trim());
  }
  return vivos;
}

function boundary(token, modo = 'token') {
  const esc = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Modo `path`: o nome só conta como referência a arquivo quando vem depois de barra ou
  // aspa (`'./session.js'`, `@/lib/tenant`). Sem isso, um arquivo `tenant.ts` removido vira
  // sonda pela palavra "tenant" e casa com prosa de documentação — 228 hits inúteis num
  // repositório real. Casar pelo caminho de duas pastas também não serve: perde o import
  // relativo, que é justamente quem quebra.
  if (modo === 'path') return new RegExp(`["'\`/]${esc}(\\.[A-Za-z0-9]+)?($|[^A-Za-z0-9_$-])`);
  return new RegExp(`(^|[^A-Za-z0-9_$])${esc}([^A-Za-z0-9_$]|$)`);
}

/** Sonda na árvore resultante (pós-merge), quando o diff deles já não é a pergunta certa. */
function sondarWorktree(repoRoot, rupturas) {
  const tokens = rupturas.map((r) => r.token);
  if (!tokens.length) return;
  const res = spawnSync('git', ['grep', '-n', '-F', '-f', '-'], {
    cwd: repoRoot, encoding: 'utf8', input: tokens.join('\n') + '\n', maxBuffer: 64 * 1024 * 1024, windowsHide: true
  });
  if (res.error || (res.status !== 0 && res.status !== 1)) return;
  for (const line of (res.stdout || '').split(/\r?\n/)) {
    const m = line.match(/^([^:]+):(\d+):(.*)$/);
    if (!m) continue;
    const [, arquivo, linha, texto] = m;
    for (const r of rupturas) {
      if (!boundary(r.token, r.modo).test(texto)) continue;
      r.hitsTotal++;
      if (r.hits.length < MAX_HITS) r.hits.push({ arquivo, linha: Number(linha), trecho: texto.trim().slice(0, 200) });
    }
  }
}

export function inventory(repoRoot, { ours = 'HEAD', theirs = null, against = 'diff' } = {}) {
  const cfg = resolveSyncConfig(repoRoot);
  const alvo = theirs || cfg.sync.theirs;
  if (!alvo) throw new Error('Não sei qual é o outro lado: passe --theirs ou defina "baseBranch"/"sync.theirs" no .sismais-dev.json');
  if (!revExists(repoRoot, alvo)) throw new Error(`ref inexistente: ${alvo} (fez fetch?)`);

  const ignoreRe = new RegExp(cfg.sync.ignorePattern);
  const base = mergeBase(repoRoot, ours, alvo);
  const nosso = parseDiff(repoRoot, base, ours, ignoreRe);

  const map = new Map();

  // (a) objeto de banco removido: o DROP entra como linha ADICIONADA na nossa migration.
  // Drop seguido de recriação (padrão `drop policy` + `create policy`) não é ruptura:
  // o contrato continua de pé, e reportá-lo enterraria as rupturas de verdade em ruído.
  const semEsquema = (nome) => (nome.includes('.') ? nome.split('.').pop() : nome);
  const recriados = new Set();
  for (const l of nosso.added) {
    matchAll(SQL_CREATE, l.texto, (m) => recriados.add(semEsquema(m[1] ?? m[2] ?? m[3]).toLowerCase()));
  }
  for (const l of nosso.added) {
    matchAll(SQL_DROP, l.texto, (m) => {
      const nome = semEsquema(m[2] ?? m[3] ?? m[4]);
      if (recriados.has(nome.toLowerCase())) return;
      addRuptura(map, 'objeto-removido', nome, `${l.arquivo}:${l.linha}`, l.texto);
    });
  }

  // (b) símbolo cuja DEFINIÇÃO sumiu do nosso lado (confirmado depois contra a revisão).
  const candidatosSimbolo = new Map();
  for (const l of nosso.removed) {
    for (const re of DEF_PATTERNS) {
      matchAll(re, l.texto, (m) => {
        const nome = m[1].includes('.') ? m[1].split('.').pop() : m[1];
        if (nome.length >= MIN_TOKEN && !candidatosSimbolo.has(nome)) {
          candidatosSimbolo.set(nome, { origem: l.arquivo, evidencia: l.texto });
        }
      });
    }
  }
  const vivos = tokensVivos(repoRoot, ours, [...candidatosSimbolo.keys()].slice(0, MAX_TOKENS));
  for (const [nome, meta] of candidatosSimbolo) {
    if (vivos.has(nome)) continue;
    addRuptura(map, 'simbolo-removido', nome, meta.origem, meta.evidencia);
  }

  // (c) regra de lint nova: ela DECLARA o que virou proibido — a fonte mais barata que existe.
  for (const l of nosso.added) {
    if (!LINT_FILE.test(l.arquivo)) continue;
    if (LINT_TEXTO_HUMANO.test(l.texto)) continue;
    const chave = l.texto.match(LINT_CHAVE)?.[2];
    matchAll(/["'`]([^"'`]{4,})["'`]/g, l.texto, (m) => {
      if (m[1] === chave) return;
      for (const ident of m[1].match(/[A-Za-z_][\w$]{3,}/g) || []) {
        if (LINT_STOPWORDS.has(ident.toLowerCase())) continue;
        if (!COMPOSTO.test(ident)) continue;
        addRuptura(map, 'regra-nova', ident, `${l.arquivo}:${l.linha}`, l.texto);
      }
    });
  }

  // (d) arquivo removido: quem do outro lado ainda importa/menciona. Sonda em modo `path`.
  for (const f of deletedFiles(repoRoot, base, ours)) {
    if (ignoreRe.test(f)) continue;
    const nome = path.basename(f).replace(/\.[^.]+$/, '');
    addRuptura(map, 'arquivo-removido', nome, f, `arquivo removido: ${f}`, 'path');
  }

  const rupturas = [...map.values()].slice(0, MAX_TOKENS);
  const limites = [
    'Heurística cobre: DROP de objeto de banco, definição exportada que sumiu (JS/TS, Python, Go, SQL), identificador citado em regra de lint nova e arquivo removido. Assinatura alterada sem DROP e renomeação sem remoção NÃO são detectadas.',
    'Em regra de lint só entram identificadores COMPOSTOS (com _, . ou camelCase): proibição de palavra solta (ex.: uma lib chamada "moment") passa batido — o preço de não afogar o inventário em palavras de dicionário.',
    'Sonda é textual: casa o token, não resolve escopo/import — hit é pista para a lente, não veredito.'
  ];
  if (map.size > MAX_TOKENS) limites.push(`Rupturas truncadas em ${MAX_TOKENS} (havia ${map.size}).`);

  if (against === 'worktree') {
    sondarWorktree(repoRoot, rupturas);
  } else {
    const deles = parseDiff(repoRoot, base, alvo, ignoreRe);
    for (const l of deles.added) {
      for (const r of rupturas) {
        if (!boundary(r.token, r.modo).test(l.texto)) continue;
        r.hitsTotal++;
        if (r.hits.length < MAX_HITS) r.hits.push({ arquivo: l.arquivo, linha: l.linha, trecho: l.texto.trim().slice(0, 200) });
      }
    }
  }
  for (const r of rupturas) {
    if (r.hitsTotal > HITS_RUIDOSO) r.ruidoso = true;
    if (r.hitsTotal > r.hits.length) limites.push(`"${r.token}": ${r.hitsTotal} ocorrências, ${r.hits.length} listadas.`);
  }
  if (rupturas.some((r) => r.ruidoso)) {
    limites.push(`Rupturas marcadas com "ruidoso" passam de ${HITS_RUIDOSO} ocorrências: confira o token antes de tratar os hits como fila de trabalho.`);
  }

  const comHits = rupturas.filter((r) => r.hitsTotal > 0);
  return {
    version: 1,
    ours: git(repoRoot, ['rev-parse', '--abbrev-ref', ours]).stdout.trim(),
    theirs: alvo,
    mergeBase: base,
    sondadoContra: against,
    rupturas,
    resumo: {
      rupturas: rupturas.length,
      comHits: comHits.length,
      hitsTotal: rupturas.reduce((s, r) => s + r.hitsTotal, 0)
    },
    limites
  };
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

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || '')) {
  const a = parseArgs(process.argv.slice(2));
  const out = inventory(a.repo || process.cwd(), {
    ours: a.ours || 'HEAD', theirs: a.theirs || null, against: a.against || 'diff'
  });
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}
