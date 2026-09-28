# TVS Analytics — руководство по эксплуатации

## 1. Для кого этот документ

Документ описывает два сценария:

1. локальный запуск на Windows/Linux без Docker;
2. боевой релиз через Docker Compose, PostgreSQL и Redis за HTTPS reverse proxy.

В примерах ниже `tvs` — это короткая запись для запуска:

- Windows: `tvs.bat` (или `.\tvs.bat` в PowerShell);
- Linux/macOS: `./tvs.sh` (сначала один раз `chmod +x tvs.sh`).

При двойном клике по `tvs.bat` открывается меню: `1` — локальный сервер,
`2` — Docker release, `3` — status, `4` — logs, `5` — backup, `6` — safe update,
`7` — checks, `8` — показать главный admin-ключ. Для завершения меню выберите `Q`.

В обоих сценариях общий принцип: **сначала backup, потом обновление, потом миграция, потом health-check**.

## Бренд и совместимость ключей

Сервис называется **TVS — Twitch Viewers System**. Новые ключи создаются в формате
`TVS_` + 128 символов, машинные ключи — `tvs_` + 128 символов.

Старые ключи вида `TVB_` и `tvb_` продолжают работать для совместимости:
существующие админские и пользовательские ключи не нужно перевыпускать. Новые
ключи всегда создаются уже с префиксом `TVS_`. Старая база `data/tvb.db`
продолжает использоваться, если путь прописан в `.env`.

## Команды оператора

| Команда | Назначение |
|---|---|
| `tvs doctor` | проверить Python, `.env`, Docker и production-настройки |
| `tvs up` | поднять release-контур Docker Compose |
| `tvs status` | показать контейнеры и readiness |
| `tvs logs` | смотреть логи в реальном времени |
| `tvs backup` | создать backup SQLite/PostgreSQL |
| `tvs check` | запустить тесты, lint, JS syntax и Alembic check |
| `tvs update` | безопасно обновить build + миграции + health-check |
| `tvs local` | локальный запуск без Docker |
| `tvs show-admin-key` | показать активный главный admin TVS-ключ после подтверждения |
| `tvs restore-sqlite ... --yes` | явное восстановление локальной SQLite DB |

---

## 2. Быстрый старт локально

### Windows

```powershell
.\tvs.bat init
.\tvs.bat doctor
pip install -r requirements.txt
.\tvs.bat local
```

Откройте `http://127.0.0.1:8000/`.

### Linux/macOS

```bash
chmod +x tvs.sh
./tvs.sh init
./tvs.sh doctor
python3 -m pip install -r requirements.txt
./tvs.sh local
```

Команда `local` работает на переднем плане. Останавливается через `Ctrl+C`.

Для локальной работы демо-режим можно включить только явно:

```env
TWITCH_SOURCE=demo
POLLER_ENABLED=0
```

Для реальных данных оставьте:

```env
TWITCH_SOURCE=gql
POLLER_ENABLED=1
```

Не запускайте одновременно `tvs local` и отдельный `python -m app.jobs.run_poller` в локальном режиме: в API уже есть фоновый poller.

---

## 3. Подготовка production-релиза

Production рекомендуется запускать через Docker Compose. На сервере должны быть Docker Engine/Desktop, Docker Compose и HTTPS reverse proxy или Cloudflare Tunnel.

### 3.1. Создать конфигурацию

```bash
cp .env.example .env
```

Windows:

```bat
copy .env.example .env
```

Сгенерировать ключ шифрования:

```bash
python scripts/tvs.py token fernet
```

Сгенерировать первый admin TVS-ключ:

```bash
python scripts/tvs.py token admin
```

Команды печатают секрет один раз в терминал. Сразу перенесите его в защищённое хранилище или `.env`; не отправляйте секрет в Telegram, URL, Referer, issue и логи.

### 3.2. Обязательные production-параметры

В `.env` должны быть примерно такие значения:

```env
APP_ENV=production
PUBLIC_BASE_URL=https://analytics.example.com
ALLOWED_ORIGINS=https://analytics.example.com
COOKIE_SECURE=1
TWITCH_SOURCE=gql
POLLER_ENABLED=1
POSTGRES_PASSWORD=длинный-случайный-пароль
TOKEN_ENCRYPTION_KEY=значение_из_token_fernet
BOOTSTRAP_ADMIN_TOKEN=первый_TVS_ключ
```

`PUBLIC_BASE_URL` и `ALLOWED_ORIGINS` должны соответствовать фактическому origin без лишнего slash.

В production `BOOTSTRAP_ADMIN_TOKEN` нужен только для первого создания admin. После успешного входа и создания рабочих профилей его лучше удалить из `.env`; при следующем запуске уже существующий admin не пересоздаётся.

### 3.3. Постоянные секреты

Никогда не удаляйте и не пересоздавайте:

