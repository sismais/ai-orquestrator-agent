// Regra do par (classe 5 do catálogo), mecanizada.
//
// Corrigir uma migration NO ARQUIVO não conserta o ambiente onde ela já rodou: o alvo
// rastreia por VERSÃO, nunca por conteúdo. Toda correção de migration já publicada sai em
// par — a edição no arquivo (base limpa, CI) MAIS uma migration nova de reconciliação
// (ambiente que já aplicou). Entregar metade do par compila, passa no CI e quebra em
// produção; é o erro mais caro e mais silencioso de um sync.
//
// Este script não julga: aponta quais migrations foram editadas depois de publicadas e se
// existe alguma migration nova recriando os mesmos objetos.
//
// Uso:
//   node sync-migrations.mjs --repo <path> [--theirs origin/staging] [--ours HEAD]
//
// Saída: JSON no stdout (contrato: devkit-core/schemas/sync-migrations.schema.json).
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolveSyncConfig, git, revExists, mergeBase, isMigration } from './sync-lib.mjs';

// Objetos que uma migration DEFINE. É por eles que a reconciliação é procurada: o par não é
// "mexeu no mesmo arquivo" (não existe mesmo arquivo — a nova tem outro nome), é "recria o
// mesmo objeto".
const SQL_CREATE = /\b(?:create|alter)\s+(?:or\s+replace\s+)?(?:unique\s+)?(?:function|procedure|table|view|materialized\s+view|policy|trigger|type|domain|index|sequence)\s+(?:if\s+not\s+exists\s+)?(?:"([^"]+)"|'([^']+)'|([a-zA-Z_][\w.$]*))/gi;

/**
 * Caminhos de migration que mudaram entre duas revisões, num único processo git.
 * Perguntar arquivo por arquivo (`git show`) custa um processo por migration — num
 * repositório com centenas delas o script passa de dois minutos e ninguém o roda.
 */
function migrationsPorFiltro(repoRoot, from, to, filtro, pattern) {
  const out = git(repoRoot, ['diff', `--diff-filter=${filtro}`, '--name-only', from, to]).stdout;
  return out.split(/\r?\n/).filter((f) => f && isMigration(f, pattern));
}

function conteudo(repoRoot, rev, file) {
  const res = git(repoRoot, ['show', `${rev}:${file}`], { allowFail: true });
  return res.code === 0 ? res.stdout : null;
}

function objetosDefinidos(sql) {
  const nomes = new Set();
  let m;
  SQL_CREATE.lastIndex = 0;
  while ((m = SQL_CREATE.exec(sql)) !== null) {
    const nome = m[1] ?? m[2] ?? m[3];
    if (nome) nomes.add(nome.includes('.') ? nome.split('.').pop() : nome);
  }
  return [...nomes];
}

function contem(sql, nome) {
  const esc = nome.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(^|[^A-Za-z0-9_$])${esc}([^A-Za-z0-9_$]|$)`).test(sql);
}

/**
 * Onde cada objeto é mencionado entre as migrations novas — um `git grep` só, com todos os
 * nomes de uma vez, em vez de ler o conteúdo de cada candidata.
 */
function mencoes(repoRoot, rev, nomes, paths) {
  const mapa = new Map();
  if (!nomes.length || !paths.length) return mapa;
  const res = spawnSync('git', ['grep', '-n', '-F', '-f', '-', rev, '--', ...paths], {
    cwd: repoRoot, encoding: 'utf8', input: nomes.join('\n') + '\n', maxBuffer: 64 * 1024 * 1024, windowsHide: true
  });
  if (res.error || (res.status !== 0 && res.status !== 1)) return mapa;
  for (const line of (res.stdout || '').split(/\r?\n/)) {
    const m = line.match(/^[^:]*:([^:]+):\d+:(.*)$/);
    if (!m) continue;
    const [, arquivo, texto] = m;
    for (const nome of nomes) {
      if (!contem(texto, nome)) continue;
      if (!mapa.has(nome)) mapa.set(nome, new Set());
      mapa.get(nome).add(arquivo);
    }
  }
  return mapa;
}

/** Para cada migration editada, procura entre as novas do MESMO lado quem recria seus objetos. */
function avaliarPar(repoRoot, rev, editadas, novas) {
  const comObjetos = editadas.map((e) => ({ ...e, objetos: objetosDefinidos(e.sql) }));
  const todosNomes = [...new Set(comObjetos.flatMap((e) => e.objetos))];
  const onde = mencoes(repoRoot, rev, todosNomes, novas);
  return comObjetos.map((e) => {
    const candidatas = [...new Set(e.objetos.flatMap((o) => [...(onde.get(o) || [])]))];
    return {
      arquivo: e.arquivo,
      lado: e.lado,
      objetos: e.objetos,
      parCoberto: candidatas.length > 0,
      reconciliacaoProvavel: candidatas
    };
  });
}

export function migrations(repoRoot, { ours = 'HEAD', theirs = null } = {}) {
  const cfg = resolveSyncConfig(repoRoot);
  const alvo = theirs || cfg.sync.theirs;
  if (!alvo) throw new Error('Não sei qual é o outro lado: passe --theirs ou defina "baseBranch"/"sync.theirs" no .sismais-dev.json');
  if (!revExists(repoRoot, alvo)) throw new Error(`ref inexistente: ${alvo} (fez fetch?)`);

  const pattern = cfg.sync.migrationsPattern;
  const base = mergeBase(repoRoot, ours, alvo);
  // `A` = existe de um lado só (migration nova, ainda não rodou em lugar nenhum: sem par a
  // cobrar). `M` = existe nos dois e o conteúdo difere — ou seja, foi editada DEPOIS de
  // publicada. É essa que precisa do par.
  const novasNossas = migrationsPorFiltro(repoRoot, alvo, ours, 'A', pattern);
  const novasDeles = migrationsPorFiltro(repoRoot, base, alvo, 'A', pattern);

  const editadasPorNos = migrationsPorFiltro(repoRoot, alvo, ours, 'M', pattern)
    .map((f) => ({ arquivo: f, sql: conteudo(repoRoot, ours, f) || '', lado: 'nosso' }));
  const editadasPorEles = migrationsPorFiltro(repoRoot, base, alvo, 'M', pattern)
    .map((f) => ({ arquivo: f, sql: conteudo(repoRoot, alvo, f) || '', lado: 'deles' }));

  const pares = [
    ...avaliarPar(repoRoot, ours, editadasPorNos, novasNossas),
    ...avaliarPar(repoRoot, alvo, editadasPorEles, novasDeles)
  ];
  const semPar = pares.filter((p) => !p.parCoberto);

  return {
    version: 1,
    ours: git(repoRoot, ['rev-parse', '--abbrev-ref', ours]).stdout.trim(),
    theirs: alvo,
    mergeBase: base,
    novas: { nossas: novasNossas, deles: novasDeles },
    pares,
    resumo: { editadas: pares.length, semPar: semPar.length },
    limites: [
      'O par é procurado por MENÇÃO textual aos objetos que a migration editada define — é pista forte, não prova de que a reconciliação está correta ou idempotente.',
      'Migration editada que não define objeto nenhum (só INSERT/UPDATE de dados) sai com `objetos` vazio e nunca acha par: confira à mão.',
      'O script não sabe o que o ambiente já aplicou. Se a versão editada NUNCA rodou em lugar nenhum, editar no arquivo basta e não há par a cobrar.'
    ]
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
  const out = migrations(a.repo || process.cwd(), { ours: a.ours || 'HEAD', theirs: a.theirs || null });
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}
