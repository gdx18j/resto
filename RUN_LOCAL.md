# Как запустить проект локально

Перейди в папку проекта:

```powershell
cd D:\resto_pj\resto
```

## Вариант 1: без Docker

Создай локальный `.env`, если его ещё нет:

```powershell
Copy-Item .env.local.example .env
```

Установи зависимости:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Примени миграции и при необходимости импортируй стартовые данные:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_project_data
```

Запусти сервер:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Сайт: `http://127.0.0.1:8000/`

Админка: `http://127.0.0.1:8000/admin/`

Создание администратора:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Вариант 2: Docker

Сначала запусти Docker Desktop и подготовь `.env`:

```powershell
Copy-Item .env.local.example .env
```

Собери image:

```powershell
docker compose build web
```

Запусти PostgreSQL и Redis:

```powershell
docker compose up -d db redis
```

Примени миграции и собери static через одноразовый release-контейнер:

```powershell
docker compose --profile release run --rm release
```

При первом запуске импортируй стартовые данные явно:

```powershell
docker compose run --rm web python manage.py seed_project_data
```

Запусти приложение:

```powershell
docker compose up -d web
```

Открой `http://localhost:8000/`.

Посмотреть логи:

```powershell
docker compose logs -f web
```

Остановить контейнеры без удаления данных:

```powershell
docker compose down
```

Полностью удалить PostgreSQL, Redis, static и media volumes:

```powershell
docker compose down -v
```

Команда `-v` необратимо удаляет локальные данные и используется только для
полного пересоздания окружения.

## Обновление кода через Docker

После получения новой версии:

```powershell
docker compose build web
docker compose --profile release run --rm release
docker compose up -d web
```

`web` больше не запускает миграции автоматически. Это сделано специально,
чтобы несколько web-контейнеров не меняли схему одновременно.

## Важное про `DB_HOST`

Для Docker не добавляй `DB_HOST=db` в `.env`: Compose передаёт его контейнеру
самостоятельно. Иначе host-side команды `manage.py` начнут искать Docker DNS
имя `db` вне compose-сети.
