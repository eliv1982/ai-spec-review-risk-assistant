# AI Specification Review & Risk Assistant

Веб-приложение для проверки технических заданий, проектных и бизнес-требований,
feature request'ов и брифов на автоматизацию. Сервис выявляет риски, пробелы и
противоречия, формирует вопросы и измеримые критерии приёмки, а затем применяет
детерминированный контроль качества к структурированному ответу LLM.

**Статус:** MVP завершён, production-развёртывание выполнено и проверено.

Демонстрационный экземпляр: <https://spec-review.elivcloud.org>. Доступ защищён
инфраструктурной Basic Auth в Traefik; учётные данные передаются отдельно и в
репозитории не хранятся.

## Возможности

- создание и хранение документов;
- проверка сохранённого документа или отдельного текста через OpenAI Structured Outputs;
- строгие схемы `ModelReviewDraft` и `FinalReview`;
- backend-only решение `needs_review` с нормализованными `reason_codes`;
- безопасный fallback при техническом сбое LLM;
- история проверок, подробный результат и журнал аудита;
- CSV-экспорт проверок и аудита;
- SQLite-персистентность и воспроизводимый запуск через Docker Compose.

## Архитектура

Проект — модульный монолит: React/Vite frontend обращается к FastAPI API, FastAPI
выполняет LLM-вызов, строгую валидацию, QC, персистентность и аудит, а данные хранятся
в SQLite. В Docker Caddy раздаёт SPA и проксирует `/api` во внутренний контейнер
backend; порт backend на хост не публикуется.

Production-трафик проходит по цепочке:

```text
Internet → Traefik v3.6 → HTTPS / Let's Encrypt → Basic Auth middleware
         → Caddy frontend → /api proxy → FastAPI backend → SQLite volume
```

Подробности: [архитектура](docs/ARCHITECTURE.md),
[модель данных](docs/DATA_MODEL.md), [API-контракты](docs/API_CONTRACTS.md).

## Быстрый запуск — до 10 минут

Оценка до 10 минут предполагает, что Docker и Docker Compose уже установлены,
репозиторий уже клонирован, а для реальных AI-вызовов доступны действующий
`OPENAI_API_KEY` и настроенная через `OPENAI_MODEL` модель OpenAI с поддержкой
используемого Structured Outputs контракта.

1. Из корня репозитория скопируйте шаблон окружения:

   ```bash
   cp .env.example .env
   ```

   В PowerShell используйте `Copy-Item .env.example .env`.

2. Для реальной AI-проверки заполните в `.env` только обязательные значения:

   ```dotenv
   OPENAI_API_KEY=<your-api-key>
   OPENAI_MODEL=<model-with-structured-outputs-support>
   ```

   Остальные локальные значения уже имеют рабочие значения по умолчанию. Никогда не
   добавляйте `.env` в Git.

3. Проверьте конфигурацию и запустите локальный Compose:

   ```bash
   docker compose --env-file .env -f docker-compose.yml -f docker-compose.local.yml config -q
   docker compose --env-file .env -f docker-compose.yml -f docker-compose.local.yml up -d --build
   ```

4. Проверьте API и откройте frontend:

   ```bash
   curl -fsS http://127.0.0.1:8080/api/health
   ```

   Ожидаемый ответ: `{"status":"ok"}`. Интерфейс доступен по адресу
   <http://127.0.0.1:8080/>.

Если порт `8080` занят, задайте в `.env`, например, `APP_PORT=8081`, повторите запуск
и используйте `http://127.0.0.1:8081`. Без `OPENAI_API_KEY` или `OPENAI_MODEL`
приложение и проверка доступности запускаются, но AI-операция вернёт безопасный fallback, а не
реальный результат модели.

## Переменные окружения

### Обязательные для реальных AI-вызовов

| Переменная | Назначение |
| --- | --- |
| `OPENAI_API_KEY` | Ключ OpenAI. Пустое значение не мешает запуску, но приводит AI-проверку к безопасному fallback. |
| `OPENAI_MODEL` | Имя доступной модели OpenAI с поддержкой используемого Structured Outputs контракта. Пустое значение также приводит к fallback. |

### Локальные и значения по умолчанию

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite в `/app/data`; в Compose каталог подключён к volume `app_data`. |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173` | Разрешённые origin'ы для отдельного сервера разработки Vite. Docker frontend обращается к same-origin `/api`. |
| `APP_PORT` | `8080` | Локальная публикация Caddy только на `127.0.0.1`. |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api` | Только для отдельного frontend-запуска; Docker-образ собирается со значением `/api`. Шаблон находится в `frontend/.env.example`. |

### Только production-развёртывание за Traefik

| Переменная | Назначение |
| --- | --- |
| `APP_HOST` | Production hostname без схемы и пути. |
| `TRAEFIK_NETWORK` | Существующая внешняя Docker-сеть Traefik. |
| `TRAEFIK_ENTRYPOINT` | HTTPS entrypoint Traefik, по умолчанию `websecure`. |
| `TRAEFIK_CERTRESOLVER` | Механизм получения сертификатов Traefik, по умолчанию `letsencrypt`. |
| `TRAEFIK_MIDDLEWARES` | Ссылка на уже настроенный middleware, обязательная только с `docker-compose.traefik-auth.yml`. |

Секреты передаются backend через переменные окружения контейнера, не используются как
аргументы сборки и не копируются в образы.

## Примеры API-запросов

Примеры предполагают локальный Docker-запуск на порту `8080`. В Windows при конфликте
с псевдонимом PowerShell используйте `curl.exe` вместо `curl`. Настоящий API-ключ в
команды не передаётся: backend читает его из `.env`.

