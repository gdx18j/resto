# Как запустить проект локально

Проект находится здесь:

```powershell
cd D:\resto_pj\resto
```

## Вариант 1: локально без Docker

Этот вариант уже подготовлен: `.env` создан, зависимости Django установлены, миграции применены.

Запуск сервера:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Открыть в браузере:

```text
http://127.0.0.1:8000
```

Админка:

```text
http://127.0.0.1:8000/admin/
```

Остановить сервер:

```text
Ctrl+C
```

Если нужно создать администратора:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Если запускаешь с нуля

Создать `.env`, если его нет:

```powershell
Copy-Item .env.local.example .env
```

`.env.example` теперь production-шаблон: он специально требует реальные
секреты, SMTP и production-настройки. Для локального запуска используй
`.env.local.example`.

Поставить зависимости, которые нужны для локального SQLite-запуска:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Применить миграции:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Запустить сервер:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

## Вариант 2: через Docker

Сначала запусти Docker Desktop.

Потом из папки проекта:

```powershell
docker compose up --build
```

Открыть:

```text
http://localhost:8000
```

Остановить:

```powershell
docker compose down
```

Полностью сбросить контейнеры и базу PostgreSQL:

```powershell
docker compose down -v
```

Команда с `-v` удаляет все данные базы, поэтому используется только при необходимости полного пересоздания PostgreSQL.

## Важное про DB_HOST

Для Docker не добавляй `DB_HOST=db` в `.env`: compose сам передает это значение
в `web`-контейнер. Если прописать `DB_HOST=db` в `.env`, команды `manage.py` с
хоста начнут пытаться подключаться к Docker DNS-имени `db` и упадут вне
compose-сети.

## Полезные команды

Проверка проекта:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Повторно применить миграции:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Открыть Django shell:

```powershell
.\.venv\Scripts\python.exe manage.py shell
```