- `TOKEN_ENCRYPTION_KEY` из production secret manager;
- `data/token.key` в локальной SQLite-версии;
- `.env` с паролем PostgreSQL;
- `backups/`, особенно копии `token.key`.

Смена encryption key без миграции секретов делает старые TVS-ключи нерасшифровываемыми. Для старых секретов предусмотрен audited rotate flow.

### 3.4. Проверить конфигурацию

```bash
tvs doctor
```

Скрипт не выводит значения секретов. Он проверяет наличие Docker, `.env`, production HTTPS/Cookie-настроек и базовых файлов.

---

## 4. Первый запуск release

### Запуск

```bash
tvs up
```

Команда выполняет:

1. build сервисов;
2. запуск PostgreSQL и Redis;
3. запуск API и отдельного poller;
4. ожидание `http://127.0.0.1:8000/readyz`.

### Проверка

```bash
tvs status
tvs logs
```

Ожидаемое состояние:

- `/readyz` отвечает успешно;
- API и poller работают;
- в базе создан bootstrap admin;
- в браузере открывается `/`.

### Первый вход администратора

1. Откройте публичный HTTPS URL.
2. Вставьте bootstrap TVS admin key.
3. В админ-панели создайте отдельный profile key для пользователя.
4. Задайте `unlimited` или allowlist каналов.
5. Передайте пользователю profile key по защищённому каналу.
6. Войдите под profile key и проверьте пустой портфель.

Не используйте admin key как обычный пользовательский ключ.

---

## 5. Как пользоваться сервисом

### 5.1. Добавление каналов

На странице «Портфель» нажмите «Добавить канал» и вставьте каналы в любом из форматов:

```text
https://twitch.tv/streamer
twitch.tv/another_streamer
login_third
```

Можно вставить несколько ссылок через пробел или новую строку. Сервис нормализует login, удаляет дубли и проверяет allowlist/unlimited policy.

После добавления выполняется первый immediate snapshot. Дальше poller обновляет каналы примерно раз в 60 секунд.

### 5.2. Чтение показателей

- **Всего** — значение `viewers` из Twitch.
- **В чате** — наблюдаемое значение `chatters`; это не список ботов.
- **Гости** — `viewers - min(chatters, viewers)`.
- **Ratio** — доля чата, ограниченная сверху 100%;raw-значение доступно в диагностике.
- **Индекс** — explainable risk score, не вероятность накрутки.
- **Confidence** — насколько достаточно наблюдений для уверенной оценки.

Красный флаг `!` означает «проверить канал», а не «забанить канал». Откройте подробный отчёт и вручную сопоставьте его с историей.

### 5.3. История

Раздел «История» показывает:

- график зрителей и людей в чате;
- окна 24 часа, 7 дней и 30 дней;
- последние наблюдения;
- горизонтальный список каналов.

Для списка каналов работают обычное вертикальное колесо и `Shift + колесо` мыши.

График всегда сжимает данные до сетки точек: до 30 точек в портфеле и до 40
точек в истории. Наведите курсор на точку, чтобы увидеть время наблюдения,
количество зрителей и количество людей в чате.

### 5.4. CSV и PDF

В карточке канала:

- «Экспорт CSV» скачивает сырые наблюдения;
- «Отчёт PDF» скачивает отчёт с summary и score factors.

CSV/PDF скачиваются через авторизованный запрос. Не передавайте API-ключ в URL вручную.

### 5.5. Алерты

В разделе «Алерты» доступны правила:

- всплеск зрителей;
- падение доли чата;
- высокий score;
- уход в offline;
- stale data.

Cooldown не позволяет одному правилу создавать одинаковое событие каждый poll. Telegram и webhook требуют отдельной настройки и внешнего smoke test.

### 5.6. API-ключ

В разделе «Вебхуки и API» создайте child key вида `tvs_...`. Он имеет read-only доступ v1 и наследует профиль родительского TVS-ключа.

```http
Authorization: Bearer tvs_...
GET /api/v1/portfolio
```

При revoke/expiry родителя child key также перестаёт работать.

---

## 6. Администрирование

Администратор может:

- создавать profile и admin TVS-ключи;
- задавать expiry;
- редактировать allowlist/unlimited;
- revoke/rotate ключи;
- смотреть audit;
- смотреть request/status/latency/poller charts;
- проверять активные sessions, profiles, channels и API keys.

После операций с секретами всегда проверяйте audit и отдавайте новый ключ только по защищённому каналу.

---

### 6.1 Просмотр главного admin-ключа через BAT

На компьютере, где находится база и encryption key, можно открыть:

```bat
show_admin_key.bat
```

или выбрать пункт `8` в меню `tvs.bat`.

Скрипт:

1. находит первый активный admin TVS-ключ в базе;
2. расшифровывает его локально;
3. просит подтвердить `SHOW`;
4. записывает операцию в audit;
5. печатает ключ в консоль.