Проверка доступности:

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

Проверка текста без создания `Document` и `Review`:

```bash
curl -fsS -X POST http://127.0.0.1:8080/api/ai/review -H "Content-Type: application/json" -d '{"title":"Модуль уведомлений","text":"Система должна отправлять пользователю уведомление после подтверждённого события. Требуется определить каналы доставки, правила повторных попыток, сроки хранения истории, ограничения нагрузки, обработку недоступности внешних провайдеров и измеримые критерии успешной доставки."}'
```

Создание документа:

```bash
curl -fsS -X POST http://127.0.0.1:8080/api/documents -H "Content-Type: application/json" -d '{"title":"Требования к уведомлениям","text":"Система должна отправлять уведомления пользователям после наступления настроенного события. Необходимо уточнить каналы, сроки доставки, повторы, мониторинг и хранение истории."}'
```

Ответ содержит `id`. Подставьте его вместо `<document_id>` для сохранённой проверки:

```bash
curl -fsS -X POST http://127.0.0.1:8080/api/documents/<document_id>/review
```

Полный каталог и схемы ответов находятся в [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md).

## Пользовательский сценарий

1. Откройте «Проверить документ», заполните «Название документа» и «Текст документа».
2. Нажмите «Сохранить документ и запустить проверку».
3. После завершения откроется «Результат проверки» с исходным документом, заключением,
   рисками, недостающими требованиями, противоречиями, вопросами, критериями приёмки и
   признаками экспертной проверки.
4. В «История проверок» доступны фильтры по идентификатору документа и необходимости
   экспертной проверки, постраничный список, переход «Открыть результат» и «Скачать CSV».
5. В «Журнал аудита» доступны фильтр статуса, технические детали и «Скачать CSV».
6. На странице результата кнопка «Скачать результат CSV» выгружает полные данные одной
   проверки.

Frontend-маршруты: `/`, `/reviews`, `/reviews/:reviewId`, `/audit`; неизвестный маршрут
показывает русскоязычную страницу 404. Отдельного экрана списка или карточки документов
нет: документ создаётся на главной и показывается внутри результата проверки.

## Безопасный fallback

Технический сбой LLM, транспорта, JSON-разбора или проверки схемы не превращается в
выдуманные риски и требования. Backend формирует фиксированный `FinalReview` с пустыми
находками, `needs_review=true` и техническим reason code. Для сохранённой проверки:

- `Review.error` содержит фиксированное очищенное сообщение для пользователя;
- `Document.status` становится `review_failed`;
- `AuditRun.status` становится `error`;
- конкретная безопасная категория остаётся только в `AuditRun.output_json.llm_error_category`;
- endpoint всё равно возвращает `201`, если fallback-проверка успешно сохранена.

Сырое исключение, ответ провайдера, ключи и содержимое документа не попадают в поля
`error` и снимки аудита.

## CSV-экспорт

Доступны `GET /api/reviews/export`, `GET /api/reviews/{review_id}/export` и
`GET /api/audit-runs/export`. Экспорт использует UTF-8 с BOM, разделитель `;`, окончания
строк `\r\n`, локализованные заголовки и защиту от formula injection. Фильтры совпадают
с соответствующими эндпоинтами списка, пагинация не применяется. Операции доступны
только для чтения и не создают `audit_runs`.

## Проверка качества

Последняя полная автоматическая проверка перед production-развёртыванием:

- backend: `582 passed`;
- frontend: `408 passed`;
- всего: `990 passed`;
- `pip check` — без ошибок;
- линтинг, сборка frontend и `npm ls` — без ошибок;
- сборки Docker и проверка Compose — без ошибок.

Текущее обнаружение тестов на принятом `HEAD` по-прежнему даёт 582 backend-теста и
408 frontend-тестов. Команды для повторного запуска:

```bash
cd backend
pytest
```

```bash
cd frontend
npm run test -- --run
npm run lint
npm run build
```

## Production-развёртывание

Рабочий экземпляр: <https://spec-review.elivcloud.org>.

- HTTPS завершается существующим Traefik v3.6; сертификат выпускается через Let's Encrypt.
- Доступ защищён Basic Auth middleware на уровне Traefik. Учётные данные и их хеши не
  хранятся в репозитории и предоставляются отдельно.
- Прикладная аутентификация и роли намеренно остаются вне границ продукта; инфраструктурная
  Basic Auth не меняет эту границу.
- Traefik направляет hostname на Caddy frontend, Caddy проксирует `/api` в FastAPI.
- Backend не публикует порт хоста.
- SQLite хранится в именованном Docker volume `app_data` и переживает пересоздание
  backend-контейнера.

Production-конфигурация Compose использует базовый файл и два overlay-файла:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.traefik-auth.yml config -q
docker compose --env-file .env -f docker-compose.yml -f docker-compose.traefik.yml -f docker-compose.traefik-auth.yml up -d --build
```

Traefik, DNS и механизм получения сертификатов уже должны существовать во внешней
инфраструктуре; репозиторий их не создаёт. При использовании
`docker-compose.traefik-auth.yml` соответствующий Basic Auth middleware также должен быть
заранее создан во внешней инфраструктуре.

## Документация

- [Границы продукта](PROJECT_SCOPE.md)
- [Документация backend](backend/README.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [API-контракты](docs/API_CONTRACTS.md)
- [Модель данных](docs/DATA_MODEL.md)
- [Схема проверки и QC](docs/REVIEW_SCHEMA.md)
