# Frontend — React Dashboard

Скелет за структурою Фази 0.3 плану. Реалізація dashboard — Фаза 1
(таблиця спредів, фільтри, статуси з'єднань, stale-індикація).

Стек (заплановано): React + TypeScript + Vite. Ініціалізація toolchain
виконується на початку Фази 1:

```bash
npm create vite@latest . -- --template react-ts
```

Вимоги плану до UI (Фаза 1, п.10):

- Order Book з'являється справа тільки після відкриття конкретної пари.
- Загальний екран не масштабується жестом zoom; дозволений тільки
  вертикальний скрол.
- Пауза UI не зупиняє backend.

## PWA ("Додати на екран Домівки" на iPhone)

`public/manifest.webmanifest` + `public/sw.js` + іконки в `public/icons/`
роблять із дашборду встановлювану PWA. Service worker кешує лише
статичну оболонку (HTML/JS/CSS/іконки) — `/api/*`, `/ws`, `/health`
свідомо НЕ кешуються, завжди йдуть напряму в мережу (котирування/спред/
баланс не можуть бути stale). Реєструється лише в production-збірці
(`npm run build`), вимагає HTTPS (крім localhost) — на iPhone Safari без
секурного контексту PWA не встановиться. Повний runbook розгортання на
VPS без Docker — [docs/operations/vps-deploy-no-docker.md](../docs/operations/vps-deploy-no-docker.md).
