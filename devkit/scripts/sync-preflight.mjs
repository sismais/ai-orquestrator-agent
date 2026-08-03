// Pré-voo do sync: os fatos que dimensionam o trabalho, antes de qualquer agente.
// Determinístico e barato — o custo do fluxo tem de ser proporcional ao porte do sync.
//
// Uso:
//   node sync-preflight.mjs --repo <path> [--theirs origin/staging] [--ours HEAD]
//
// Saída: JSON no stdout (contrato: devkit-core/schemas/sync-preflight.schema.json).
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  resolveSyncConfig, git, revExists, mergeBase, countCommits, changedFiles,
  predictConflicts, isMigration, interleavedMigrations, classificarPorte, lentesPorPorte
} from './sync-lib.mjs';

/** PRs abertos contra a branch — best-effort: sem `gh` autenticado devolve null, nunca []. */
function prsAbertos(repoRoot, branch) {
  const res = spawnSync('gh', ['pr', 'list', '--base', branch, '--state', 'open', '--json', 'number,title'], {
    cwd: repoRoot, encoding: 'utf8', windowsHide: true
  });
  if (res.error || res.status !== 0) return null;
  try {
    return JSON.parse(res.stdout).map((p) => `#${p.number} ${p.title}`);
  } catch {
    return null;
  }
}

export function preflight(repoRoot, { ours = 'HEAD', theirs = null } = {}) {
  const cfg = resolveSyncConfig(repoRoot);
  const alvo = theirs || cfg.sync.theirs;
  if (!alvo) {
    throw new Error('Não sei qual é o outro lado: passe --theirs ou defina "baseBranch"/"sync.theirs" no .sismais-dev.json');
  }
  if (!revExists(repoRoot, alvo)) throw new Error(`ref inexistente: ${alvo} (fez fetch?)`);

  const ignoreRe = new RegExp(cfg.sync.ignorePattern);
  const base = mergeBase(repoRoot, ours, alvo);
  const nossos = changedFiles(repoRoot, base, ours, ignoreRe);
  const deles = changedFiles(repoRoot, base, alvo, ignoreRe);
  const setDeles = new Set(deles);
  const intersecao = nossos.filter((f) => setDeles.has(f));

  const conflitos = predictConflicts(repoRoot, ours, alvo);
  const migsNossas = nossos.filter((f) => isMigration(f, cfg.sync.migrationsPattern));
  const migsDeles = deles.filter((f) => isMigration(f, cfg.sync.migrationsPattern));
  const intercaladas = interleavedMigrations(migsNossas, migsDeles);

  const { porte, motivo } = classificarPorte({
    intersecao: intersecao.length,
    conflitos: conflitos === null ? null : conflitos.length,
    migrationsAmbosLados: migsNossas.length > 0 && migsDeles.length > 0,
    intercaladas: intercaladas.length
  });

  const branchAtual = git(repoRoot, ['rev-parse', '--abbrev-ref', ours]).stdout.trim();
  const naoVerificado = [];
  if (conflitos === null) naoVerificado.push('conflitos previstos: git sem `merge-tree --write-tree` (>= 2.38) — só o merge real dirá');
  naoVerificado.push('estado do ambiente de trabalho (o que já foi aplicado lá) — o pré-voo lê o repositório, não o alvo');

  const prs = prsAbertos(repoRoot, branchAtual);
  if (prs === null) naoVerificado.push('PRs abertos contra a branch: `gh` indisponível ou não autenticado');

  return {
    version: 1,
    ours: branchAtual,
    theirs: alvo,
    mergeBase: base,
    commits: { nossos: countCommits(repoRoot, base, ours), deles: countCommits(repoRoot, base, alvo) },
    arquivos: { nossos: nossos.length, deles: deles.length, intersecao: intersecao.length },
    intersecao,
    conflitosPrevistos: conflitos,
    migrations: { nossas: migsNossas, deles: migsDeles, intercaladas },
    porte,
    porteMotivo: motivo,
    lentesRecomendadas: lentesPorPorte(porte),
    prsAbertos: prs,
    armadilhas: cfg.sync.armadilhas,
    proibidos: cfg.sync.proibidos,
    naoVerificado
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
  const out = preflight(a.repo || process.cwd(), { ours: a.ours || 'HEAD', theirs: a.theirs || null });
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}