Если хост не подключён к PostgreSQL, команда автоматически пытается выполнить
ту же операцию внутри Docker-контейнера API.

Полный ключ не попадает в Docker build, `.env`, URL или логи. Не пересылайте его в чат и не делайте скриншот. Если секрет создан со старым encryption key, расшифровка невозможна — используйте audited rotate flow. Для автоматизированного запуска на доверенной машине есть `tvs show-admin-key --yes`, но интерактивное подтверждение безопаснее.

---

## 7. Безопасное обновление

### Штатная команда

```bash
tvs update
```

Команда делает:

1. `tvs backup`;
2. `git pull --ff-only`, если проект является Git checkout;
3. build образов с `--pull`;
4. `alembic upgrade head`;
5. `up -d --remove-orphans`;
6. health-check.

Если Git-метаданных нет, скрипт не пытается ничего удалять: сначала установите новую release-версию файлов вручную, затем повторите `tvs update`.

### Важные правила

Никогда не делайте при обновлении:

```text
docker compose down -v
docker volume rm ...
rm data/tvs.db
rm data/token.key
git reset --hard
```

Это может удалить базу, профили, ключи или сделать старые секреты нерасшифровываемыми.

### Если health-check не прошёл

1. Не удаляйте volumes.
2. Сохраните логи:

```bash
tvs logs
```

3. Верните предыдущую версию исходников/образа.
4. Запустите сервис без новой миграции.
5. Проверьте backup и при необходимости восстановите SQLite локально.

`tvs update` не делает автоматический rollback, потому что необратимый автоматический откат может скрыть причину сбоя.

---

## 8. Backup и restore

### Backup

```bash
tvs backup
```

Для SQLite создаётся каталог `backups/YYYYMMDD-HHMMSS/`:

- `tvs.db`;
- `token.key`, если файл существует.

Для PostgreSQL создаётся SQL-дамп через контейнер.

Каталог backups нужно хранить на отдельном защищённом носителе. Если в production encryption key находится в secret manager, сохраняйте его отдельно от SQL-дампа.

### Локальный SQLite restore

Сначала остановите локальный сервер. Затем:

```bash
tvs restore-sqlite backups/YYYYMMDD-HHMMSS/tvs.db --yes
```

Скрипт перед restore создаёт дополнительную копию текущей базы.

### PostgreSQL restore

Восстановление PostgreSQL выполняйте процедурой DBA с проверкой резервной копии и версии схемы. Не используйте SQLite restore для PostgreSQL.

---

## 9. Диагностика

| Симптом | Что проверить |
|---|---|
| порт 8000 занят | `tvs status`, затем `netstat -ano | findstr :8000` |
| `422` на `/history` | перезапущен ли сервер после исправления маршрута |
| `409` при reveal | старый secret создан с прежним encryption key; используйте rotate |
| `503` при reveal | проверить secret manager и `TOKEN_ENCRYPTION_KEY` |
| stale channel | `tvs logs`, состояние poller и `TWITCH_SOURCE` |
| нет обновлений | не запущены ли два poller или poller остановился с ошибкой |
| `404 /favicon.ico` | косметический запрос браузера, не ошибка приложения |
| PDF/CSV не открывается | проверить `/api/auth/me`, origin/session и network tab браузера |

---

## 10. Чек-лист безопасного production-релиза

- [ ] Docker и PostgreSQL/Redis доступны.
- [ ] `.env` не попадает в Git/Docker image.
- [ ] `PUBLIC_BASE_URL` и `ALLOWED_ORIGINS` указывают на HTTPS origin.
- [ ] `COOKIE_SECURE=1`.
- [ ] `TOKEN_ENCRYPTION_KEY` хранится в secret manager.
- [ ] `BOOTSTRAP_ADMIN_TOKEN` удалён после первого входа.
- [ ] Создан отдельный profile key для каждого пользователя.
- [ ] Allowlist/unlimited policy настроены осознанно.
- [ ] `tvs backup` проверен и лежит в защищённом месте.
- [ ] `tvs status` и `tvs logs` проверены после запуска.
- [ ] Выполнен real GQL smoke test.
- [ ] Настроены и проверены Telegram/webhook доставки.
- [ ] Есть backup/restore rehearsal.
- [ ] `tvs update` проверен на staging перед production.

---

## 11. Границы сервиса

TVS Analytics — сервис наблюдения и объяснимой аналитики. Он не показывает, какие аккаунты являются ботами, и не доказывает накрутку по одному снимку. Красный индекс — сигнал для ручной проверки. Любое решение о блокировке принимает человек.

Production-ограничения, которые нужно закрыть перед публичным запуском:

- реальный PostgreSQL/Redis прогон;
- shared Redis rate limiter;
- webhook SSRF/egress protection и retries;
- external Telegram/webhook smoke test;
- load/concurrency testing;
- backup restore rehearsal;
- полноценная stream-session model и расширенная score history.
