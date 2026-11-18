# Adrobot backend

Обёртка над Keitaro на FastAPI + SQLAlchemy. Разрабатывается поэтапно.

## Текущий этап

Готова основа backend: конфигурация, жизненный цикл подключения к БД,
миграция таблицы кампаний, проверки доступности и автоматические тесты.
Создание кампаний в Keitaro и редактор пока не реализованы.
Требования и следующие этапы описаны в [docs/backend-plan.md](docs/backend-plan.md).

## Запуск

Нужны Python 3.12–3.14 и [uv](https://docs.astral.sh/uv/getting-started/installation/).
Все команды выполняются из корня репозитория. Версии зависимостей зафиксированы в `uv.lock`.

```sh
uv sync --locked
cp .env.example .env
uv run --locked alembic upgrade head
uv run --locked uvicorn adrobot.main:create_app --factory --reload --host 127.0.0.1
```

По умолчанию используется SQLite, файл `adrobot.db` в текущей директории.
Приложение само не создаёт таблицы: миграции запускаются отдельно.
Секреты и локальная БД исключены из Git. Доступ к Keitaro на этом этапе не требуется.

- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>
- `GET /api/v1/health/live` — процесс отвечает.
- `GET /api/v1/health/ready` — БД доступна и таблица кампаний существует;
  без начальной миграции возвращает 503. Это не проверка подключения к Keitaro.

Настройки читаются из `.env`; переменные окружения имеют приоритет:

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `APP_NAME` | `Adrobot API` | Заголовок OpenAPI |
| `DATABASE_URL` | `sqlite:///./adrobot.db` | SQLAlchemy URL базы |

В этом этапе проверен SQLite. Другие СУБД требуют отдельного драйвера и проверки.

## Проверки

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv run --locked alembic check
```

Тесты создают отдельные временные БД, применяют реальные миграции и не обращаются к Keitaro.
Проверяются готовность до/после миграции, upgrade/downgrade, соответствие схемы моделям,
сохранение, откат незакоммиченных изменений и ограничения таблицы кампаний.

## Миграции

```sh
uv run --locked alembic current
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head
```

Сгенерированную миграцию необходимо проверить перед коммитом.
`alembic downgrade base` удаляет таблицы приложения и их данные — использовать только
для одноразовой тестовой БД. Тест обратной миграции выполняется именно на временной БД.

## Структура

```text
src/adrobot/       приложение, настройки, SQLAlchemy, health API
migrations/       миграции Alembic
tests/            тесты на изолированных SQLite-базах
docs/             требования и план реализации
```
