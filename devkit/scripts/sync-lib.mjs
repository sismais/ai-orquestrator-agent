// Utilitários compartilhados pelo fluxo de sync (pré-voo e inventário de rupturas).
// Determinístico, sem modelo, sem dependência externa: só git + Node.
//
// FONTE ÚNICA: devkit-core/scripts/. As cópias nos consumidores são geradas por
// devkit-core/sync.mjs — não edite as cópias.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

// git pode devolver diff grande; o default de 1MB do spawnSync truncaria calado.
const MAX_BUFFER = 256 * 1024 * 1024;

export const DEFAULT_SYNC_CONFIG = {
  // Ref do outro lado (o que a branch vai trazer de volta). Default: baseBranch da config.
  theirs: null,
  // Caminhos que carregam estado versionado do alvo (migrations, changelogs).
  migrationsPattern: '(^|/)(migrations|migrate|changelog)/',
  // Ruído que nunca deve virar sonda nem entrar na interseção.
  ignorePattern: '(^|/)(node_modules|dist|build|vendor|coverage)/|(^|/)[^/]*\\.(lock|snap|min\\.js|map)$',
  // Decisão 7: cada projeto declara onde a própria bateria mente.
  // Ex.: "npm test puro derruba a suíte nesta máquina — usar npx vitest run --maxWorkers=4".
  armadilhas: [],
  // Comandos proibidos contra o ambiente de trabalho (ex.: reset/push de schema no clone).
  proibidos: []
};

export function resolveSyncConfig(repoRoot) {
  const cfgPath = path.join(repoRoot, '.sismais-dev.json');
  const raw = fs.existsSync(cfgPath) ? JSON.parse(fs.readFileSync(cfgPath, 'utf8')) : {};
  const sync = { ...DEFAULT_SYNC_CONFIG, ...(raw.sync || {}) };
  if (!sync.theirs) sync.theirs = raw.baseBranch || null;
  return { ...raw, sync };
}

export function git(repoRoot, args, { allowFail = false } = {}) {
  const res = spawnSync('git', args, {
    cwd: repoRoot, encoding: 'utf8', maxBuffer: MAX_BUFFER, windowsHide: true
  });
  if (res.error) throw new Error(`git ${args[0]}: ${res.error.message}`);
  if (res.status !== 0 && !allowFail) {
    throw new Error(`git ${args.join(' ')} falhou (${res.status}): ${(res.stderr || '').trim()}`);
  }
  return { code: res.status, stdout: res.stdout || '', stderr: res.stderr || '' };
}

const lines = (s) => s.split(/\r?\n/).filter(Boolean);

export function revExists(repoRoot, rev) {
  return git(repoRoot, ['rev-parse', '--verify', '--quiet', `${rev}^{commit}`], { allowFail: true }).code === 0;
}

export function mergeBase(repoRoot, ours, theirs) {
  return git(repoRoot, ['merge-base', ours, theirs]).stdout.trim();
}

export function countCommits(repoRoot, from, to) {
  return lines(git(repoRoot, ['rev-list', '--count', `${from}..${to}`]).stdout)[0] * 1 || 0;
}

export function changedFiles(repoRoot, from, to, ignoreRe) {
  const out = git(repoRoot, ['diff', '--name-only', '-M', `${from}..${to}`]).stdout;
  return lines(out).filter((f) => !ignoreRe || !ignoreRe.test(f));
}

export function deletedFiles(repoRoot, from, to) {
  return lines(git(repoRoot, ['diff', '--name-only', '--diff-filter=D', '-M', `${from}..${to}`]).stdout);
}

/**
 * Linhas adicionadas e removidas por um lado, com arquivo e linha.
 * `--unified=0` mantém só o que mudou de fato — contexto vira ruído nas sondas.
 */
