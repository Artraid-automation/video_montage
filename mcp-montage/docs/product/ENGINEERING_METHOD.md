# Метод реализации и аудита

Метод адаптирует официальные публичные workflows Cursor Team Kit, а не утверждает доступ к приватному внутреннему stack Cursor.

## Цикл блока

1. Сформулировать проверяемое утверждение: условие, метрика, порог.
2. Зафиксировать acceptance contract и red-тест.
3. Реализовать один ограниченный блок, не меняя смысл acceptance.
4. Сохранить raw evidence: test report, manifests, probes, fault-injection logs.
5. Параллельно отдать один diff двум независимым критикам:
   - correctness, recovery, security, user-visible behavior;
   - architecture, maintainability, boundaries, special cases.
6. Дедуплицировать findings, исправить blockers, повторить тесты и review.
7. Выпустить `audit/Pn-verdict.json` только со статусом `PASS` или `FAIL`.

## Роли

- **Planner:** поддерживает implementation plan и acceptance; не реализует media workers.
- **Worker:** реализует один блок и отдает structured handoff с evidence.
- **Verifier:** пытается опровергнуть acceptance claim; не доверяет отчету worker.
- **Critic A:** ищет функциональные, recovery и security defects.
- **Critic B:** ищет архитектурные долги, ложные abstractions и неуправляемые special cases.

## Пирамида тестов

- L0: contracts, parsers, hashes, state transition matrix, path safety.
- L1: adapters и media workers на synthetic fixtures.
- L2: отдельная интеграция Phase 1–4 с fault injection.
- L3: полный synthetic E2E с обоими human gates и selective rebuild.
- L4: provider canary и затем реальное пользовательское видео.

## Источники практик

- [Cursor: Best practices for coding with agents](https://cursor.com/blog/agent-best-practices)
- [Cursor Team Kit](https://cursor.com/marketplace/cursor/cursor-team-kit)
- [Cursor official plugins repository](https://github.com/cursor/plugins)
- [verify-this](https://github.com/cursor/plugins/blob/main/cursor-team-kit/skills/verify-this/SKILL.md)
- [Thermos dual review](https://github.com/cursor/plugins/tree/main/thermos)
- [Orchestrate](https://github.com/cursor/plugins/tree/main/orchestrate/skills/orchestrate)

Публично нельзя доказать полный приватный prompt/model stack Cursor или использование каждого skill каждым инженером. В проекте фиксируются только проверяемые опубликованные практики.
