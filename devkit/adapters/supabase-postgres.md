# Adaptador de stack: Supabase / Postgres

Concretudes da stack para o fluxo de sync. **Organizado por classe do catálogo** — de
propósito: item que não for a concretude de uma classe do núcleo não é "detalhe do adaptador",
é sinal de classe faltando no catálogo.

Este arquivo fala de **Supabase/Postgres**, não de um projeto. Nomes concretos (qual função
resolve o tenant, qual é a chave de permissão, qual cabeçalho o client injeta) vêm do
`rulesFile` do projeto-alvo — nunca copiados para cá, que envelheceria calado.

Selecionado por `sync.adapter` no `.sismais-dev.json`, ou detectado pela presença de
`supabase/config.toml` / `supabase/migrations/`.

---

## Classe 2 — uso de objeto que a branch removeu

- `DROP FUNCTION` só remove a assinatura exata. Sobrecarga que ficou continua atendendo chamadas
  e esconde a ruptura: confira `pg_proc` quando a função tinha mais de uma forma.
- Função com `SECURITY DEFINER` roda com o dono; com `SECURITY INVOKER`, com quem chamou.
  **Guard dentro de função `SECURITY INVOKER` exige que o chamador tenha `EXECUTE` na função de
  permissão.** Se não tiver, o erro não é "acesso negado" para quem não tem a chave — é
  `permission denied for function` para **todo mundo**. Não é pego por typecheck, lint, smoke
  como dono, nem pelo apply da migration: só por teste rodando como usuário comum.
- Tipos gerados (`types.ts`) são derivados do schema: depois do merge, regenerar contra o banco
  de trabalho. Tipo velho compila e mente.

## Classe 3 — resolução de contexto pela via antiga

- RLS que depende de **cabeçalho HTTP propagado pelo client** (padrão `request.headers` /
  GUC de request) some do teste que não define o cabeçalho: a consulta devolve zero linha e o
  teste passa "verde", inclusive para o dono. Todo teste de RLS desse modelo tem de setar o
  cabeçalho — do contrário está medindo o vazio.
- GUC de transação (`set_config(..., true)`) é o caminho seguro para passar contexto entre
  etapas do mesmo comando: o client não consegue forjá-lo, porque o PostgREST só expõe os GUCs
  com prefixo `request.`.
- Coluna/tabela de sessão substituída continua existindo até o `drop` final. Código do outro
  lado que a lê **funciona** — e passa a ler estado morto. Pior que quebrar.

## Classe 4 — divergência entre linhas do tempo

- O ledger é `supabase_migrations.schema_migrations`, chaveado por **versão** (o timestamp do
  nome do arquivo). Conteúdo não entra na conta: reaplicar não acontece, e editar não repara.
- Nome de migration é timestamp UTC real com segundos reais. Incremento sintético
  (`…120000`, `…120100`) colide entre PRs paralelas e produz ordens diferentes em máquinas
  diferentes.
- Aplicar migration por ferramenta que **carimba a versão do momento** (em vez da versão do
  arquivo) faz o ledger do ambiente divergir do repositório. Depois disso, `db push` acha que
  tudo está pendente e reaplica o mundo. Quando houver essa divergência, aplicar **uma a uma**,
  e declarar o comando proibido em `sync.proibidos`.

## Classe 5 — quebra só na promoção / regra do par

- **`supabase db reset` local (Docker) é a única prova de que a ordem funciona do zero.** É
  seguro: derruba e reconstrói um banco descartável.
- **`supabase db reset` e `db push` contra ambiente com dado são destrutivos ou reaplicam o
  histórico.** Nunca contra o ambiente de trabalho, staging ou produção.
- `create ... if not exists` e `drop ... if exists` escondem divergência entre ambientes: o
  comando passa nos dois e o estado final é diferente. Bom para idempotência da reconciliação,
  péssimo como prova de que os ambientes batem.
- A reconciliação idempotente é `create or replace` / `drop policy if exists` + `create policy`,
  não `alter` cirúrgico — a mesma migration precisa poder rodar num ambiente que já tem a versão
  velha e noutro que não tem nada.

## Classe 6 e 7 — testes

- Suíte SQL costuma exigir **dados de teste aplicados antes, em passo separado** (como a CI
  faz). Rodar os arquivos de teste direto produz falha em massa por FK/RLS que parece defeito do
  sync e não é. Isso vai em `sync.armadilhas`.
- **Dono/owner curto-circuita a checagem de permissão** na maioria dos modelos: o teste que roda
  como dono passa idêntico com e sem a trava. O caso positivo tem de ser usuário **não-dono**
  com papel carregando exatamente a chave — e, quando a chave é FK para um catálogo de
  permissões, chave errada quebra na inserção, o que é uma proteção a mais.
- Teste que consulta tabela com RLS de modelo por cabeçalho **precisa do cabeçalho** (ver
  classe 3).

## Classe 8 — recurso novo sem as travas da branch

- Rota, tela, ação e item de menu novos do outro lado precisam declarar a permissão/limite que
  o projeto passou a exigir. O `rulesFile` diz quais são os portões e como aplicá-los.
- **Edge function** é superfície separada do banco: ganha o próprio `verify_jwt`, o próprio CORS
  e não herda nada da RLS. Cabeçalho novo que o client passou a injetar em toda requisição
  precisa estar no `Access-Control-Allow-Headers` de **cada** função — a que faltar quebra no
  dia da promoção, para todos os tenants ao mesmo tempo, e o navegador reporta como erro de
  CORS, não como erro da função.
- Storage tem política própria por bucket: recurso novo que grava arquivo não é coberto pela
  RLS das tabelas.

---

## Comandos úteis (leitura)

```bash
supabase migration list                 # ledger do ambiente x arquivos do repo
supabase db reset                       # SOMENTE local: prova do fresh-run
supabase functions list                 # superfície de edge functions
```

Escrita (`db push`, `apply_migration`, `functions deploy`) segue a regra de ambiente do
projeto-alvo, declarada no `rulesFile` e em `sync.proibidos`. O fluxo de sync **não** decide
onde escrever.
