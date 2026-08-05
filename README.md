# AI Specification Review & Risk Assistant

An assistant that reviews technical specifications, project requirements, feature requests, automation briefs, and business requirements, combining LLM-based analysis with deterministic validation and quality control to flag risks and route uncertain cases for manual review.

Status: In development

## Repository Structure

```
backend/      Backend service (FastAPI, SQLAlchemy, SQLite)
frontend/     Frontend application (React/Vite)
docs/         Project documentation
tests_data/   Sample and test documents
```

## Frontend — локальный запуск

Минимальный интерфейс на React + Vite + TypeScript: создание документа, запуск его
проверки и просмотр сохранённого результата (`FinalReview`).

### Требования

- Node.js 18 или новее (проверено на Node.js 24);
- npm;
- запущенный backend (см. `backend/README.md`), доступный по адресу, указанному в
  `VITE_API_BASE_URL`.

### Установка зависимостей

```bash
cd frontend
npm install
```

### Настройка адреса backend

Скопируйте `frontend/.env.example` в `frontend/.env` и при необходимости измените адрес:

```bash
cp .env.example .env
```

```
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

Если переменная не задана, используется это же значение по умолчанию — адрес backend
при локальном запуске командой `uvicorn app.main:app --reload` из каталога `backend/`.

Допустимо указывать как origin backend (`http://127.0.0.1:8000`), так и полный адрес с
`/api` (`http://127.0.0.1:8000/api`), в том числе с повторёнными сегментами `/api/api`
и с trailing slash или без него. Значение нормализуется
(`frontend/src/api/baseUrl.ts`) так, чтобы итоговый адрес всегда заканчивался ровно
одним `/api` без задвоенных слэшей, а hostname (даже содержащий подстроку `api`,
например `api-host.example`) никогда не изменяется.

Не поддерживаются и отклоняются как ошибка конфигурации (понятное русское сообщение
«Некорректно настроен адрес API.» вместо запуска с потенциально неверным адресом):

* query string (`?...`) и fragment (`#...`) в адресе;
* произвольный посторонний путь, отличный от повторов `/api` (например `/backend`,
  `/v1`);
* относительный адрес (без схемы и хоста) или строка, не являющаяся URL;
* схема, отличная от `http`/`https`.

### Запуск

```bash
npm run dev
```

Frontend будет доступен по адресу `http://localhost:5173` (это же значение уже разрешено
в `BACKEND_CORS_ORIGINS` backend по умолчанию).

### Первый сценарий (E2E)

1. На главной странице (`/`) заполните поля «Название документа» и «Текст документа» и
   нажмите «Создать документ и запустить проверку».
2. Приложение создаёт документ через `POST /api/documents`, затем автоматически
   запускает его проверку через `POST /api/documents/{document_id}/review`.
3. После успешного запуска происходит переход на страницу `/reviews/{review_id}`, где
   отображается сохранённый результат проверки (`FinalReview`): резюме, риски,
   недостающие требования, противоречия, вопросы для уточнения, критерии приёмки,
   `confidence`, `needs_review` и коды причин.

### Тесты, линт и сборка

```bash
npm run test -- --run
npm run lint
npm run build
```
