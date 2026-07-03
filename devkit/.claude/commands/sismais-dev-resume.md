---
description: Pipeline SDD — retoma um run a partir do run.json.
argument-hint: <feature-slug ou caminho do run.json>
---

Use a skill `sismais-dev` para **retomar** o run indicado: leia o `run.json`, identifique os estágios já concluídos (`stagesCompleted`) e continue do próximo estágio sem refazer os anteriores. Trate `pendingQuestions` primeiro se houver.

Run: $ARGUMENTS