export function parseDiff(repoRoot, from, to, ignoreRe) {
  const out = git(repoRoot, ['diff', '--unified=0', '--no-color', '-M', `${from}..${to}`]).stdout;
  const added = [];
  const removed = [];
  let oldFile = null;
  let file = null;
  let newLine = 0;
  for (const raw of out.split(/\r?\n/)) {
    if (raw.startsWith('--- ')) {
      const p = raw.slice(4).trim();
      oldFile = p === '/dev/null' ? null : p.replace(/^a\//, '');
      continue;
    }
    if (raw.startsWith('+++ ')) {
      const p = raw.slice(4).trim();
      // Arquivo apagado tem `+++ /dev/null`: sem cair no nome antigo, as linhas removidas
      // (onde moram os símbolos que a branch aboliu) seriam descartadas em silêncio.
      file = p === '/dev/null' ? oldFile : p.replace(/^b\//, '');
      if (file && ignoreRe && ignoreRe.test(file)) file = null;
      continue;
    }
    if (raw.startsWith('@@')) {
      const m = raw.match(/@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      newLine = m ? Number(m[1]) : 0;
      continue;
    }
    if (!file) continue;
    if (raw.startsWith('+') && !raw.startsWith('+++')) {
      added.push({ arquivo: file, linha: newLine, texto: raw.slice(1) });
      newLine++;
    } else if (raw.startsWith('-') && !raw.startsWith('---')) {
      removed.push({ arquivo: file, linha: 0, texto: raw.slice(1) });
    }
  }
  return { added, removed };
}

/**
 * Conflitos textuais previstos SEM tocar na árvore de trabalho (`merge-tree --write-tree`).
 * Git < 2.38 não tem a forma nova: devolvemos null em vez de fingir zero conflito —
 * "não consegui verificar" é resultado válido; zero falso não é.
 */
export function predictConflicts(repoRoot, ours, theirs) {
  const res = git(repoRoot, ['merge-tree', '--write-tree', '--name-only', ours, theirs], { allowFail: true });
  if (res.code !== 0 && res.code !== 1) return null;
  // Formato: OID da árvore, lista de arquivos em conflito, LINHA EM BRANCO, mensagens
  // informativas. A linha em branco é o separador — descartá-la faz "Auto-merging …"
  // entrar na lista como se fosse arquivo.
  const out = res.stdout.split(/\r?\n/);
  if (!out.length || !out[0].trim()) return null;
  const conflicted = [];
  for (const line of out.slice(1)) {
    if (!line.trim()) break;
    conflicted.push(line.trim());
  }
  return conflicted;
}

export function isMigration(file, pattern) {
  return new RegExp(pattern, 'i').test(file);
}

/**
 * Classe 4 do catálogo (dupla linha do tempo): migration do outro lado que, ordenada,
 * cai ANTES da última da nossa branch. Numa base limpa ela roda antes; no ambiente que já
 * aplicou as nossas, rodou depois. Ordem diferente = comportamento diferente.
 */
export function interleavedMigrations(oursMigs, theirsMigs) {
  if (!oursMigs.length || !theirsMigs.length) return [];
  const key = (f) => path.basename(f);
  const maxOurs = oursMigs.map(key).sort().at(-1);
  return theirsMigs.filter((f) => key(f) < maxOurs);
}

export const PORTE_LIMITES = { P: { intersecao: 5, conflitos: 0 }, M: { intersecao: 25, conflitos: 5 } };

export function classificarPorte({ intersecao, conflitos, migrationsAmbosLados, intercaladas }) {
  const c = conflitos ?? Infinity; // conflito não medido não pode rebaixar o porte
  const motivos = [];
  let porte = 'P';
  if (intersecao > PORTE_LIMITES.P.intersecao || c > PORTE_LIMITES.P.conflitos) porte = 'M';
  if (intersecao > PORTE_LIMITES.M.intersecao || c > PORTE_LIMITES.M.conflitos) porte = 'G';
  if (porte !== 'P') motivos.push(`interseção ${intersecao} arquivo(s), ${conflitos ?? 'não medido'} conflito(s) previsto(s)`);
  if (migrationsAmbosLados && porte === 'P') { porte = 'M'; }
  if (migrationsAmbosLados) motivos.push('os dois lados tocaram migrations');
  if (intercaladas > 0) {
    if (porte === 'P') porte = 'M';
    motivos.push(`${intercaladas} migration(s) do outro lado intercalam com as nossas (dupla linha do tempo)`);
  }
  if (!motivos.length) motivos.push('interseção pequena e sem conflito previsto');
  return { porte, motivo: motivos.join('; ') };
}

export function lentesPorPorte(porte) {
  if (porte === 'P') return ['semantica'];
  if (porte === 'M') return ['semantica', 'banco'];
  return ['semantica', 'banco', 'testes'];
}
