# Как запустить проект локально

Проект находится здесь:

```powershell
cd D:\1PythonProjects\resto
```

## Вариант 1: локально без Docker

Этот вариант уже подготовлен: `.env` создан, зависимости Django установлены, миграции применены.

Запуск сервера:

```powershell
.\.venv\bin\python.exe manage.py runserver 127.0.0.1:8000
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
.\.venv\bin\python.exe manage.py createsuperuser
```

## Если запускаешь с нуля

Создать `.env`, если его нет:

```powershell
Copy-Item .env.example .env
```

Поставить зависимости, которые нужны для локального SQLite-запуска:

```powershell
.\.venv\bin\python.exe -m pip install --no-cache-dir asgiref==3.11.1 Django==5.2.15 python-dotenv==1.2.2 sqlparse==0.5.5 typing_extensions==4.15.0 tzdata==2026.2
```

Применить миграции:

```powershell
.\.venv\bin\python.exe manage.py migrate
```

Запустить сервер:

```powershell
.\.venv\bin\python.exe manage.py runserver 127.0.0.1:8000
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

## Что сейчас не получилось

Docker установлен, но daemon сейчас недоступен. Ошибка была такая: Docker client не может подключиться к `docker_engine`.

Обычно это значит одно из двух:

- Docker Desktop не запущен.
- Docker Desktop запущен, но терминал/права Windows не дают подключиться к daemon.

Для быстрого локального запуска используй вариант без Docker выше.

## Полезные команды

Проверка проекта:

```powershell
.\.venv\bin\python.exe manage.py check
```

Повторно применить миграции:

```powershell
.\.venv\bin\python.exe manage.py migrate
```

Открыть Django shell:

```powershell
.\.venv\bin\python.exe manage.py shell
```
