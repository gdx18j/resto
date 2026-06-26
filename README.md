# Resto: запуск через Docker

Проект запускается двумя контейнерами:

- `web` - Django-приложение.
- `db` - PostgreSQL 15.

Docker Compose сам создает внутреннюю сеть, поэтому Django подключается к базе по имени сервиса `db`.

## Быстрый запуск

1. Убедитесь, что установлен и запущен Docker Desktop.
2. Откройте терминал в папке проекта:

```powershell
cd D:\resto_pj\resto
```

3. При первом запуске можно оставить готовый `.env` как есть. Если `.env` удален, создайте его из примера:

```powershell
Copy-Item .env.example .env
```

4. Соберите и запустите проект:

```powershell
docker compose up --build
```

5. Откройте приложение:

```text
http://localhost:8000
```

Админка Django доступна здесь:

```text
http://localhost:8000/admin/
```

## Создание администратора

В отдельном терминале выполните:

```powershell
docker compose exec web python manage.py createsuperuser
```

## Остановка проекта

Остановить контейнеры:

```powershell
docker compose down
```

Остановить контейнеры и удалить базу данных вместе с Docker volume:

```powershell
docker compose down -v
```

Команду с `-v` используйте только если нужно полностью сбросить PostgreSQL.

## Полезные команды

Посмотреть логи:

```powershell
docker compose logs -f
```

Запустить миграции вручную:

```powershell
docker compose exec web python manage.py migrate
```

Собрать статику вручную:

```powershell
docker compose exec web python manage.py collectstatic --noinput
```

Открыть Django shell:

```powershell
docker compose exec web python manage.py shell
```

## Какие файлы за что отвечают

`Dockerfile` описывает образ Django-приложения: берет Python, ставит зависимости из `requirements.txt`, копирует проект и назначает `entrypoint.sh` стартовым скриптом.

`docker-compose.yml` описывает два сервиса: `web` с Django и `db` с PostgreSQL. Здесь же настроены порты, переменные окружения, healthcheck базы и Docker volumes для базы, статики и media-файлов.

`entrypoint.sh` выполняется при старте контейнера `web`: ждет доступности PostgreSQL, применяет миграции, собирает static-файлы и запускает Django.

`.env` хранит локальные настройки запуска: порт приложения, имя базы, пользователя, пароль и `DJANGO_SECRET_KEY`. Этот файл не должен попадать в Git.

`.env.example` пример настроек для нового окружения. Его можно копировать в `.env`.

`.dockerignore` исключает из Docker build локальные и временные файлы: `.venv`, `.git`, `.env`, SQLite-базу, кэш Python, собранную статику и прочий мусор.

`requirements.txt` список Python-зависимостей.

`manage.py` стандартная точка входа Django для команд вроде `migrate`, `createsuperuser`, `shell`.

`config/settings.py` основные настройки Django. В Docker приложение использует PostgreSQL, потому что Compose передает `DB_HOST=db`. Без Docker, если `DB_HOST` не задан, Django использует локальный SQLite.

`config/urls.py` маршруты проекта: главная страница и админка.

`main/` Django-приложение с views, models, templates и static-файлами.

## Структура после очистки

```text
resto/
  .dockerignore
  .env
  .env.example
  .gitignore
  Dockerfile
  docker-compose.yml
  entrypoint.sh
  manage.py
  README.md
  requirements.txt
  config/
  main/
```

Папки `staticfiles/`, `mediafiles/` и файл `db.sqlite3` не нужны в репозитории. Docker создает и хранит эти данные через volume.
