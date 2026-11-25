# Установленные скиллы для CertDesk

Этот файл документирует скиллы [skills.sh](https://www.skills.sh), установленные для проекта CertDesk. Они расширяют возможности AI-агента (Cline) при работе с этим Django-проектом.

## Список установленных скиллов

| Скилл | Источник | Зачем нужен для CertDesk |
|-------|----------|--------------------------|
| `code-review` | mattpocock/skills | Проверка кода Django-представлений, форм, моделей перед коммитом. Особенно полезен для логики статусов документов (active/expiring/expired/missing) и CSV-импорта. |
| `implement` | mattpocock/skills | Реализация новых фич по спецификации — например, добавление новых типов документов, интеграция с Stripe, AI-извлечение метаданных. |
| `to-spec` | mattpocock/skills | Разработка в соответствии с техническим заданием. Помогает соблюдать архитектурные решения проекта при добавлении нового функционала. |
| `diagnosing-bugs` | mattpocock/skills | Отладка проблем в Django-views, миграциях, загрузке файлов, email-рассылках и вебхуках Stripe. |
| `web-design-guidelines` | vercel-labs/agent-skills | Улучшение UI/UX шаблонов Django (landing, pricing, dashboard, list, detail). Рекомендации по адаптивности и доступности. |

## Где находятся скиллы

Все скиллы установлены на уровне проекта:

```
C:\CertDesk\.agents\skills\
├── code-review\
├── diagnosing-bugs\
├── implement\
├── to-spec\
└── web-design-guidelines\
```

Они автоматически подключены к以下 агентам: Cline, Claude Code, Cursor, Codex, Gemini CLI, GitHub Copilot и другим.

## Как переустановить скиллы

Если нужно переустановить все скиллы с нуля, запустите скрипт:

```powershell
# В папке C:\CertDesk
.\install-skills.ps1
```

Или вручную через `npx`:

```powershell
npx skills add mattpocock/skills --skill code-review --full-depth -y
npx skills add mattpocock/skills --skill implementing --full-depth -y
npx skills add mattpocock/skills --skill to-spec --full-depth -y
npx skills add mattpocock/skills --skill diagnosing-bugs --full-depth -y
npx skills add vercel-labs/agent-skills --skill web-design-guidelines --full-depth -y
```

## Как использовать скилл в работе

При работе над задачей вы можете попросить AI-агента применить конкретный скилл. Например:

- *"Проверь код через code-review перед коммитом"*
- *"Используй diagnosing-bugs, чтобы найти причину ошибки в CSV-импорте"*
- *"Реализуй новую фичу согласно to-spec"*
- *"Улучши UI/dashboard согласно web-design-guidelines"*

## Безопасность

Скиллы запускаются с полными правами агента. Перед использованием новых скиллов рекомендуется ознакомиться с их исходным кодом в `.agents\skills\`.
