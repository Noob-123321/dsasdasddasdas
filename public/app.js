/* TVS Analytics (Twitch Viewers System) dependency-light SPA. */
(() => {
  'use strict';

  const app = document.getElementById('app');
  const state = {
    user: null,
    view: 'portfolio',
    overview: null,
    selected: null,
    history: null,
    historyChannel: null,
    historyRange: 24,
    detection: null,
    detectionRoster: null,
    detectionChannel: null,
    detectionHours: 168,
    statusFilter: 'all',
    lang: localStorage.getItem('tvs_lang') || 'ru',
    filter: '',
    adminTab: 'overview',
    showRevoked: false,
    adminData: null,
    config: null,
    refreshTimer: null,
  };

  const I18N = {
    ru: {
      sign_in: 'Войдите по ключу',
      sign_in_sub: 'Вставьте лицензионный ключ TVS, чтобы открыть свой портфель стримеров и подробную аналитику.',
      access_key: 'Ключ доступа',
      show: 'Показать',
      hide: 'Скрыть',
      open_portfolio: 'Открыть портфель',
      checking: 'Проверяем…',
      enter_key: 'Введите ключ.',
      need_key: 'Нужен ключ? Обратитесь к администратору.',
      api_docs: 'Документация API',
      portfolio: 'Портфель',
      history: 'История',
      alerts: 'Алерты',
      api: 'Вебхуки и API',
      settings: 'Настройки',
      admin: 'Админ-панель',
      operations: 'Operations',
      workspace: 'Workspace',
      sign_out: 'Выйти',
      updated: 'Обновлено',
      add_channel: '＋ Добавить канал',
      add_channel_btn: 'Добавить канал',
      portfolio_empty: 'Портфель пуст',
      portfolio_empty_desc: 'Добавьте одного или нескольких Twitch-стримеров. Можно вставить ссылки в одно поле — мы сами нормализуем имена и запустим наблюдение.',
      loading_data: 'Загружаем данные',
      loading_portfolio: 'Загружаем портфель',
      loading_history: 'Загружаем историю канала',
      loading_alerts: 'Загружаем алерты',
      loading_api: 'Загружаем API-ключи',
      loading_admin: 'Загружаем админку',
      search_channel: 'Найти канал…',
      all: 'Все',
      live: 'Live',
      flagged_tab: 'Подозрительные',
      kpi_channels: 'Каналов в списке',
      kpi_total_viewers: 'Суммарно зрителей',
      kpi_flagged: 'Помечено флагом',
      kpi_refresh: 'Обновление',
      kpi_live: 'сейчас в эфире',
      kpi_sec: 'сек',
      kpi_bg: 'фоновый poller · 60 сек',
      detail_title: (l, d) => `${l} — история зрителей и чата`,
      detail_sub: (d) => `последние сохранённые наблюдения`,
      chart_viewers: 'Всего зрителей',
      chart_in_chat: 'В чате (примерно)',
      chart_viewers_word: 'зрителей',
      chart_flat: 'Ровные участки означают, что Twitch не изменил счётчик между наблюдениями; это не ошибка графика.',
      risk_breakdown: 'Разбор индекса',
      collect_more: 'Соберите ещё несколько наблюдений, чтобы увидеть объяснение индекса.',
      confidence: 'Confidence',
      observations: 'наблюдений',
      provisional: 'предварительно',
      admin_tvs_keys: 'Ключи TVS',
      admin_sub: 'Токены, политики, аудит и нагрузка сервера.',
      create_key: '＋ Создать ключ',
      token: 'Токен',
      type: 'Тип',
      expiry: 'Срок',
      status: 'Статус',
      actions: 'Действия',
      rotate: 'Перевыпустить',
      show_btn: 'Показать',
      change: 'Изменить',
      key_created: 'Ключ создан',
      copy: 'Копировать',
      remove_confirm_prefix: 'Убрать #',
      remove_confirm_suffix: ' из портфеля?',
      loading_error: 'Ошибка загрузки',
      your_keys: 'Ваши ключи',
      no_api_keys_yet: 'API-ключей пока нет',
      create_readonly_key: 'Создайте read-only ключ для интеграции.',
      how_to_use: 'Как использовать',
      same_access: 'Один и тот же доступ, другой интерфейс',
      api_inheritance: 'Ключ <span class="inline-code">tvs_…</span> наследует список стримеров и историю родительского профиля. Передавайте его только в заголовке <span class="inline-code">Authorization: Bearer</span>.',
      api_expiry: 'Срок API-ключа ограничен сроком TVS. Отзыв родителя автоматически отключает все дочерние ключи.',
      api_example: 'GET /api/v1/channels/tumblurr/snapshot\nAuthorization: Bearer tvs_…',
      requests_used: 'запросов',
      created_label: 'создан',
      status_active: 'активен',
      reveal: 'Показать',
      revoke: 'Отозвать',
      new_api_key_title: 'Новый API-ключ',
      new_api_key_desc: 'Он получит доступ только к данным текущего профиля.',
      key_name_label: 'Название',
      key_name_default: 'Интеграция',
      key_created_once: 'Ключ показывается один раз после создания. Сохраните его в менеджере секретов.',
      created_heading: 'Ключ создан',
      copy_btn: 'Копировать',
      secret_hidden: 'Это значение больше не показывается в списке.',
      done_btn: 'Готово',
      revoke_confirm: 'Отозвать этот API-ключ?',
      api_key_revoked: 'API-ключ отозван',
      new_rule_title: 'Новое правило',
      new_rule_desc: 'Событие будет сохранено в ленте алертов профиля.',
      rule_type_label: 'Тип',
      rule_type_spike: 'Всплеск зрителей',
      rule_type_ratio: 'Падение доли чата',
      rule_type_stale: 'Нет свежих данных',
      rule_type_offline: 'Канал ушёл офлайн',
      threshold_label: 'Порог',
      threshold_hint: 'Для «Всплеск зрителей» укажите, во сколько раз выросло значение. Для «Падение доли чата» — минимальный порог доли.',
      cancel_btn: 'Отмена',
      create_btn: 'Создать',
      rule_created: 'Правило создано',
      policy_title: 'Политика профиля',
      policy_unlimited: 'Разрешить любые публичные Twitch-каналы',
      allowlist_label: 'Allowlist каналов',
      allowlist_placeholder: 'tumblurr pesh',
      allowlist_hint: 'При включённом unlimited список можно оставить пустым.',
      save_policy_btn: 'Сохранить политику',
      policy_updated: 'Политика профиля обновлена',
      edit_key_title: 'Изменить ключ',
      edit_label: 'Название',
      edit_expiry: 'Новый срок (пусто = бессрочный)',
      save_btn: 'Сохранить',
      key_updated: 'Срок и название обновлены',
      create_token_title: 'Создать TVS-ключ',
      create_token_desc: 'Ключ можно открыть в портфеле или выдать администратору.',
      token_kind_label: 'Тип ключа',
      token_kind_profile: 'Профиль',
      token_kind_admin: 'Администратор',
      token_label: 'Название',
      token_label_default: 'Новый профиль',
      token_expiry: 'Срок (пусто = бессрочный)',
      token_unlimited: 'Без ограничений по каналам',
      token_created_note: 'Секрет можно снова показать в таблице токенов; действие попадёт в аудит.',
      reveal_api_title: 'Показать API-ключ',
      reveal_token_title: 'Показать секрет',
      audit_event: 'Событие записано в аудит.',
      secret_security: 'Не отправляйте секрет в URL или сторонний чат.',
      rotate_title: 'Перевыпустить ключ',
      rotate_warning: 'Старый ключ будет отозван, а вместо него будет создан новый TVS-ключ с тем же профилем и настройками. Дочерние API-ключи старого TVS также перестанут работать.',
      rotate_btn: 'Перевыпустить',
      rotate_done: 'Новый ключ показывается один раз. Старый ключ уже отозван.',
      rotated_label: 'этот ключ',
      webhook_title: 'Добавить webhook',
      webhook_desc: 'События будут подписываться HMAC и отправляться на HTTPS endpoint.',
      webhook_url_label: 'HTTPS URL',
      webhook_url_placeholder: 'https://example.com/tvs-hook',
      webhook_secret_label: 'Подпись secret (минимум 16 символов)',
      webhook_hint: 'Приватные IP, localhost и не-HTTPS адреса запрещены.',
      add_btn: 'Добавить',
      webhook_added: 'Webhook добавлен',
      copied: 'Скопировано',
      copy_manual: 'Скопируйте текст вручную',
      admin_sessions: 'активных сессий',
      admin_profiles: 'активных профилей',
      admin_channels: 'активных каналов',
      admin_api_keys: 'API-ключей',
      statuses_title: 'Статусы ответов',
      statuses_sub: 'Распределение HTTP-кодов текущего процесса',
      routes_title: 'Топ маршрутов',
      routes_sub: 'Количество запросов по endpoint',
      poller_title: 'Poller и задержка',
      poller_sub: 'Состояние фонового сбора',
      polls_count: 'опросов',
      errors_count: 'ошибок',
      p95_latency: 'p95 latency',
      poller_success_hint: 'Зелёная доля — успешные циклы; красная — ошибки poller.',
      tokens_tab: 'Токены',
      profiles_tab: 'Политики',
      audit_tab: 'Аудит',
      load_tab: 'Нагрузка',
      hide_revoked: 'Скрыть отозванные',
      show_revoked: 'Показать отозванные',
      key_col: 'Ключ',
      type_col: 'Тип',
      profile_col: 'Профиль',
      mode_col: 'Режим',
      expiry_col: 'Срок',
      status_col: 'Статус',
      actions_col: 'Действия',
      profile_name_col: 'Профиль',
      channels_col: 'Каналы',
      mode_col_short: 'Режим',
      last_activity_col: 'Последняя активность',
      time_col: 'Время',
      actor_col: 'Actor',
      action_col: 'Действие',
      object_col: 'Объект',
      request_col: 'Request',
      load_title: 'Нагрузка приложения',
      load_sub: 'Последних запросов',
      active_sessions_label: 'Активные сессии',
      active_profiles_label: 'Активные профили',
      active_channels_label: 'Активные каналы',
      api_keys_label: 'API ключи',
      p50_latency: 'p50 latency',
      error_rate: 'Error rate',
      mode_unlimited: 'unlimited',
      mode_allowlist: 'allowlist',
      active_channels: 'Активные каналы',
      add_and_start: 'Добавить и запустить',
      add_channels_desc: 'Вставьте ссылки или логины Twitch. Они могут быть разделены пробелами и переводами строк.',
      add_channels_modal: 'Добавить каналы',
      alerts_sub: 'Понятные правила и события наблюдения.',
      all_channels: 'Все каналы',
      all_profile_channels: 'все добавленные профилем',
      api_requests: 'API запросы',
      api_sub: 'Создавайте машинные ключи из профиля. Они живут, пока действует TVS.',
      audit: 'Аудит',
      bg_poller_60: 'фоновый poller · 60 сек',
      cancel: 'Отмена',
      channel: 'Канал',
      channel_history: 'История каналов',
      channel_history_sub: 'Отдельный просмотр наблюдений, аномалий и причин индекса.',
      channel_mode: 'Режим каналов',
      channel_offline_note: 'Канал сейчас офлайн. График появится после следующего live-наблюдения.',
      channels_tracked: 'Каналов в списке',
      chart_note: 'Ровные участки означают, что Twitch не изменил счётчик между наблюдениями; это не ошибка графика.',
      create_api_key_desc: 'Добавьте порог всплеска или отсутствия данных, чтобы получать события.',
      currently_live: 'сейчас в эфире',
      d_ago: 'д назад',
      days_30: '30 дней',
      days_7: '7 дней',
      demo_note: 'Показан <strong>демо-режим</strong>: цифры синтетические и не отражают Twitch. Для реальных данных установите TWITCH_SOURCE=gql и перезапустите poller.',
      detailed_report: 'Подробный отчёт',
      docs: 'Документация',
      docs_desc: 'Полный OpenAPI доступен на сервере. Там есть схемы, ошибки, лимиты и примеры curl/Python/JavaScript.',
      download_fail: 'Не удалось скачать файл',
      event_feed: 'Последние события',
      events: 'событий',
      expiry_date: 'Срок действия',
      export_csv: 'Экспорт CSV',
      flag: 'флаг',
      flagged: 'Помечено флагом',
      for_devs: 'Для разработчиков',
      freshness: 'Свежесть',
      guests: 'Гости',
      h_ago: 'ч назад',
      high_risk: 'высокий риск',
      hours_24: '24 часа',
      in_chat: 'В чате',
      in_chat_approx: 'В чате (примерно)',
      in_chat_word: 'и чата',
      increased_attention: 'повышенное внимание',
      index: 'Индекс',
      insufficient_data: 'Данных пока недостаточно для вывода.',
      label: 'Название',
      last_cycle: 'последний цикл',
      live_status: 'в сети',
      load: 'Нагрузка',
      min_ago: 'мин назад',
      monitoring: 'наблюдение',
      na: 'н/д',
      new_rule: '＋ Новое правило',
      no_data: 'нет данных',
      no_events_yet: 'Пока нет правил',
      no_history: 'История ещё не накопилась.',
      no_numeric: 'Нет числовых наблюдений',
      normal: 'норма',
      obs_after_poller: 'Наблюдения появятся после следующего цикла poller.',
      offline_status: 'офлайн',
      open_api_docs: 'Открыть API docs ↗',
      open_history: 'Открыть историю',
      picker_hint: 'Каналы истории. Используйте Shift и колесо мыши',
      policies: 'Политики',
      poller_status: 'Статус poller',
      portfolio_rules: 'Правила',
      profile: 'Профиль',
      profile_tvs_details: 'Данные текущего TVS-ключа',
      profiles_count: 'профилей',
      ratio: 'Доля чата',
      reasons: 'Причины',
      recent_obs: 'Последние наблюдения',
      refresh: 'Обновить',
      refresh_rate: 'Обновление',
      report_pdf: 'Отчёт PDF',
      restricted_profile_note: 'Профиль с ограничением пропустит только разрешённые администратором каналы.',
      retry: 'Повторить',
      rule_offline: 'Канал ушёл офлайн',
      rule_ratio: 'Падение доли чата',
      rule_score: 'Высокий индекс',
      rule_spike: 'Всплеск зрителей',
      rule_stale: 'Нет свежих данных',
      rule_test: 'Тестовое событие',
      rules_count: 'активно',
      score_above_60: 'score выше 60',
      sec_30: '30 сек',
      sec_ago: 'сек назад',
      service_down: 'Сервис временно недоступен',
      session_expired: 'Сессия истекла. Введите ключ снова.',
      settings_sub: 'Профиль, доступ и документация.',
      stale: 'устарело',
      stream: 'Эфир',
      streamer_links: 'Ссылки на стримеров',
      time: 'Время',
      tokens: 'Токены',
      total: 'Всего',
      total_viewers: 'Суммарно зрителей',
      total_viewers_chart: 'Всего зрителей',
      trend: 'Динамика',
      unlimited: 'Без ограничений',
      viewers: 'зрителей',
      warning: 'внимание',
      webhooks_and_api: 'Вебхуки и API',
      welcome: 'Добро пожаловать',
      no_chart_data: 'Нет данных для графика',
      chart_top_n: 'Показаны первые',
      chart_of_total: 'из',
      portfolio_title: 'Портфель каналов',
      portfolio_subtitle: 'Наблюдение, аномалии и свежесть данных в одном экране.',
      new_api_key_btn: '＋ Новый API-ключ',
      detail_chart_title: 'история зрителей и чата',
      in_chat_short: 'в чате',
      chat_capped_note: 'Twitch показал больше людей в чате, чем зрителей, поэтому значение ограничено числом зрителей.',
      chart_shared_scale: 'Обе линии используют одну шкалу, поэтому расстояние между ними равно разнице в людях.',
      explain_score: 'Индекс описывает необычность наблюдаемого поведения, а не вероятность накрутки. Решение остаётся за человеком. {detail}',
      explain_score_enough: 'Данных достаточно для предварительного сравнения.',
      warn_low_confidence: 'данных мало, оценка предварительная',
      warn_no_chat_data: 'не хватает данных о чате',
      note_low_ratio: 'медиана доли чаттеров {ratio}',
      note_spike_amplitude: 'наибольший всплеск x{amplitude}',
      note_sawtooth: '{changes} смен направления',
      factor_low_ratio: 'Низкая доля чата',
      factor_spike_no_chat: 'Всплеск без роста чата',
      factor_sawtooth: 'Резкие колебания',
      factor_category_outlier: 'Отклонение категории',
      no_factors_yet: 'Для этого канала ещё недостаточно факторов. Продолжайте наблюдение.',
      need_more_observations: 'Нужны дополнительные наблюдения',
      suspicious_anomaly: 'Подозрительная аномалия',
      title_unavailable: 'Название недоступно',
      request_failed: 'Ошибка запроса',
      nav_admin: 'Административная навигация',
      nav_main: 'Основная навигация',
      modal_close: 'Закрыть',
      hours_short: 'ч',
      adding: 'Добавляем…',
      add_and_start_short: 'Добавить и запустить',
      added_summary: 'Добавлено: {added}. Повторов: {duplicates}.{rejected}',
      rejected_summary: ' Запрещено: {rejected}.',
      channel_removed: '#{login} убран из портфеля',
      rule_enabled: 'включено',
      rule_disabled: 'выключено',
      poller_off: 'Poller выключен.',
      trend_aria: 'Динамика канала',
      chart_aria: 'История зрителей и людей в чате',
      done_btn_short: 'Готово',
      rotate_note: 'старый секрет нельзя восстановить',
      lang_badge: 'Русский',
      guide_title: 'Как работают алерты',
      guide_sub: 'Это сигналы для проверки, а не автоматический бан',
      guide_spike: 'Всплеск зрителей',
      guide_spike_desc: 'Сравниваем новый пик с предыдущим наблюдением.',
      guide_ratio: 'Падение доли чата',
      guide_ratio_desc: 'Смотрим, не остались ли зрители без людей в чате.',
      guide_stale: 'Нет данных',
      guide_stale_desc: 'Предупреждаем, если poller не обновлял канал.',
      guide_offline: 'Офлайн',
      guide_offline_desc: 'Фиксируем переход канала из эфира в офлайн.',
      guide_footer: 'Cooldown не позволяет одному и тому же правилу создавать много одинаковых событий. Красный знак у канала означает высокий индекс; наведите курсор или нажмите знак, чтобы увидеть причины.',
      downloading: 'Файл {file} скачивается',
      severity_high: 'высокая',
      severity_warning: 'внимание',
      severity_info: 'инфо',
      detection: 'Детекция накрутки',
      detection_sub: 'Форма кривой, поведение чата и выборка аккаунтов. Индекс описывает необычность поведения, а не вероятность ботов.',
      loading_detection: 'Считаем детекцию накрутки',
      detection_verdict: 'Вердикт',
      detection_series: 'Развёрнутый по минутам ряд',
      detection_confidence_parts: 'Из чего сложилась уверенность',
      detection_availability: 'доступность',
      detection_window: 'Окно',
      detection_hours: 'часов',
      detection_points: 'точек',
      detection_gaps: 'пропусков',
      detection_factors: 'Сработавшие признаки',
      detection_signals: 'сигналов',
      detection_quiet: 'Ни один признак не сработал.',
      detection_quiet_detail: 'Это не гарантия честного онлайна: часть метрик зависит от выборки и объёма наблюдений.',
      detection_chart_title: 'кривая онлайна по минутам',
      detection_chart_note: 'Ряд развёрнут по минутам: значения держатся до следующего изменения, пропуски poller показаны разрывом.',
      event_spike: 'Скачок онлайна',
      event_ad: 'Признак рекламы (прокси)',
      event_change: 'Смена названия или категории',
      event_stream: 'Граница эфира',
      event_stream_start: 'эфир начался',
      event_stream_end: 'эфир закончился',
      events_thinned: 'Событий больше 25: показаны не все.',
      detection_rate_title: 'Активность чата (прокси)',
      detection_rate_sub: 'Анонимный клиент не читает сообщения: это изменение числа активных авторов, а не счётчик реплик.',
      detection_rate_per_minute: 'Изменение в минуту',
      detection_rate_stale: 'Минут без изменений',
      detection_rate_source: 'Источник',
      detection_ad_title: 'Реклама: сравнение окон',
      detection_ad_proxy: 'Анонимный клиент не читает adBreak, поэтому это инференциальная оценка по косвенным признакам.',
      detection_ad_none: 'Рекламные паузы не обнаружены, сравнение недоступно.',
      detection_ad_window: 'Окна рекламных пауз',
      detection_ad_rest: 'Остальное время',
      detection_minutes: 'минут',
      detection_growth: 'рост',
      detection_no_breaks: 'перерывов не найдено',
      detection_unavailable: 'Отчёт детекции недоступен. Проверьте данные канала и повторите позже.',
      detection_unavailable_title: 'Недоступные метрики',
      detection_unavailable_sub: 'Отсутствие данных понижает уверенность, а не саму оценку.',
      detection_warnings: 'Ограничения и предупреждения',
      detection_evidence: 'Доказательства: выборка чаттеров',
      detection_evidence_sub: 'До 100 логинов из CommunityTab, обогащённых users(logins:)',
      detection_no_sample: 'Выборка чаттеров ещё не собрана.',
      detection_sampled: 'сэмпл',
      detection_enriched: 'обогащено',
      detection_accounts: 'аккаунтов',
      detection_enrich_pending: 'Обогащение аккаунтов появится после следующего цикла poller.',
      chatter_col: 'Аккаунт',
      age_days_col: 'Возраст, дней',
      followers_col: 'Подписчиков',
      created_col: 'Создан',
      followers_label: 'подписчиков',
      detect_not_probability: 'Оценка описывает необычность поведения, а не вероятность ботов.',
      detect_no_observations: 'В выбранном окне нет наблюдений, оценка невозможна.',
      detect_explain: 'Детекция сопоставляет форму кривой, поведение чата и выборку аккаунтов с собственными наблюдениями канала. {detail}',
      unavailable_series: 'нет наблюдений зрителей в выбранном окне',
      unavailable_chat: 'нет наблюдений чата в выбранном окне',
      unavailable_roster: 'выборка чаттеров ещё не собрана',
      unavailable_intel: 'нет данных о канале (followers, title, game)',
      unavailable_causes: 'недостаточно данных для сравнения рекламных окон',
      unavailable_shapes: 'меньше 30 минут наблюдений в окне',
      unavailable_chat_events: 'анонимный клиент не читает сообщения чата',
      missing_table_detection_tables: 'Таблицы детекции отсутствуют: примените alembic upgrade head.',
      factor_no_justification: 'Скачок без причины',
      metric_series: 'Онлайн (зрители)',
      metric_chat: 'Активные авторы в чате',
      metric_roster: 'Выборка чаттеров',
      metric_intel: 'Данные о канале',
      metric_causes: 'Причины изменений',
      metric_shapes: 'Форма кривой',
      metric_chat_events: 'Сообщения чата',
      metric_detection_tables: 'Таблицы детекции',
      metric_viewer_cliff: 'Провал онлайна с отскоком',
      metric_chatter_dip: 'Пропорциональный провал чата',
      metric_title_change: 'Смена названия',
      metric_game_change: 'Смена категории',
      metric_raid_influx: 'Прилив зрителей с подписками',
      metric_combined: 'Совпадение признаков',
      metric_unknown: 'Неизвестный признак',
      metric_ad_growth_ratio: 'рост в окнах рекламы',
      metric_ad_minutes: 'минут в окнах',
      metric_after_viewers: 'зрителей после',
      metric_amplitude: 'во сколько раз',
      metric_baseline_viewers: 'медиана зрителей',
      metric_before_viewers: 'зрителей до',
      metric_boundary_ts: 'граница',
      metric_breaks: 'признаков',
      metric_buckets: 'корзин',
      metric_chat_ratio_after: 'доля чата после',
      metric_chat_ratio_before: 'доля чата до',
      metric_chat_ratio_change_fraction: 'изменение доли чата',
      metric_chatters: 'активных авторов',
      metric_chatters_after: 'активных авторов после',
      metric_chatters_before: 'активных авторов до',
      metric_chatters_drop_fraction: 'падение числа авторов',
      metric_collapse_seconds: 'секунд до обрыва',
      metric_component_count: 'совпало признаков',
      metric_components: 'признаки',
      metric_correlation: 'корреляция',
      metric_count: 'количество',
      metric_current_hourly: 'текущий профиль по часам',
      metric_day: 'день',
      metric_days: 'разных дней',
      metric_delta_ratio: 'отклонение',
      metric_dominant_share: 'доля главного значения',
      metric_drop_fraction: 'падение',
      metric_drop_pct: 'падение, %',
      metric_drop_ratio: 'падение доли',
      metric_early_ratio: 'доля чата раньше',
      metric_early_viewers: 'зрителей раньше',
      metric_end_ts: 'конец',
      metric_entropy_bits: 'энтропия, бит',
      metric_first_followers: 'подписчиков сначала',
      metric_first_ts: 'начало',
      metric_first_viewers: 'зрителей сначала',
      metric_floor: 'минимальный порог',
      metric_followers_after: 'подписчиков после',
      metric_followers_before: 'подписчиков до',
      metric_followers_delta: 'прирост подписчиков',
      metric_followers_ratio: 'рост подписчиков',
      metric_fresh: 'свежих аккаунтов',
      metric_gap_minutes: 'минут перерыва',
      metric_growth_ratio: 'рост',
      metric_hints: 'подсказки о причинах',
      metric_is_instant: 'мгновенный рост',
      metric_kinds: 'виды признаков',
      metric_late_ratio: 'доля чата позже',
      metric_late_viewers: 'зрителей позже',
      metric_max_age_days: 'максимальный возраст, дней',
      metric_max_step: 'максимальный шаг',
      metric_max_step_share: 'доля максимального шага',
      metric_messages: 'сообщений',
      metric_minutes: 'минут',
      metric_minutes_into_stream: 'минута эфира',
      metric_near_zero_share: 'доля почти нулевых изменений',
      metric_normalised: 'нормировано',
      metric_observed_at: 'в момент',
      metric_pairs: 'пары эфиров',
      metric_peak_ts: 'пик',
      metric_peak_viewers: 'пик зрителей',
      metric_pre_median: 'медиана до',
      metric_proxies: 'использованные прокси',
      metric_proxy: 'это прокси-оценка, не наблюдение',
      metric_ratio: 'отношение',
      metric_ratio_median: 'медиана отношения',
      metric_rebound_minutes: 'минут до отскока',
      metric_rebound_viewers: 'зрителей при отскоке',
      metric_rest_growth_ratio: 'рост вне окон',
      metric_rest_minutes: 'минут вне окон',
      metric_rise_fraction: 'доля роста',
      metric_rise_pct: 'рост, %',
      metric_rise_seconds: 'секунд роста',
      metric_running_median: 'текущая медиана',
      metric_sampled: 'в выборке',
      metric_share: 'доля',
      metric_start_ts: 'начало',
      metric_still_minutes: 'минут без изменений',
      metric_stream_id: 'эфир',
      metric_sudden: 'резкий рост',
      metric_threshold: 'порог',
      metric_threshold_share: 'пороговая доля',
      metric_top_author: 'главный автор',
      metric_top_share: 'доля главного автора',
      metric_triggered_by: 'сработавшие признаки',
      metric_value: 'значение',
      metric_viewers: 'зрителей',
      metric_viewers_after: 'зрителей после',
      metric_viewers_before: 'зрителей до',
      metric_viewers_median: 'медиана зрителей',
      metric_viewers_ratio: 'изменение зрителей',
      metric_window_minutes: 'минут в окне',
      metric_zero_delta_fraction: 'доля минут без изменений',
      metric_zero_delta_minutes: 'минут без изменений',
      metric_zero_followers: 'без подписчиков',
      metric_source: 'источник данных',
      metric_messages_per_minute: 'сообщений в минуту (прокси)',
      metric_chatter_turnover: 'оборот чата',
      metric_stale_minutes: 'минут без изменений',
      metric_stale_share: 'доля минут без изменений',
      metric_unpaired_minutes: 'минут без движения онлайна',
      metric_unpaired_share: 'доля таких минут',
      metric_movement: 'относительное движение чата',
      metric_chatters_median: 'медиана активных авторов',
      metric_frozen: 'счётчик замер',
      metric_erratic: 'резкие колебания',
      src_chatters_proxy: 'прокси по счётчику чата',
      src_chat_events: 'реальные сообщения чата',
      ev_series: 'Онлайн (зрители)',
      ev_chat: 'Активные авторы в чате',
      ev_roster: 'Выборка чаттеров',
      ev_intel: 'Данные о канале',
      ev_causes: 'Причины изменений',
      ev_shapes: 'Форма кривой',
      ev_detection_tables: 'Таблицы детекции',
      ev_viewer_cliff: 'Провал онлайна с отскоком',
      ev_chatter_dip: 'Пропорциональный провал чата',
      ev_title_change: 'Смена названия',
      ev_game_change: 'Смена категории',
      ev_raid_influx: 'Прилив зрителей с подписками',
      ev_combined: 'Совпадение признаков',
      ev_unknown: 'Неизвестный признак',
      ev_ad_growth_ratio: 'рост в окнах рекламы',
      ev_ad_minutes: 'минут в окнах',
      ev_after_viewers: 'зрителей после',
      ev_amplitude: 'во сколько раз',
      ev_baseline_viewers: 'медиана зрителей',
      ev_before_viewers: 'зрителей до',
      ev_boundary_ts: 'граница',
      ev_breaks: 'признаков',
      ev_buckets: 'корзин',
      ev_chat_ratio_after: 'доля чата после',
      ev_chat_ratio_before: 'доля чата до',
      ev_chat_ratio_change_fraction: 'изменение доли чата',
      ev_chatters: 'активных авторов',
      ev_chatters_after: 'активных авторов после',
      ev_chatters_before: 'активных авторов до',
      ev_chatters_drop_fraction: 'падение числа авторов',
      ev_collapse_seconds: 'секунд до обрыва',
      ev_component_count: 'совпало признаков',
      ev_components: 'признаки',
      ev_correlation: 'корреляция',
      ev_count: 'количество',
      ev_current_hourly: 'текущий профиль по часам',
      ev_day: 'день',
      ev_days: 'разных дней',
      ev_delta_ratio: 'отклонение',
      ev_dominant_share: 'доля главного значения',
      ev_drop_fraction: 'падение',
      ev_drop_pct: 'падение, %',
      ev_drop_ratio: 'падение доли',
      ev_early_ratio: 'доля чата раньше',
      ev_early_viewers: 'зрителей раньше',
      ev_end_ts: 'конец',
      ev_entropy_bits: 'энтропия, бит',
      ev_first_followers: 'подписчиков сначала',
      ev_first_ts: 'начало',
      ev_first_viewers: 'зрителей сначала',
      ev_floor: 'минимальный порог',
      ev_followers_after: 'подписчиков после',
      ev_followers_before: 'подписчиков до',
      ev_followers_delta: 'прирост подписчиков',
      ev_followers_ratio: 'рост подписчиков',
      ev_fresh: 'свежих аккаунтов',
      ev_gap_minutes: 'минут перерыва',
      ev_growth_ratio: 'рост',
      ev_hints: 'подсказки о причинах',
      ev_is_instant: 'мгновенный рост',
      ev_kinds: 'виды признаков',
      ev_late_ratio: 'доля чата позже',
      ev_late_viewers: 'зрителей позже',
      ev_max_age_days: 'максимальный возраст, дней',
      ev_max_step: 'максимальный шаг',
      ev_max_step_share: 'доля максимального шага',
      ev_messages: 'сообщений',
      ev_minutes: 'минут',
      ev_minutes_into_stream: 'минута эфира',
      ev_near_zero_share: 'доля почти нулевых изменений',
      ev_normalised: 'нормировано',
      ev_observed_at: 'в момент',
      ev_pairs: 'пары эфиров',
      ev_peak_ts: 'пик',
      ev_peak_viewers: 'пик зрителей',
      ev_pre_median: 'медиана до',
      ev_proxies: 'использованные прокси',
      ev_proxy: 'это прокси-оценка, не наблюдение',
      ev_ratio: 'отношение',
      ev_ratio_median: 'медиана отношения',
      ev_rebound_minutes: 'минут до отскока',
      ev_rebound_viewers: 'зрителей при отскоке',
      ev_rest_growth_ratio: 'рост вне окон',
      ev_rest_minutes: 'минут вне окон',
      ev_rise_fraction: 'доля роста',
      ev_rise_pct: 'рост, %',
      ev_rise_seconds: 'секунд роста',
      ev_running_median: 'текущая медиана',
      ev_sampled: 'в выборке',
      ev_share: 'доля',
      ev_start_ts: 'начало',
      ev_still_minutes: 'минут без изменений',
      ev_stream_id: 'эфир',
      ev_sudden: 'резкий рост',
      ev_threshold: 'порог',
      ev_threshold_share: 'пороговая доля',
      ev_top_author: 'главный автор',
      ev_top_share: 'доля главного автора',
      ev_triggered_by: 'сработавшие признаки',
      ev_value: 'значение',
      ev_viewers: 'зрителей',
      ev_viewers_after: 'зрителей после',
      ev_viewers_before: 'зрителей до',
      ev_viewers_median: 'медиана зрителей',
      ev_viewers_ratio: 'изменение зрителей',
      ev_window_minutes: 'минут в окне',
      ev_zero_delta_fraction: 'доля минут без изменений',
      ev_zero_delta_minutes: 'минут без изменений',
      ev_zero_followers: 'без подписчиков',
      ev_source: 'источник данных',
      ev_messages_per_minute: 'сообщений в минуту (прокси)',
      ev_chatter_turnover: 'оборот чата',
      ev_stale_minutes: 'минут без изменений',
      ev_stale_share: 'доля минут без изменений',
      ev_unpaired_minutes: 'минут без движения онлайна',
      ev_unpaired_share: 'доля таких минут',
      ev_movement: 'относительное движение чата',
      ev_chatters_median: 'медиана активных авторов',
      ev_frozen: 'счётчик замер',
      ev_erratic: 'резкие колебания',
      factor_plateau_lock: 'Плато после скачка',
      factor_repeat_shape: 'Повтор формы',
      factor_staircase_return: 'Обрыв в конце эфира',
      factor_silent_chat: 'Мёртвый чат',
      factor_chat_starvation_ratio: 'Мало чата при онлайне',
      factor_chat_collapse: 'Обвал доли чата',
      factor_single_chatter_dominance: 'Один пишущий',
      factor_message_rate: 'Активность чата (прокси)',
      factor_passive_viewer_caveat: 'Оговорка о пассивных зрителях',
      factor_fresh_account_cluster: 'Свежие аккаунты',
      factor_clustered_creation_dates: 'Одинаковые даты создания',
      factor_zero_follower_cluster: 'Аккаунты без подписчиков',
      factor_follower_burst: 'Резкий рост подписчиков',
      factor_follow_without_viewing: 'Подписки без зрителей',
      factor_flatline: 'Плоский онлайн',
      factor_suspicious_smoothness: 'Подозрительная гладкость',
      factor_low_entropy: 'Низкая энтропия значений',
      factor_time_of_day_independence: 'Независимость от суток',
      factor_instant_restore: 'Мгновенное восстановление',
      factor_ad_driven_growth: 'Рост в окнах рекламы',
      note_no_justification: 'Онлайн вырос x{amplitude}: медиана {baseline_viewers} → пик {peak_viewers} за {rise_seconds} с, наблюдаемой причины нет (подсказки: {hints}).',
      note_plateau_lock: 'После скачка значение держится около {value} уже {minutes} мин, отклонение {delta_ratio} ({start_ts} → {end_ts}).',
      note_repeat_shape: 'Кривая повторяет форму прошлых эфиров: {pairs}, корреляция {best_correlation}.',
      note_staircase_return: 'Онлайн обнулился за {collapse_seconds} с от медианы {pre_median} (последнее значение {last_viewers}).',
      note_silent_chat: 'Онлайн около {viewers_median} при замершем чате: {chatters} человек в чате не менялись {still_minutes} мин ({start_ts} → {end_ts}).',
      note_chat_starvation_ratio: 'Медианная доля чата {ratio_median} ниже порога {floor} для {viewers_median} зрителей ({minutes} мин наблюдений).',
      note_chat_collapse: 'Доля чата упала с {early_ratio} до {late_ratio} (падение {drop_ratio}), при этом онлайн вырос {early_viewers} → {late_viewers}.',
      note_single_chatter_dominance: 'Один аккаунт {top_author} написал {top_share} сообщений из {messages} ({top_share_percent}).',
      note_passive_viewer_caveat: 'Пассивные зрители не боты. Признаки {triggered_by} опираются на счётчик чата, а не на список сообщений; медиана онлайна {viewers_median}.',
      note_message_rate: 'Прокси активности чата: счётчик активных авторов меняется на {messages_per_minute} в минуту при медиане {chatters_median} авторов и {viewers_median} зрителей; {stale_minutes} из {minutes} минут без изменений. Это изменение числа авторов, а не счётчик сообщений: анонимный клиент сообщения не читает.',
      note_fresh_account_cluster: 'Свежие аккаунты: {fresh} из {sampled} в выборке младше {max_age_days} дней (доля {share}, порог {threshold_share}).',
      note_clustered_creation_dates: 'Совпадение дат создания: {count} из {sampled} аккаунтов созданы {day} (доля {share}, разных дней в выборке {days}).',
      note_zero_follower_cluster: 'Аккаунты без подписчиков: {zero_followers} из {sampled} (доля {share}, порог {threshold_share}) — сам по себе это слабый признак.',
      note_follower_burst: 'Подписчики выросли x{ratio} внутри одного эфира {stream_id}: {first_followers} → {last_followers} ({first_ts} → {last_ts}).',
      note_follow_without_viewing: 'Подписчики выросли x{followers_ratio}, а онлайн изменился x{viewers_ratio} ({first_viewers} → {last_viewers}): подписчики не равны зрителям.',
      note_flatline: 'Плоская линия: {zero_delta_minutes} из {window_minutes} минут без изменений ({zero_delta_fraction}) при онлайне {viewers}.',
      note_suspicious_smoothness: 'Слишком гладкая кривая: {near_zero_share} вторых разностей ниже порога {threshold} (медиана |Δ²| {median_d2}, у прошлых эфиров {history_median_d2}, {minutes} мин).',
      note_low_entropy: 'Низкая энтропия значений: {entropy_bits} бит, нормализованная {normalised} на {buckets} корзинах (доля главной {dominant_share}, {minutes} мин).',
      note_time_of_day_independence: 'Суточный профиль не совпадает с прошлыми эфирами: корреляция {correlation} по {hours_compared} часам.',
      note_instant_restore: 'После разрыва {gap_minutes} мин онлайн вернулся к прежнему значению: {before_viewers} → {after_viewers} (отклонение {delta_ratio}).',
      note_ad_driven_growth: 'Рост онлайна сосредоточен в окнах предполагаемой рекламы: {ad_growth_ratio} за {ad_minutes} мин против {rest_growth_ratio} за {rest_minutes} мин вне окон (отношение {growth_ratio}, разрывов {breaks}). Это прокси-оценка: реклама анонимно не читается.',
    },
    en: {
      sign_in: 'Sign in with Key',
      sign_in_sub: 'Enter your TVS license key to open your streamer portfolio and analytics.',
      access_key: 'Access key',
      show: 'Show',
      hide: 'Hide',
      open_portfolio: 'Open portfolio',
      checking: 'Verifying…',
      enter_key: 'Enter key.',
      need_key: 'Need a key? Contact an administrator.',
      api_docs: 'API Documentation',
      portfolio: 'Portfolio',
      history: 'History',
      alerts: 'Alerts',
      api: 'Webhooks & API',
      settings: 'Settings',
      admin: 'Admin panel',
      operations: 'Operations',
      workspace: 'Workspace',
      sign_out: 'Sign out',
      updated: 'Updated',
      add_channel: '＋ Add channel',
      add_channel_btn: 'Add channel',
      portfolio_empty: 'Portfolio is empty',
      portfolio_empty_desc: 'Add one or more Twitch streamers. Paste links in one field — we normalize names and start monitoring automatically.',
      loading_data: 'Loading data',
      loading_portfolio: 'Loading portfolio',
      loading_history: 'Loading channel history',
      loading_alerts: 'Loading alerts',
      loading_api: 'Loading API keys',
      loading_admin: 'Loading admin',
      search_channel: 'Search channel…',
      all: 'All',
      live: 'Live',
      flagged_tab: 'Flagged',
      kpi_channels: 'Channels tracked',
      kpi_total_viewers: 'Total viewers',
      kpi_flagged: 'Flagged',
      kpi_refresh: 'Refresh rate',
      kpi_live: 'currently live',
      kpi_sec: 'sec',
      kpi_bg: 'background poller · 60s',
      detail_title: (l, d) => `${l} — viewers & chat history`,
      detail_sub: (d) => `latest saved observations`,
      chart_viewers: 'Total viewers',
      chart_in_chat: 'In chat (approx)',
      chart_viewers_word: 'viewers',
      chart_flat: 'Flat sections mean the Twitch counter did not change between observations; this is expected.',
      risk_breakdown: 'Risk index breakdown',
      collect_more: 'Collect a few more observations to see risk index breakdown.',
      confidence: 'Confidence',
      observations: 'observations',
      provisional: 'provisional',
      admin_tvs_keys: 'TVS keys',
      admin_sub: 'Tokens, policies, audit log, and server load metrics.',
      create_key: '＋ Create key',
      token: 'Token',
      type: 'Type',
      expiry: 'Expiry',
      status: 'Status',
      actions: 'Actions',
      rotate: 'Rotate',
      show_btn: 'Show',
      change: 'Change',
      key_created: 'Key created',
      copy: 'Copy',
      remove_confirm_prefix: 'Remove #',
      remove_confirm_suffix: ' from portfolio?',
      loading_error: 'Loading error',
      your_keys: 'Your keys',
      no_api_keys_yet: 'No API keys yet',
      create_readonly_key: 'Create a read-only key for external integrations.',
      how_to_use: 'How to use',
      same_access: 'Same access, different interface',
      api_inheritance: 'Key <span class="inline-code">tvs_…</span> inherits the streamer list and history of the parent profile. Pass it only in the <span class="inline-code">Authorization: Bearer</span> header.',
      api_expiry: 'API key lifetime is limited by the TVS lifetime. Revoking the parent automatically disables all child keys.',
      api_example: 'GET /api/v1/channels/tumblurr/snapshot\nAuthorization: Bearer tvs_…',
      requests_used: 'requests',
      created_label: 'created',
      status_active: 'active',
      reveal: 'Reveal',
      revoke: 'Revoke',
      new_api_key_title: 'New API key',
      new_api_key_desc: 'It will only access data from the current profile.',
      key_name_label: 'Name',
      key_name_default: 'Integration',
      key_created_once: 'The key is shown only once after creation. Store it in your secrets manager.',
      created_heading: 'Key created',
      copy_btn: 'Copy',
      secret_hidden: 'This value will no longer appear in the list.',
      done_btn: 'Done',
      revoke_confirm: 'Revoke this API key?',
      api_key_revoked: 'API key revoked',
      new_rule_title: 'New rule',
      new_rule_desc: 'The event will be saved to the profile\'s alert feed.',
      rule_type_label: 'Type',
      rule_type_spike: 'Viewer spike',
      rule_type_ratio: 'Chat ratio collapse',
      rule_type_stale: 'Stale data',
      rule_type_offline: 'Stream went offline',
      threshold_label: 'Threshold',
      threshold_hint: 'For "Viewer spike", specify how many times the value increased. For "Chat ratio collapse", the minimum ratio threshold.',
      cancel_btn: 'Cancel',
      create_btn: 'Create',
      rule_created: 'Rule created',
      policy_title: 'Profile policy',
      policy_unlimited: 'Allow any public Twitch channels',
      allowlist_label: 'Channel allowlist',
      allowlist_placeholder: 'tumblurr pesh',
      allowlist_hint: 'With unlimited enabled, the list can be left empty.',
      save_policy_btn: 'Save policy',
      policy_updated: 'Profile policy updated',
      edit_key_title: 'Edit key',
      edit_label: 'Name',
      edit_expiry: 'New expiry (empty = no expiry)',
      save_btn: 'Save',
      key_updated: 'Expiry and name updated',
      create_token_title: 'Create TVS key',
      create_token_desc: 'The key can be opened in the portfolio or issued to an administrator.',
      token_kind_label: 'Key type',
      token_kind_profile: 'Profile',
      token_kind_admin: 'Administrator',
      token_label: 'Name',
      token_label_default: 'New profile',
      token_expiry: 'Expiry (empty = no expiry)',
      token_unlimited: 'Unlimited channels',
      token_created_note: 'The secret can be shown again in the tokens table; the action will be recorded in the audit log.',
      reveal_api_title: 'Reveal API key',
      reveal_token_title: 'Reveal secret',
      audit_event: 'Event recorded in audit log.',
      secret_security: 'Do not send the secret in URLs or third-party chats.',
      rotate_title: 'Rotate key',
      rotate_warning: 'The old key will be revoked and a new TVS key will be created with the same profile and settings. Child API keys of the old TVS will also stop working.',
      rotate_btn: 'Rotate',
      rotate_done: 'The new key is shown only once. The old key has already been revoked.',
      rotated_label: 'this key',
      webhook_title: 'Add webhook',
      webhook_desc: 'Events will be HMAC-signed and sent to an HTTPS endpoint.',
      webhook_url_label: 'HTTPS URL',
      webhook_url_placeholder: 'https://example.com/tvs-hook',
      webhook_secret_label: 'Signing secret (minimum 16 characters)',
      webhook_hint: 'Private IPs, localhost, and non-HTTPS addresses are not allowed.',
      add_btn: 'Add',
      webhook_added: 'Webhook added',
      copied: 'Copied',
      copy_manual: 'Copy the text manually',
      admin_sessions: 'active sessions',
      admin_profiles: 'active profiles',
      admin_channels: 'active channels',
      admin_api_keys: 'API keys',
      statuses_title: 'Response statuses',
      statuses_sub: 'HTTP status distribution for current process',
      routes_title: 'Top routes',
      routes_sub: 'Request count by endpoint',
      poller_title: 'Poller and latency',
      poller_sub: 'Background collection status',
      polls_count: 'polls',
      errors_count: 'errors',
      p95_latency: 'p95 latency',
      poller_success_hint: 'Green share = successful cycles; red = poller errors.',
      tokens_tab: 'Tokens',
      profiles_tab: 'Policies',
      audit_tab: 'Audit',
      load_tab: 'Load',
      hide_revoked: 'Hide revoked',
      show_revoked: 'Show revoked',
      key_col: 'Key',
      type_col: 'Type',
      profile_col: 'Profile',
      mode_col: 'Mode',
      expiry_col: 'Expiry',
      status_col: 'Status',
      actions_col: 'Actions',
      profile_name_col: 'Profile',
      channels_col: 'Channels',
      mode_col_short: 'Mode',
      last_activity_col: 'Last activity',
      time_col: 'Time',
      actor_col: 'Actor',
      action_col: 'Action',
      object_col: 'Object',
      request_col: 'Request',
      load_title: 'Application load',
      load_sub: 'Last requests',
      active_sessions_label: 'Active sessions',
      active_profiles_label: 'Active profiles',
      active_channels_label: 'Active channels',
      api_keys_label: 'API keys',
      p50_latency: 'p50 latency',
      error_rate: 'Error rate',
      mode_unlimited: 'unlimited',
      mode_allowlist: 'allowlist',
      active_channels: 'Active channels',
      add_and_start: 'Add and start',
      add_channels_desc: 'Paste Twitch links or logins. They can be separated by spaces and line breaks.',
      add_channels_modal: 'Add channels',
      alerts_sub: 'Clear rules and observation events.',
      all_channels: 'All channels',
      all_profile_channels: 'all added by the profile',
      api_requests: 'API requests',
      api_sub: 'Generate machine keys from your profile. They stay valid while the TVS key is active.',
      audit: 'Audit',
      bg_poller_60: 'background poller · 60 sec',
      cancel: 'Cancel',
      channel: 'Channel',
      channel_history: 'Channel history',
      channel_history_sub: 'A separate view of observations, anomalies, and index causes.',
      channel_mode: 'Channel mode',
      channel_offline_note: 'The channel is offline now. The chart appears after the next live observation.',
      channels_tracked: 'Channels tracked',
      chart_note: 'Flat sections mean Twitch did not change the counter between observations; this is not a chart error.',
      create_api_key_desc: 'Add a spike or missing-data threshold to start receiving events.',
      currently_live: 'currently live',
      d_ago: 'd ago',
      days_30: '30 days',
      days_7: '7 days',
      demo_note: 'Showing <strong>demo mode</strong>: the numbers are synthetic and do not reflect Twitch. For real data set TWITCH_SOURCE=gql and restart the poller.',
      detailed_report: 'Detailed report',
      docs: 'Documentation',
      docs_desc: 'The full OpenAPI schema is available on the server with schemas, errors, limits, and curl/Python/JavaScript examples.',
      download_fail: 'Failed to download the file',
      event_feed: 'Latest events',
      events: 'events',
      expiry_date: 'Expiry date',
      export_csv: 'Export CSV',
      flag: 'flag',
      flagged: 'Flagged',
      for_devs: 'For developers',
      freshness: 'Freshness',
      guests: 'Guests',
      h_ago: 'h ago',
      high_risk: 'high risk',
      hours_24: '24 hours',
      in_chat: 'In chat',
      in_chat_approx: 'In chat (approx)',
      in_chat_word: 'and chat',
      increased_attention: 'increased attention',
      index: 'Index',
      insufficient_data: 'Not enough data to draw a conclusion yet.',
      label: 'Name',
      last_cycle: 'last cycle',
      live_status: 'live',
      load: 'Load',
      min_ago: 'min ago',
      monitoring: 'monitoring',
      na: 'n/a',
      new_rule: '＋ New rule',
      no_data: 'no data',
      no_events_yet: 'No rules yet',
      no_history: 'No history collected yet.',
      no_numeric: 'No numeric observations',
      normal: 'normal',
      obs_after_poller: 'Observations appear after the next poller cycle.',
      offline_status: 'offline',
      open_api_docs: 'Open API docs ↗',
      open_history: 'Open history',
      picker_hint: 'History channels. Use Shift and the mouse wheel',
      policies: 'Policies',
      poller_status: 'Poller status',
      portfolio_rules: 'Rules',
      profile: 'Profile',
      profile_tvs_details: 'Current TVS key details',
      profiles_count: 'profiles',
      ratio: 'Ratio',
      reasons: 'Reasons',
      recent_obs: 'Latest observations',
      refresh: 'Refresh',
      refresh_rate: 'Refresh rate',
      report_pdf: 'PDF report',
      restricted_profile_note: 'A restricted profile only accepts channels allowed by the administrator.',
      retry: 'Retry',
      rule_offline: 'Stream went offline',
      rule_ratio: 'Chat ratio collapse',
      rule_score: 'High risk index',
      rule_spike: 'Viewer spike',
      rule_stale: 'Stale data',
      rule_test: 'Test event',
      rules_count: 'active',
      score_above_60: 'score above 60',
      sec_30: '30 sec',
      sec_ago: 'sec ago',
      service_down: 'Service temporarily unavailable',
      session_expired: 'Session expired. Enter the key again.',
      settings_sub: 'Profile, access, and documentation.',
      stale: 'stale',
      stream: 'Stream',
      streamer_links: 'Streamer links',
      time: 'Time',
      tokens: 'Tokens',
      total: 'Total',
      total_viewers: 'Total viewers',
      total_viewers_chart: 'Total viewers',
      trend: 'Trend',
      unlimited: 'Unlimited',
      viewers: 'viewers',
      warning: 'warning',
      webhooks_and_api: 'Webhooks & API',
      welcome: 'Welcome',
      no_chart_data: 'No chart data',
      chart_top_n: 'Showing first',
      chart_of_total: 'of',
      portfolio_title: 'Channel portfolio',
      portfolio_subtitle: 'Observations, anomalies, and data freshness on one screen.',
      new_api_key_btn: '＋ New API key',
      detail_chart_title: 'viewers & chat history',
      in_chat_short: 'in chat',
      chat_capped_note: 'Twitch reported more chatters than viewers, so the value is capped at the viewer count.',
      chart_shared_scale: 'Both lines use one scale, so the gap between them equals the real difference in people.',
      explain_score: 'The index describes how unusual the observed behaviour is, not the probability of artificial inflation. The final call stays with a human. {detail}',
      explain_score_enough: 'There is enough data for a preliminary comparison.',
      warn_low_confidence: 'not enough data, the estimate is preliminary',
      warn_no_chat_data: 'not enough chat data',
      note_low_ratio: 'median chatter share {ratio}',
      note_spike_amplitude: 'largest spike x{amplitude}',
      note_sawtooth: '{changes} direction changes',
      factor_low_ratio: 'Low chat share',
      factor_spike_no_chat: 'Spike without chat growth',
      factor_sawtooth: 'Sharp oscillations',
      factor_category_outlier: 'Category deviation',
      no_factors_yet: 'There are not enough factors for this channel yet. Keep watching.',
      need_more_observations: 'More observations are needed',
      suspicious_anomaly: 'Suspicious anomaly',
      title_unavailable: 'Title unavailable',
      request_failed: 'Request failed',
      nav_admin: 'Admin navigation',
      nav_main: 'Main navigation',
      modal_close: 'Close',
      hours_short: 'h',
      adding: 'Adding…',
      add_and_start_short: 'Add and start',
      added_summary: 'Added: {added}. Duplicates: {duplicates}.{rejected}',
      rejected_summary: ' Rejected: {rejected}.',
      channel_removed: '#{login} removed from portfolio',
      rule_enabled: 'enabled',
      rule_disabled: 'disabled',
      poller_off: 'Poller is off.',
      trend_aria: 'Channel trend',
      chart_aria: 'Viewer and chat history',
      done_btn_short: 'Done',
      rotate_note: 'the old secret cannot be recovered',
      lang_badge: 'English',
      guide_title: 'How Alerts Work',
      guide_sub: 'Signals for verification, not automatic enforcement',
      guide_spike: 'Viewer spike',
      guide_spike_desc: 'Compares the new peak with the previous observation.',
      guide_ratio: 'Chat ratio collapse',
      guide_ratio_desc: 'Checks whether viewers remained without chat participants.',
      guide_stale: 'Stale data',
      guide_stale_desc: 'Warns if the poller has not updated the channel.',
      guide_offline: 'Offline',
      guide_offline_desc: 'Records the channel transition from live to offline.',
      guide_footer: 'Cooldown keeps one rule from generating duplicate events every poll. A red flag marks a high index; hover or click it to see the causes.',
      downloading: 'Downloading {file}',
      severity_high: 'high',
      severity_warning: 'warning',
      severity_info: 'info',
      detection: 'View-farm detection',
      detection_sub: 'Curve shape, chat behaviour and the chatter sample. The index describes how unusual the behaviour is, not the probability of bots.',
      loading_detection: 'Computing the detection report',
      detection_verdict: 'Verdict',
      detection_series: 'Expanded per-minute series',
      detection_confidence_parts: 'How confidence was formed',
      detection_availability: 'availability',
      detection_window: 'Window',
      detection_hours: 'hours',
      detection_points: 'points',
      detection_gaps: 'gaps',
      detection_factors: 'Fired signals',
      detection_signals: 'signals',
      detection_quiet: 'No signal fired.',
      detection_quiet_detail: 'This is not proof of honest traffic: several metrics depend on the sample size and observation volume.',
      detection_chart_title: 'per-minute viewer curve',
      detection_chart_note: 'The series is expanded per minute: values hold until the next change and poller gaps show up as breaks.',
      event_spike: 'Viewer spike',
      event_ad: 'Ad signal (proxy)',
      event_change: 'Title or game change',
      event_stream: 'Stream boundary',
      event_stream_start: 'stream started',
      event_stream_end: 'stream ended',
      events_thinned: 'More than 25 events: only some are shown.',
      detection_rate_title: 'Chat activity (proxy)',
      detection_rate_sub: 'The anonymous client cannot read messages: this is the change in the chatter count, not a message counter.',
      detection_rate_per_minute: 'Change per minute',
      detection_rate_stale: 'Minutes unchanged',
      detection_rate_source: 'Source',
      detection_ad_title: 'Ads: window comparison',
      detection_ad_proxy: 'The anonymous client cannot read adBreak, so this is an inferential estimate from proxies.',
      detection_ad_none: 'No ad break was detected, so the comparison is unavailable.',
      detection_ad_window: 'Estimated ad-break windows',
      detection_ad_rest: 'The rest of the stream',
      detection_minutes: 'minutes',
      detection_growth: 'growth',
      detection_no_breaks: 'no break found',
      detection_unavailable: 'The detection report is unavailable. Check the channel data and retry later.',
      detection_unavailable_title: 'Unavailable metrics',
      detection_unavailable_sub: 'Missing data lowers confidence, not the score itself.',
      detection_warnings: 'Limits and warnings',
      detection_evidence: 'Evidence: the chatter sample',
      detection_evidence_sub: 'Up to 100 logins from CommunityTab, enriched via users(logins:)',
      detection_no_sample: 'No chatter sample collected yet.',
      detection_sampled: 'sample',
      detection_enriched: 'enriched',
      detection_accounts: 'accounts',
      detection_enrich_pending: 'Account enrichment appears after the next poller cycle.',
      chatter_col: 'Account',
      age_days_col: 'Age, days',
      followers_col: 'Followers',
      created_col: 'Created',
      followers_label: 'followers',
      detect_not_probability: 'The score describes how unusual the behaviour is, not the probability of bots.',
      detect_no_observations: 'No observations in the selected window, the score cannot be computed.',
      detect_explain: 'Detection compares the curve shape, chat behaviour and account sample against the channel own history. {detail}',
      unavailable_series: 'no viewer observations in the selected window',
      unavailable_chat: 'no chat observations in the selected window',
      unavailable_roster: 'no chatter sample collected yet',
      unavailable_intel: 'no channel intel (followers, title, game)',
      unavailable_causes: 'not enough data to compare ad windows',
      unavailable_shapes: 'fewer than 30 minutes of observations',
      unavailable_chat_events: 'the anonymous client cannot read chat messages',
      missing_table_detection_tables: 'Detection tables are missing: run alembic upgrade head.',
      factor_no_justification: 'Unexplained jump',
      metric_series: 'Viewers',
      metric_chat: 'Chatters in chat',
      metric_roster: 'Chatter sample',
      metric_intel: 'Channel intel',
      metric_causes: 'Causes of change',
      metric_shapes: 'Curve shape',
      metric_chat_events: 'Chat messages',
      metric_detection_tables: 'Detection tables',
      metric_viewer_cliff: 'Viewer cliff with rebound',
      metric_chatter_dip: 'Proportional chat dip',
      metric_title_change: 'Title change',
      metric_game_change: 'Game change',
      metric_raid_influx: 'Influx with followers',
      metric_combined: 'Combined signals',
      metric_unknown: 'Unknown signal',
      metric_ad_growth_ratio: 'growth in ad windows',
      metric_ad_minutes: 'minutes in windows',
      metric_after_viewers: 'viewers after',
      metric_amplitude: 'multiple',
      metric_baseline_viewers: 'median viewers',
      metric_before_viewers: 'viewers before',
      metric_boundary_ts: 'boundary',
      metric_breaks: 'signals',
      metric_buckets: 'buckets',
      metric_chat_ratio_after: 'chat ratio after',
      metric_chat_ratio_before: 'chat ratio before',
      metric_chat_ratio_change_fraction: 'chat ratio change',
      metric_chatters: 'chatters',
      metric_chatters_after: 'chatters after',
      metric_chatters_before: 'chatters before',
      metric_chatters_drop_fraction: 'chatter drop',
      metric_collapse_seconds: 'seconds to collapse',
      metric_component_count: 'matched signals',
      metric_components: 'signals',
      metric_correlation: 'correlation',
      metric_count: 'count',
      metric_current_hourly: 'current hourly profile',
      metric_day: 'day',
      metric_days: 'distinct days',
      metric_delta_ratio: 'deviation',
      metric_dominant_share: 'dominant value share',
      metric_drop_fraction: 'drop',
      metric_drop_pct: 'drop, %',
      metric_drop_ratio: 'ratio drop',
      metric_early_ratio: 'chat ratio earlier',
      metric_early_viewers: 'viewers earlier',
      metric_end_ts: 'end',
      metric_entropy_bits: 'entropy, bits',
      metric_first_followers: 'followers first',
      metric_first_ts: 'start',
      metric_first_viewers: 'viewers first',
      metric_floor: 'minimum floor',
      metric_followers_after: 'followers after',
      metric_followers_before: 'followers before',
      metric_followers_delta: 'follower growth',
      metric_followers_ratio: 'follower growth',
      metric_fresh: 'fresh accounts',
      metric_gap_minutes: 'minutes of break',
      metric_growth_ratio: 'growth',
      metric_hints: 'cause hints',
      metric_is_instant: 'instant rise',
      metric_kinds: 'signal kinds',
      metric_late_ratio: 'chat ratio later',
      metric_late_viewers: 'viewers later',
      metric_max_age_days: 'max age, days',
      metric_max_step: 'largest step',
      metric_max_step_share: 'share of largest step',
      metric_messages: 'messages',
      metric_minutes: 'minutes',
      metric_minutes_into_stream: 'minute of the stream',
      metric_near_zero_share: 'share of near-zero changes',
      metric_normalised: 'normalised',
      metric_observed_at: 'observed at',
      metric_pairs: 'stream pairs',
      metric_peak_ts: 'peak',
      metric_peak_viewers: 'peak viewers',
      metric_pre_median: 'median before',
      metric_proxies: 'proxies used',
      metric_proxy: 'this is a proxy, not an observation',
      metric_ratio: 'ratio',
      metric_ratio_median: 'median ratio',
      metric_rebound_minutes: 'minutes to rebound',
      metric_rebound_viewers: 'viewers at rebound',
      metric_rest_growth_ratio: 'growth outside windows',
      metric_rest_minutes: 'minutes outside windows',
      metric_rise_fraction: 'rise fraction',
      metric_rise_pct: 'rise, %',
      metric_rise_seconds: 'seconds of rise',
      metric_running_median: 'running median',
      metric_sampled: 'sampled',
      metric_share: 'share',
      metric_start_ts: 'start',
      metric_still_minutes: 'minutes unchanged',
      metric_stream_id: 'stream',
      metric_sudden: 'sudden rise',
      metric_threshold: 'threshold',
      metric_threshold_share: 'threshold share',
      metric_top_author: 'top author',
      metric_top_share: 'top author share',
      metric_triggered_by: 'triggered by',
      metric_value: 'value',
      metric_viewers: 'viewers',
      metric_viewers_after: 'viewers after',
      metric_viewers_before: 'viewers before',
      metric_viewers_median: 'median viewers',
      metric_viewers_ratio: 'viewer change',
      metric_window_minutes: 'minutes in window',
      metric_zero_delta_fraction: 'share of unchanged minutes',
      metric_zero_delta_minutes: 'minutes unchanged',
      metric_zero_followers: 'without followers',
      metric_source: 'data source',
      metric_messages_per_minute: 'messages per minute (proxy)',
      metric_chatter_turnover: 'chat turnover',
      metric_stale_minutes: 'minutes unchanged',
      metric_stale_share: 'share of unchanged minutes',
      metric_unpaired_minutes: 'minutes without viewer movement',
      metric_unpaired_share: 'share of those minutes',
      metric_movement: 'relative chat movement',
      metric_chatters_median: 'median chatters',
      metric_frozen: 'counter frozen',
      metric_erratic: 'erratic swings',
      src_chatters_proxy: 'chatter-count proxy',
      src_chat_events: 'real chat messages',
      ev_series: 'Viewers',
      ev_chat: 'Chatters in chat',
      ev_roster: 'Chatter sample',
      ev_intel: 'Channel intel',
      ev_causes: 'Causes of change',
      ev_shapes: 'Curve shape',
      ev_detection_tables: 'Detection tables',
      ev_viewer_cliff: 'Viewer cliff with rebound',
      ev_chatter_dip: 'Proportional chat dip',
      ev_title_change: 'Title change',
      ev_game_change: 'Game change',
      ev_raid_influx: 'Influx with followers',
      ev_combined: 'Combined signals',
      ev_unknown: 'Unknown signal',
      ev_ad_growth_ratio: 'growth in ad windows',
      ev_ad_minutes: 'minutes in windows',
      ev_after_viewers: 'viewers after',
      ev_amplitude: 'multiple',
      ev_baseline_viewers: 'median viewers',
      ev_before_viewers: 'viewers before',
      ev_boundary_ts: 'boundary',
      ev_breaks: 'signals',
      ev_buckets: 'buckets',
      ev_chat_ratio_after: 'chat ratio after',
      ev_chat_ratio_before: 'chat ratio before',
      ev_chat_ratio_change_fraction: 'chat ratio change',
      ev_chatters: 'chatters',
      ev_chatters_after: 'chatters after',
      ev_chatters_before: 'chatters before',
      ev_chatters_drop_fraction: 'chatter drop',
      ev_collapse_seconds: 'seconds to collapse',
      ev_component_count: 'matched signals',
      ev_components: 'signals',
      ev_correlation: 'correlation',
      ev_count: 'count',
      ev_current_hourly: 'current hourly profile',
      ev_day: 'day',
      ev_days: 'distinct days',
      ev_delta_ratio: 'deviation',
      ev_dominant_share: 'dominant value share',
      ev_drop_fraction: 'drop',
      ev_drop_pct: 'drop, %',
      ev_drop_ratio: 'ratio drop',
      ev_early_ratio: 'chat ratio earlier',
      ev_early_viewers: 'viewers earlier',
      ev_end_ts: 'end',
      ev_entropy_bits: 'entropy, bits',
      ev_first_followers: 'followers first',
      ev_first_ts: 'start',
      ev_first_viewers: 'viewers first',
      ev_floor: 'minimum floor',
      ev_followers_after: 'followers after',
      ev_followers_before: 'followers before',
      ev_followers_delta: 'follower growth',
      ev_followers_ratio: 'follower growth',
      ev_fresh: 'fresh accounts',
      ev_gap_minutes: 'minutes of break',
      ev_growth_ratio: 'growth',
      ev_hints: 'cause hints',
      ev_is_instant: 'instant rise',
      ev_kinds: 'signal kinds',
      ev_late_ratio: 'chat ratio later',
      ev_late_viewers: 'viewers later',
      ev_max_age_days: 'max age, days',
      ev_max_step: 'largest step',
      ev_max_step_share: 'share of largest step',
      ev_messages: 'messages',
      ev_minutes: 'minutes',
      ev_minutes_into_stream: 'minute of the stream',
      ev_near_zero_share: 'share of near-zero changes',
      ev_normalised: 'normalised',
      ev_observed_at: 'observed at',
      ev_pairs: 'stream pairs',
      ev_peak_ts: 'peak',
      ev_peak_viewers: 'peak viewers',
      ev_pre_median: 'median before',
      ev_proxies: 'proxies used',
      ev_proxy: 'this is a proxy, not an observation',
      ev_ratio: 'ratio',
      ev_ratio_median: 'median ratio',
      ev_rebound_minutes: 'minutes to rebound',
      ev_rebound_viewers: 'viewers at rebound',
      ev_rest_growth_ratio: 'growth outside windows',
      ev_rest_minutes: 'minutes outside windows',
      ev_rise_fraction: 'rise fraction',
      ev_rise_pct: 'rise, %',
      ev_rise_seconds: 'seconds of rise',
      ev_running_median: 'running median',
      ev_sampled: 'sampled',
      ev_share: 'share',
      ev_start_ts: 'start',
      ev_still_minutes: 'minutes unchanged',
      ev_stream_id: 'stream',
      ev_sudden: 'sudden rise',
      ev_threshold: 'threshold',
      ev_threshold_share: 'threshold share',
      ev_top_author: 'top author',
      ev_top_share: 'top author share',
      ev_triggered_by: 'triggered by',
      ev_value: 'value',
      ev_viewers: 'viewers',
      ev_viewers_after: 'viewers after',
      ev_viewers_before: 'viewers before',
      ev_viewers_median: 'median viewers',
      ev_viewers_ratio: 'viewer change',
      ev_window_minutes: 'minutes in window',
      ev_zero_delta_fraction: 'share of unchanged minutes',
      ev_zero_delta_minutes: 'minutes unchanged',
      ev_zero_followers: 'without followers',
      ev_source: 'data source',
      ev_messages_per_minute: 'messages per minute (proxy)',
      ev_chatter_turnover: 'chat turnover',
      ev_stale_minutes: 'minutes unchanged',
      ev_stale_share: 'share of unchanged minutes',
      ev_unpaired_minutes: 'minutes without viewer movement',
      ev_unpaired_share: 'share of those minutes',
      ev_movement: 'relative chat movement',
      ev_chatters_median: 'median chatters',
      ev_frozen: 'counter frozen',
      ev_erratic: 'erratic swings',
      factor_plateau_lock: 'Plateau after a jump',
      factor_repeat_shape: 'Repeated curve shape',
      factor_staircase_return: 'Collapse at stream end',
      factor_silent_chat: 'Silent chat',
      factor_chat_starvation_ratio: 'Chat starvation',
      factor_chat_collapse: 'Chat ratio collapse',
      factor_single_chatter_dominance: 'Single dominant chatter',
      factor_message_rate: 'Chat activity (proxy)',
      factor_passive_viewer_caveat: 'Passive viewer caveat',
      factor_fresh_account_cluster: 'Fresh accounts',
      factor_clustered_creation_dates: 'Clustered creation dates',
      factor_zero_follower_cluster: 'Zero-follower accounts',
      factor_follower_burst: 'Follower burst',
      factor_follow_without_viewing: 'Followers without viewers',
      factor_flatline: 'Flatline',
      factor_suspicious_smoothness: 'Suspicious smoothness',
      factor_low_entropy: 'Low value entropy',
      factor_time_of_day_independence: 'Time-of-day independence',
      factor_instant_restore: 'Instant restore',
      factor_ad_driven_growth: 'Growth around ad windows',
      note_no_justification: 'Viewers grew x{amplitude}: median {baseline_viewers} to peak {peak_viewers} in {rise_seconds}s with no observed cause (hints: {hints}).',
      note_plateau_lock: 'After the jump the value sits near {value} for {minutes} minutes, spread {delta_ratio} ({start_ts} to {end_ts}).',
      note_repeat_shape: 'The curve repeats the shape of earlier streams: {pairs}, correlation {best_correlation}.',
      note_staircase_return: 'Viewers collapsed within {collapse_seconds}s from a median of {pre_median} (last value {last_viewers}).',
      note_silent_chat: 'Viewers around {viewers_median} with a frozen chat: {chatters} chatters unchanged for {still_minutes} minutes ({start_ts} to {end_ts}).',
      note_chat_starvation_ratio: 'Median chat ratio {ratio_median} is below the floor {floor} for {viewers_median} viewers ({minutes} minutes observed).',
      note_chat_collapse: 'Chat ratio fell from {early_ratio} to {late_ratio} (drop {drop_ratio}) while viewers rose {early_viewers} to {late_viewers}.',
      note_single_chatter_dominance: 'A single account {top_author} wrote {top_share} of {messages} messages ({top_share_percent}).',
      note_passive_viewer_caveat: 'Passive viewers are not bots. Signals {triggered_by} rely on the chat counter, not on message lists; median viewers {viewers_median}.',
      note_message_rate: 'Chat activity proxy: the chatter count moves {messages_per_minute} per minute at a median of {chatters_median} chatters and {viewers_median} viewers; {stale_minutes} of {minutes} minutes unchanged. This is the change in the number of chatters, not a message count: the anonymous client cannot read messages.',
      note_fresh_account_cluster: 'Fresh accounts: {fresh} of {sampled} sampled chatters are younger than {max_age_days} days (share {share}, threshold {threshold_share}).',
      note_clustered_creation_dates: 'Clustered creation dates: {count} of {sampled} accounts were created on {day} (share {share}, {days} distinct days).',
      note_zero_follower_cluster: 'Accounts without followers: {zero_followers} of {sampled} (share {share}, threshold {threshold_share}) -- a weak signal on its own.',
      note_follower_burst: 'Followers grew x{ratio} inside one stream {stream_id}: {first_followers} to {last_followers} ({first_ts} to {last_ts}).',
      note_follow_without_viewing: 'Followers grew x{followers_ratio} while viewers changed x{viewers_ratio} ({first_viewers} to {last_viewers}): followers are not viewers.',
      note_flatline: 'Flat line: {zero_delta_minutes} of {window_minutes} minutes unchanged ({zero_delta_fraction}) at {viewers} viewers.',
      note_suspicious_smoothness: 'Abnormally smooth curve: {near_zero_share} of second differences below the threshold {threshold} (median |d2| {median_d2}, previous streams {history_median_d2}, {minutes} minutes).',
      note_low_entropy: 'Low entropy of the rounded values: {entropy_bits} bits, normalised {normalised} over {buckets} buckets (dominant share {dominant_share}, {minutes} minutes).',
      note_time_of_day_independence: 'The hourly profile does not match earlier streams: correlation {correlation} across {hours_compared} hours.',
      note_instant_restore: 'After a {gap_minutes}-minute break viewers returned to the previous value: {before_viewers} to {after_viewers} (spread {delta_ratio}).',
      note_ad_driven_growth: 'Viewer growth is concentrated in the estimated ad windows: {ad_growth_ratio} over {ad_minutes} minutes versus {rest_growth_ratio} over {rest_minutes} minutes outside (ratio {growth_ratio}, {breaks} breaks). This is a proxy estimate: ads cannot be read anonymously.',
    },
  };

  const t = (k, fb) => (I18N[state.lang] && I18N[state.lang][k]) || fb || k;
  const tp = (k, args) => t(k).replace(/\{(\w+)\}/g, (match, name) => (args && args[name] != null ? String(args[name]) : match));

  const icons = {
    portfolio: '▥', history: '◷', detection: '⌁', alerts: '☆', api: '◈', settings: '⚙', admin: '◉', logout: '↗'
  };

  const LOGO_SVG = '<svg class="brand-logo" viewBox="60 24 120 216" role="img" aria-label="TVS"><path fill="currentColor" d="M60 24h72v12h-72zM84 36h24v96h-24zM132 72h24v72h-24zM96 132h36v24h-36zM156 132h12v36h-12zM132 144h12v12h-12zM168 144h12v24h-12zM108 156h24v24h-24zM120 180h48v12h-48zM156 192h24v36h-24zM108 204h24v24h-24zM144 216h12v24h-12zM120 228h24v12h-24zM156 228h12v12h-12z"/></svg>';
  function langToggleHtml() {
    return `<div class="lang-toggle"><button type="button" data-lang="ru" class="${state.lang === 'ru' ? 'active' : ''}">RU</button><button type="button" data-lang="en" class="${state.lang === 'en' ? 'active' : ''}">EN</button></div>`;
  }
  function setLang(lang) {
    if (lang !== 'ru' && lang !== 'en') return;
    state.lang = lang;
    localStorage.setItem('tvs_lang', lang);
    if (!state.user) renderLogin();
    else renderView();
  }

  const alertLabels = {
    get viewer_spike() { return t('rule_spike', 'Всплеск зрителей'); },
    get ratio_collapse() { return t('rule_ratio', 'Падение доли чата'); },
    get score_threshold() { return t('rule_score', 'Высокий индекс'); },
    get stream_offline() { return t('rule_offline', 'Канал ушёл офлайн'); },
    get stale_data() { return t('rule_stale', 'Нет свежих данных'); },
    get test() { return t('rule_test', 'Тестовое событие'); }
  };
  const severityLabels = {
    get high() { return t('severity_high', 'высокая'); },
    get warning() { return t('severity_warning', 'внимание'); },
    get info() { return t('severity_info', 'инфо'); }
  };

  // The score snapshot is computed once and stored, so its Russian prose cannot
  // be translated client side. Every message the backend emits therefore ships
  // a code (and args) next to the text; these helpers render the active
  // language from those codes and fall back to the stored text for snapshots
  // written before the codes existed.
  function factorLabel(code) { return t(`factor_${code}`) === `factor_${code}` ? code : t(`factor_${code}`); }
  function factorNote(factor) { return factor.note_code ? tp(factor.note_code, factor.note_args) : (factor.note || ''); }
  function warningList(score) {
    if (Array.isArray(score.warning_codes)) return score.warning_codes.map((item) => tp(item.code, item.args));
    return score.warnings || [];
  }
  function scoreExplanation(score) {
    const detail = warningList(score).join(' ') || t('explain_score_enough', 'Данных достаточно для предварительного сравнения.');
    if (score.warning_codes) return tp('explain_score', { detail });
    return score.explanation || detail;
  }

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const fmt = (value) => value === null || value === undefined ? '—' : (typeof value === 'number' ? value.toLocaleString(state.lang === 'en' ? 'en-US' : 'ru-RU') : String(value));
  const compact = (value) => { const number = Number(value); if (!Number.isFinite(number)) return '—'; if (Math.abs(number) >= 1000000) return `${(number / 1000000).toFixed(1)}M`; if (Math.abs(number) >= 1000) return `${(number / 1000).toFixed(1)}K`; return Math.round(number).toLocaleString(state.lang === 'en' ? 'en-US' : 'ru-RU'); };
  const pct = (value) => value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(1)}%`;
  const date = (value) => value ? new Date(value).toLocaleString(state.lang === 'en' ? 'en-US' : 'ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—';
  const age = (value) => {
    if (!value) return t('no_data', 'нет данных');
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 60) return `${seconds} ${t('sec_ago', 'сек назад')}`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} ${t('min_ago', 'мин назад')}`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} ${t('h_ago', 'ч назад')}`;
    return `${Math.floor(seconds / 86400)} ${t('d_ago', 'д назад')}`;
  };
  const initials = (value) => String(value || '?').replace(/[^a-z0-9_]/gi, '').slice(0, 2).toUpperCase() || '?';

  class ApiError extends Error {
    constructor(message, status, payload) { super(message); this.status = status; this.payload = payload; }
  }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
    const response = await fetch(path, { credentials: 'include', ...options, headers });
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok || payload?.ok === false) {
      throw new ApiError(payload?.error?.message || t('request_failed', 'Ошибка запроса'), response.status, payload);
    }
    return payload;
  }

  function toast(message, kind = 'good') {
    const root = document.getElementById('toast-root');
    const node = document.createElement('div');
    node.className = `toast ${kind}`;
    node.textContent = message;
    root.appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  async function downloadFile(url, filename) {
    try {
      const response = await fetch(url, { credentials: 'include', headers: { Accept: 'application/octet-stream, application/pdf, text/csv' } });
      if (!response.ok) {
        let message = t('download_fail', 'Не удалось скачать файл');
        try { const payload = await response.json(); message = payload?.error?.message || message; } catch (_) { /* non-JSON error */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename || 'report';
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      toast(tp('downloading', { file: filename || t('report_pdf', 'Отчёт PDF') }));
    } catch (err) {
      toast(err.message || t('download_fail', 'Не удалось скачать файл'), 'bad');
    }
  }

  document.addEventListener('click', (event) => {
    const target = event.target.closest?.('[data-download]');
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    downloadFile(target.dataset.download, target.dataset.filename);
  });

  function setAppError(message) {
    app.innerHTML = `<div class="login-page"><div class="login-card"><div class="eyebrow">TVS Analytics</div><h1>${t('service_down', 'Сервис временно недоступен')}</h1><p class="subtitle">${esc(message)}</p><button class="btn btn-primary" id="retry">${t('retry', 'Повторить')}</button></div></div>`;
    document.getElementById('retry').addEventListener('click', () => boot());
  }

  function renderLogin(errorMessage = '') {
    document.body.classList.add('login-mode');
    app.innerHTML = `<main class="login-page">
      <section class="login-card">
        <div class="login-lang">${langToggleHtml()}</div>
        <div class="login-brand"><span class="brand-mark">${LOGO_SVG}</span><span class="brand-name">twitch <span>viewers system</span></span></div>
        <p class="eyebrow">Portfolio intelligence</p>
        <h1>${t('sign_in', 'Войдите по ключу')}</h1>
        <p class="subtitle">${t('sign_in_sub', 'Вставьте лицензионный ключ TVS, чтобы открыть свой портфель стримеров и подробную аналитику.')}</p>
        <form class="form-stack" id="login-form">
          <label class="form-label" for="token-input">${t('access_key', 'Ключ доступа')}</label>
          <div class="token-wrap"><input class="input" id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="TVS_…" required><button class="token-toggle" type="button" id="token-toggle">${t('show', 'Показать')}</button></div>
          <p class="form-error" id="login-error">${esc(errorMessage)}</p>
          <button class="btn btn-primary" type="submit" id="login-submit">${t('open_portfolio', 'Открыть портфель')}</button>
        </form>
        <p class="login-foot">${t('need_key', 'Нужен ключ? Обратитесь к администратору.')} <a href="/docs" target="_blank" rel="noreferrer">${t('api_docs', 'Документация API')}</a></p>
      </section>
    </main>`;
    const input = document.getElementById('token-input');
    document.querySelectorAll('[data-lang]').forEach((btn) => btn.addEventListener('click', () => setLang(btn.dataset.lang)));
    document.getElementById('token-toggle').addEventListener('click', () => {
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      document.getElementById('token-toggle').textContent = visible ? t('show', 'Показать') : t('hide', 'Скрыть');
    });
    document.getElementById('login-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = document.getElementById('login-submit');
      const error = document.getElementById('login-error');
      const token = input.value.trim();
      if (!token) { error.textContent = t('enter_key', 'Введите ключ.'); input.focus(); return; }
      button.disabled = true; button.textContent = t('checking', 'Проверяем…'); error.textContent = '';
      try {
        const result = await api('/api/auth/redeem', { method: 'POST', body: JSON.stringify({ token }) });
        state.user = result.user;
        try { state.config = (await api('/api/config')).data; } catch (_) { state.config = null; }
        state.view = state.user.is_admin ? 'admin' : viewFromLocation();
        state.overview = null;
        renderApp();
        if (state.user.is_admin) await loadAdmin();
        else await loadOverview();
        toast(`${t('welcome', 'Добро пожаловать')}, ${state.user.label}`);
      } catch (err) {
        error.textContent = err.message;
        button.disabled = false; button.textContent = t('open_portfolio', 'Открыть портфель');
      }
    });
    input.focus();
  }

  function navButton(view, label, count = '') {
    return `<button data-view="${view}" class="${state.view === view ? 'active' : ''}" title="${esc(label)}"><span class="nav-icon">${icons[view] || '•'}</span><span>${esc(label)}</span>${count !== '' ? `<span class="nav-count">${esc(count)}</span>` : ''}</button>`;
  }

  function syncLabel() { return `${state.config?.twitch_source === 'demo' ? 'DEMO DATA · ' : ''}${t('updated', 'Обновлено')} ${new Date().toLocaleTimeString(state.lang === 'en' ? 'en-US' : 'ru-RU')}`; }
  function updateSyncLabel() { const node = document.getElementById('last-sync'); if (node) node.textContent = syncLabel(); }

  function shell(content) {
    const channels = state.overview?.channels?.length || 0;
    app.innerHTML = `<div class="shell">
      <aside class="sidebar">
        <div class="brand"><span class="brand-mark">${LOGO_SVG}</span><span class="brand-name">twitch <span>viewers system</span></span></div>
        ${state.user?.is_admin ? `<div class="nav-label">${t('operations', 'Operations')}</div><nav class="nav" aria-label="${esc(t('nav_admin', 'Административная навигация'))}">${navButton('admin', t('admin', 'Админ-панель'))}</nav>` : `<div class="nav-label">${t('workspace', 'Workspace')}</div><nav class="nav" aria-label="${esc(t('nav_main', 'Основная навигация'))}">${navButton('portfolio', t('portfolio', 'Портфель'), channels)}${navButton('history', t('history', 'История'))}${navButton('detection', t('detection', 'Детекция накрутки'))}${navButton('alerts', t('alerts', 'Алерты'))}${navButton('api', t('webhooks_and_api', 'Вебхуки и API'))}${navButton('settings', t('settings', 'Настройки'))}</nav>`}
        <div class="sidebar-bottom">
          <div class="user-chip"><span class="avatar">${esc(initials(state.user?.label || 'U'))}</span><span class="user-meta"><strong>${esc(state.user?.label || t('profile', 'Профиль'))}</strong><small>${esc(state.user?.prefix || '')}</small></span></div>
          <a class="sidebar-link" href="/docs" target="_blank" rel="noreferrer">${t('open_api_docs', 'Открыть API docs ↗')}</a>
        </div>
      </aside>
      <section class="main">
        <header class="topbar"><div class="breadcrumb">TVS Analytics <span> / </span> <strong>${esc(viewTitles())}</strong></div><div class="top-actions">${langToggleHtml()}<span class="head-note ${state.config?.twitch_source === 'demo' ? 'demo-note' : ''}" id="last-sync">${syncLabel()}</span><button class="btn btn-quiet" data-action="logout" title="${esc(t('sign_out', 'Выйти'))}">${icons.logout} ${t('sign_out', 'Выйти')}</button></div></header>
        <main class="content" id="content">${content}</main>
      </section>
    </div>`;
    document.querySelectorAll('[data-view]').forEach((node) => node.addEventListener('click', () => switchView(node.dataset.view)));
    document.querySelectorAll('[data-lang]').forEach((btn) => btn.addEventListener('click', () => setLang(btn.dataset.lang)));
    app.onclick = (event) => { if (event.target.closest('[data-action="add"]')) { event.preventDefault(); openAddModal(); } };
    document.querySelector('[data-action="logout"]').addEventListener('click', logout);
  }

  function viewFromLocation() {
    if (window.location.pathname === '/history') return 'history';
    if (window.location.pathname === '/detection') return 'detection';
    return 'portfolio';
  }

  function viewTitles() {
    return ({ portfolio: t('portfolio', 'Портфель'), history: t('history', 'История'), detection: t('detection', 'Детекция накрутки'), alerts: t('alerts', 'Алерты'), api: t('webhooks_and_api', 'Вебхуки и API'), settings: t('settings', 'Настройки'), admin: t('admin', 'Админ-панель') }[state.view] || t('portfolio', 'Портфель'));
  }

  function updateNavActive() {
    document.querySelectorAll('[data-view]').forEach((node) => node.classList.toggle('active', node.dataset.view === state.view));
  }

  function switchView(view) {
    if (state.user?.is_admin && view !== 'admin') view = 'admin';
    state.view = view;
    updateNavActive();
    if (view === 'portfolio') loadOverview();
    if (view === 'history') loadHistoryPage();
    if (view === 'detection') loadDetectionPage();
    if (view === 'api') loadApiPage();
    if (view === 'alerts') loadAlertsPage();
    if (view === 'admin') loadAdmin();
    if (view === 'settings') renderSettings();
  }

  function pageHead(eyebrow, title, subtitle, action = '') {
    return `<div class="page-head"><div><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p class="subtitle">${esc(subtitle)}</p></div>${action}</div>`;
  }

  function renderApp() {
    document.body.classList.remove('login-mode');
    shell(`<div class="loading">${t('loading_data', 'Загружаем данные')}</div>`);
  }

  async function loadOverview(render = true) {
    const previous = state.overview;
    try {
      const result = await api('/api/profile/overview');
      state.overview = result.data;
      if (render) {
        if (state.view === 'portfolio' && previous && document.getElementById('content')) renderPortfolio(true);
        else renderView();
      }
      updateSyncLabel();
    } catch (err) {
      if (err.status === 401) return renderLogin(t('session_expired', 'Сессия истекла. Введите ключ снова.'));
      toast(err.message, 'bad');
    }
  }

  function renderView() {
    if (state.user?.is_admin && state.view !== 'admin') {
      state.view = 'admin';
      return loadAdmin();
    }
    if (state.view === 'portfolio') renderPortfolio();
    else if (state.view === 'history') renderHistoryPage();
    else if (state.view === 'detection') renderDetectionPage();
    else if (state.view === 'api') loadApiPage();
    else if (state.view === 'alerts') loadAlertsPage();
    else if (state.view === 'settings') renderSettings();
    else if (state.view === 'admin') renderAdmin();
  }

  async function loadHistoryPage() {
    const inPlace = state.view === 'history' && Boolean(state.overview) && Boolean(document.getElementById('content'));
    if (!state.overview) {
      try { state.overview = (await api('/api/profile/overview')).data; }
      catch (err) { if (err.status === 401) return renderLogin(t('session_expired', 'Сессия истекла. Введите ключ снова.')); return toast(err.message, 'bad'); }
    }
    const channels = state.overview?.channels || [];
    if (!channels.length) { shell(emptyHtml()); return; }
    if (!state.historyChannel || !channels.some((item) => item.login === state.historyChannel)) state.historyChannel = channels[0].login;
    if (!inPlace) shell(`<div class="loading">${t('loading_history', 'Загружаем историю канала')}</div>`);
    try {
      const result = await api(`/api/profile/channels/${encodeURIComponent(state.historyChannel)}/history?hours=${state.historyRange}`);
      state.history = result.data.points || [];
    } catch (err) { state.history = []; toast(err.message, 'bad'); }
    renderHistoryPage(inPlace);
  }

  function renderHistoryPage(inPlace = false) {
    if (!state.overview) return loadHistoryPage();
    const channels = state.overview.channels || [];
    if (!channels.length) { shell(emptyHtml()); return; }
    const selected = channels.find((item) => item.login === state.historyChannel) || channels[0];
    const recent = (state.history || []).slice(-12).reverse();
    const rangeButtons = [[24, t('hours_24', '24 часа')], [168, t('days_7', '7 дней')], [720, t('days_30', '30 дней')]].map(([hours, label]) => `<button class="${state.historyRange === hours ? 'active' : ''}" data-history-range="${hours}">${label}</button>`).join('');
    const picker = channels.map((item) => `<button class="history-channel ${item.login === selected.login ? 'active' : ''}" data-history-channel="${esc(item.login)}"><span class="channel-avatar">${esc(initials(item.login))}</span><span><strong>#${esc(item.login)}</strong><small class="${item.is_live ? 'status-live' : 'status-offline'}">${item.is_live ? t('live_status', 'в сети') : t('offline_status', 'офлайн')}</small></span></button>`).join('');
    const observations = recent.length ? `<div class="table-wrap"><table><thead><tr><th>${t('time', 'Время')}</th><th>${t('total', 'Всего')}</th><th>${t('in_chat', 'В чате')}</th><th>${t('guests', 'Гости')}</th><th>${t('ratio', 'Ratio')}</th></tr></thead><tbody>${recent.map((point) => `<tr><td>${esc(date(point.ts))}</td><td class="num">${fmt(point.total)}</td><td class="num">${fmt(point.authorized)}</td><td class="num">${fmt(point.guests)}</td><td class="num">${pct(point.chat_ratio)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="subtitle">${t('obs_after_poller', 'Наблюдения появятся после следующего цикла poller.')}</p>`;
    const content = `${pageHead('Timeline explorer', t('channel_history', 'История каналов'), t('channel_history_sub', 'Отдельный просмотр наблюдений, аномалий и причин индекса.')) }<div class="history-toolbar"><div class="history-picker" tabindex="0" aria-label="${esc(t('picker_hint', 'Каналы истории. Используйте Shift и колесо мыши'))}">${picker}</div><div class="history-range">${rangeButtons}</div></div>${detailHtml(selected.login, selected, state.historyRange)}<section class="panel-card history-observations"><div class="panel-head"><div><h2>${t('recent_obs', 'Последние наблюдения')}</h2><small>${esc(selected.login)} · ${state.historyRange} ${t('hours_short', 'ч')}</small></div></div>${observations}</section>`;
    if (inPlace && document.getElementById('content')) document.getElementById('content').innerHTML = content;
    else shell(content);
    document.querySelectorAll('[data-history-channel]').forEach((node) => node.addEventListener('click', () => { state.historyChannel = node.dataset.historyChannel; state.history = null; loadHistoryPage(); }));
    document.querySelector('.history-picker')?.addEventListener('wheel', (event) => { if (event.shiftKey || Math.abs(event.deltaY) > Math.abs(event.deltaX)) { event.preventDefault(); event.currentTarget.scrollLeft += event.deltaY; } }, { passive: false });
    document.querySelectorAll('[data-history-range]').forEach((node) => node.addEventListener('click', () => { state.historyRange = Number(node.dataset.historyRange); state.history = null; loadHistoryPage(); }));
    const chart = document.getElementById('channel-chart');
    if (chart) { chart.innerHTML = chartSvg(state.history || [], 40); bindChartTooltip(); }
    updateSyncLabel();
  }

  function renderPortfolio(inPlace = false) {
    if (!state.overview) { shell(`<div class="loading">${t('loading_portfolio', 'Загружаем портфель')}</div>`); return; }
    const data = state.overview;
    const channels = (data.channels || []).filter((item) => {
      const matchesSearch = !state.filter || item.login.toLowerCase().includes(state.filter.toLowerCase());
      const matchesStatus = state.statusFilter === 'all' || (state.statusFilter === 'live' && item.is_live) || (state.statusFilter === 'flagged' && item.score?.verdict === 'red');
      return matchesSearch && matchesStatus;
    });
    const kpis = data.kpis || {};
    const action = `<button class="btn btn-primary" data-action="add">${t('add_channel_btn', '＋ Добавить канал')}</button>`;
    const content = `${pageHead('Portfolio intelligence', t('portfolio_title', 'Портфель каналов'), t('portfolio_subtitle', 'Наблюдение, аномалии и свежесть данных в одном экране.'), action)}
      <div class="kpi-grid">
        ${kpi(t('channels_tracked', 'Каналов в списке'), fmt(kpis.channels), t('all_profile_channels', 'все добавленные профилем'))}
        ${kpi(t('total_viewers', 'Суммарно зрителей'), fmt(kpis.total_viewers), `${kpis.live || 0} ${t('currently_live', 'сейчас в эфире')}`, 'good')}
        ${kpi(t('flagged', 'Помечено флагом'), fmt(kpis.flagged), t('score_above_60', 'score выше 60'), (kpis.flagged || 0) > 0 ? 'bad' : 'good')}
        ${kpi(t('refresh_rate', 'Обновление'), t('sec_30', '30 сек'), t('bg_poller_60', 'фоновый poller · 60 сек'))}
      </div>
      <div class="toolbar"><div class="toolbar-left"><input class="input search" id="channel-search" value="${esc(state.filter)}" placeholder="${esc(t('search_channel', 'Найти канал…'))}" aria-label="${esc(t('search_channel', 'Найти канал…'))}"></div><div class="toolbar-right"><div class="filter-group"><button class="${state.statusFilter === 'all' ? 'active' : ''}" data-filter="all">${t('all', 'Все')} · ${(data.channels || []).length}</button><button class="${state.statusFilter === 'live' ? 'active' : ''}" data-filter="live">${t('live', 'Live')} · ${(data.channels || []).filter((item) => item.is_live).length}</button><button class="${state.statusFilter === 'flagged' ? 'active' : ''}" data-filter="flagged">${t('flagged_tab', 'Подозрительные')} · ${kpis.flagged || 0}</button></div><button class="btn btn-sm" data-action="refresh">${t('refresh', 'Обновить')}</button></div></div>
      ${state.config?.twitch_source === 'demo' ? `<div class="callout demo-callout">${t('demo_note', 'Показан <strong>демо-режим</strong>: цифры синтетические и не отражают Twitch. Для реальных данных установите TWITCH_SOURCE=gql и перезапустите poller.')}</div>` : ''}
      ${channels.length ? `<section class="table-card"><div class="table-wrap"><table><thead><tr><th>${t('channel', 'Канал')}</th><th>${t('stream', 'Эфир')}</th><th>${t('total', 'Всего')}</th><th>${t('in_chat', 'В чате')}</th><th>${t('guests', 'Гости')}</th><th>${t('ratio', 'Ratio')}</th><th>${t('index', 'Индекс')}</th><th>${t('trend', 'Динамика')}</th><th>${t('freshness', 'Свежесть')}</th></tr></thead><tbody>${channels.map(channelRow).join('')}</tbody></table></div></section>${state.selected ? detailHtml(state.selected, data.channels.find((item) => item.login === state.selected) || {}) : ''}` : emptyHtml()}`;
    if (inPlace && document.getElementById('content')) document.getElementById('content').innerHTML = content;
    else shell(content);
document.querySelector('[data-action="refresh"]')?.addEventListener('click', () => loadOverview());
    document.querySelectorAll('tr[data-channel]').forEach((row) => row.addEventListener('click', () => selectChannel(row.dataset.channel)));
    document.querySelectorAll('.channel-link').forEach((link) => link.addEventListener('click', (event) => event.stopPropagation()));
    document.querySelectorAll('[data-risk-report]').forEach((flag) => flag.addEventListener('click', (event) => { event.stopPropagation(); openRiskReport(flag.dataset.riskReport, data.channels.find((item) => item.login === flag.dataset.riskReport)); }));
    const chart = document.getElementById('channel-chart');
    if (chart) { chart.innerHTML = chartSvg(state.history || [], 30); bindChartTooltip(); }
    document.getElementById('channel-search')?.addEventListener('input', (event) => { state.filter = event.target.value; renderView(); });
    document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => { state.statusFilter = button.dataset.filter; renderView(); }));
    document.querySelectorAll('[data-remove-channel]').forEach((button) => button.addEventListener('click', (event) => { event.stopPropagation(); removeChannel(button.dataset.removeChannel); }));
  }

  function kpi(label, value, foot, kind = '') { return `<article class="kpi"><span class="kpi-label">${esc(label)}</span><strong class="kpi-value">${esc(value)}</strong><span class="kpi-foot ${kind}">${esc(foot)}</span></article>`; }
  function emptyHtml() { return `<section class="table-card empty"><div class="empty-orb">＋</div><h2>${t('portfolio_empty', 'Портфель пуст')}</h2><p>${t('portfolio_empty_desc', 'Добавьте одного или нескольких Twitch-стримеров. Можно вставить ссылки в одно поле — мы сами нормализуем имена и запустим наблюдение.')}</p><button class="btn btn-primary" data-action="add">${t('add_channel', 'Добавить канал')}</button></section>`; }
  function channelRow(item) {
    const score = item.score || {};
    const verdict = score.verdict || 'nd';
    const verdictLabel = { green: t('normal', 'норма'), yellow: t('warning', 'внимание'), red: t('flag', 'флаг'), nd: t('provisional', 'предварительно') }[verdict] || t('na', 'н/д');
    const cls = verdict === 'red' ? 'badge-bad' : verdict === 'yellow' ? 'badge-warn' : verdict === 'green' ? 'badge-good' : 'badge-neutral';
    const trend = item.trend?.length ? item.trend : (state.history && state.selected === item.login ? state.history : []);
    const sourceNote = state.config?.twitch_source === 'demo' ? ' <span class="badge badge-warn">DEMO</span>' : '';
    const flag = score.verdict === 'red' ? `<button class="risk-flag" data-risk-report="${esc(item.login)}" title="${esc((score.factors || []).map(factorNote).filter(Boolean).join('; ') || scoreExplanation(score) || t('need_more_observations', 'Нужны дополнительные наблюдения'))}" aria-label="${esc(t('suspicious_anomaly', 'Подозрительная аномалия'))}">!</button>` : '';
    return `<tr data-channel="${esc(item.login)}" class="${state.selected === item.login ? 'selected' : ''}"><td><div class="channel-cell"><span class="channel-avatar">${esc(initials(item.login))}</span><span><a class="channel-name channel-link" href="https://twitch.tv/${encodeURIComponent(item.login)}" target="_blank" rel="noopener noreferrer">#${esc(item.login)}</a>${flag}<small class="channel-sub" title="${esc(item.title || t('title_unavailable', 'Название недоступно'))}">${esc(item.title || t('title_unavailable', 'Название недоступно'))}</small></span></div></td><td><span class="live-dot ${item.is_live ? 'on' : ''}"></span><span class="${item.is_live ? 'status-live' : 'status-offline'}">${item.is_live ? t('live_status', 'в сети') : t('offline_status', 'офлайн')}</span>${sourceNote}</td><td class="num">${fmt(item.total_viewers)}</td><td class="num">${fmt(item.authorized)}</td><td class="num">${fmt(item.guests)}</td><td class="num">${pct(item.chat_ratio)}</td><td><span class="badge ${cls}">${esc(verdictLabel)} ${score.risk_score ?? '—'}</span></td><td>${sparkline(trend)}</td><td class="muted">${item.stale ? t('stale', 'устарело') : age(item.fetched_at)}</td></tr>`;
  }
  function openRiskReport(login, item = {}) {
    const score = item.score || {};
    const factors = score.factors || [];
    const warnings = warningList(score);
    const factorRows = factors.length ? factors.map((factor) => `<div class="factor"><div class="factor-top"><span>${esc(factorLabel(factor.code))}</span><strong>${fmt(Math.round((factor.score || 0) * 100))}%</strong></div><div class="factor-bar"><span style="width:${Math.max(3, Math.min(100, (factor.score || 0) * 100))}%"></span></div><p>${esc(factorNote(factor))}</p></div>`).join('') : `<p class="subtitle">${esc(t('no_factors_yet', 'Для этого канала ещё недостаточно факторов. Продолжайте наблюдение.'))}</p>`;
    const warningHtml = warnings.length ? `<div class="callout">${warnings.map((warning) => esc(warning)).join('<br>')}</div>` : '';
    const modal = modalShell(t('detailed_report', 'Подробный отчёт'), `#${login} · ${score.verdict === 'red' ? t('increased_attention', 'повышенное внимание') : t('monitoring', 'наблюдение')}`, `<div class="risk-report"><div class="risk-report-head"><div><span class="badge badge-bad">${t('index', 'Индекс')} ${score.risk_score ?? '—'} / 100</span><p>${esc(scoreExplanation(score) || t('provisional', 'Индекс пока предварительный.'))}</p></div><span class="risk-report-score">${score.confidence == null ? '—' : pct(score.confidence)}<small>confidence</small></span></div><h3>${t('reasons', 'Причины')}</h3>${factorRows}${warningHtml}<div class="modal-actions"><button class="btn" data-download="/api/profile/channels/${encodeURIComponent(login)}/report?format=pdf&hours=24" data-filename="${esc(`${login}-24h.pdf`)}">${t('report_pdf', 'Отчёт PDF')}</button><button class="btn btn-primary" data-history-from-report>${t('open_history', 'Открыть историю')}</button></div></div>`);
    modal.root.querySelector('[data-history-from-report]').addEventListener('click', () => { modal.close(); selectChannel(login); });
  }


  function bindChartTooltip() {
    const wrap = document.getElementById('channel-chart');
    if (!wrap) return;
    const hits = wrap.querySelectorAll('[data-tip-time]');
    if (!hits.length) return;
    let tip = wrap.querySelector('.chart-tip');
    if (!tip) { tip = document.createElement('div'); tip.className = 'chart-tip'; wrap.appendChild(tip); }
    const svg = wrap.querySelector('svg');
    const width = svg?.viewBox?.baseVal?.width || 860;
    const height = svg?.viewBox?.baseVal?.height || 270;
    const show = (node) => {
      tip.innerHTML = `<span class="chart-tip-time">${esc(node.dataset.tipTime)}</span><span class="chart-tip-row"><i class="dot-total"></i>${esc(node.dataset.tipViewers)} ${esc(t('viewers', 'зрителей'))}</span><span class="chart-tip-row"><i class="dot-chat"></i>${esc(node.dataset.tipChat)} ${esc(t('in_chat_short', 'в чате'))}</span>${node.dataset.tipCapped === '1' ? `<span class="chart-tip-note">${esc(t('chat_capped_note', 'Twitch показал больше людей в чате, чем зрителей, поэтому значение ограничено числом зрителей.'))}</span>` : ''}`;
      tip.classList.add('visible');
      const cx = Number(node.getAttribute('cx')) / width;
      const cy = Number(node.getAttribute('cy')) / height;
      tip.style.left = `${cx * 100}%`;
      tip.style.top = `${cy * 100}%`;
      tip.classList.toggle('flip', cx > 0.7);
    };
    const hide = () => tip.classList.remove('visible');
    hits.forEach((node) => {
      node.addEventListener('pointerenter', () => show(node));
      node.addEventListener('focus', () => show(node));
      node.addEventListener('pointerleave', hide);
      node.addEventListener('blur', hide);
    });
  }
  // Internal identifiers must never reach the UI. Every metric name, ad-break
  // kind and `observed` key has its own entry in BOTH dictionaries (the key
  // sets were measured off real report payloads), so these helpers cannot fall
  // back to a raw code; the last resort is a de-underscored word, never `roster`.
  const humanize = (key) => String(key ?? '').replace(/_/g, ' ');
  const metricLabel = (key) => t(`metric_${key}`, humanize(key));
  const observedLabel = (key) => t(`ev_${key}`, humanize(key));
  const breakKindLabel = (kind) => t(`metric_${kind}`, humanize(kind));
  const unavailableDetail = (item) => t(item?.code || '', item?.detail || '');
  // Item 5 surface: the proxy is shown as a proxy, and only when the detector
  // actually produced numbers -- a channel with no readable chat is not given
  // a fabricated zero.
  function chatRatePanelHtml(report) {
    const factor = (report?.factors || []).find((item) => item.code === 'message_rate');
    const observed = factor?.observed;
    if (!observed || observed.source == null) return '';
    const rows = [
      [t('detection_rate_per_minute', 'Изменение в минуту'), fmt(observed.messages_per_minute)],
      [t('detection_rate_stale', 'Минут без изменений'), `${fmt(observed.stale_minutes)} / ${fmt(observed.minutes)}`],
      [t('ev_chatter_turnover', 'оборот чата'), fmt(observed.chatter_turnover)],
      [t('detection_rate_source', 'Источник'), esc(t(`src_${observed.source}`, humanize(observed.source)))],
    ].map(([label, value]) => `<div class="list-row"><strong>${esc(label)}</strong><span class="num">${value}</span></div>`).join('');
    return `<section class="panel-card"><div class="panel-head"><div><h2>${t('detection_rate_title', 'Активность чата (прокси)')}</h2><small>${t('detection_rate_sub', 'Анонимный клиент не читает сообщения: это изменение числа активных авторов, а не счётчик реплик.')}</small></div></div><div class="list">${rows}</div></section>`;
  }

  function detailHtml(login, item, hours = 24) {
    const score = item.score || {};
    const factors = score.factors || [];
    const chatShown = (state.history || []).some((point) => Number(point.authorized ?? point.chat ?? point.chatters ?? 0) > 0);
    return `<div class="detail-grid"><section class="panel-card"><div class="panel-head"><div><h2>${esc(login)} — ${t('detail_chart_title', 'история зрителей и чата')}</h2><small>${esc(windowCaption(hours, state.history))}</small></div><div class="toolbar-right"><button class="btn btn-sm" data-download="/api/profile/channels/${encodeURIComponent(login)}/export?hours=${hours}" data-filename="${esc(`${login}-${hours}h.csv`)}">${t('export_csv', 'Экспорт CSV')}</button><button class="btn btn-sm" data-download="/api/profile/channels/${encodeURIComponent(login)}/report?format=pdf&hours=${hours}" data-filename="${esc(`${login}-${hours}h.pdf`)}">${t('report_pdf', 'Отчёт PDF')}</button></div></div><div class="chart-wrap" id="channel-chart"></div><div class="legend"><span><i></i>${t('total_viewers_chart', 'Всего зрителей')}</span><span><i class="chat-legend"></i>${t('in_chat_approx', 'В чате (примерно)')}</span></div><p class="helper chart-note">${t('chart_note', 'Ровные участки означают, что Twitch не изменил счётчик между наблюдениями; это не ошибка графика.')}${chatShown ? ` ${t('chart_shared_scale', 'Обе линии используют одну шкалу, поэтому расстояние между ними равно разнице в людях.')}` : ''}</p></section><section class="panel-card score-panel"><div class="panel-head"><div><h2>${t('risk_breakdown', 'Разбор индекса')}</h2><small>${scoreExplanation(score) || t('insufficient_data', 'Данных пока недостаточно для вывода.')}</small></div></div>${scoreRing(score)}${factors.length ? factors.map(factorHtml).join('') : `<div class="callout">${t('collect_more', 'Соберите ещё несколько наблюдений, чтобы увидеть объяснение индекса.')}</div>`}</section></div>`;
  }
  // The range selector already says "24 часа"; repeating "последние
  // сохранённые наблюдения" underneath it told the user nothing, and the
  // actual data range is what they were missing. Empty history prints no
  // range at all rather than "нет данных".
  function observedRangeCaption(points) {
    const rows = (Array.isArray(points) ? points : []).filter((point) => point && (point.ts || point.observed_at));
    if (!rows.length) return '';
    const first = date(rows[0].ts || rows[0].observed_at);
    const last = date(rows[rows.length - 1].ts || rows[rows.length - 1].observed_at);
    if (first === '—' || last === '—') return '';
    return `${first} → ${last}`;
  }

  function windowCaption(hours, points) {
    const label = hours >= 168 ? `${Math.round(hours / 24)} ${t('days_7', 'дней')}` : `${hours} ${t('hours_24', 'часа')}`;
    const range = observedRangeCaption(points);
    return range ? `${label} · ${range}` : label;
  }

  function factorHtml(factor) { return `<div class="factor"><div class="factor-top"><span>${esc(factorLabel(factor.code))}</span><strong>${fmt(Math.round((factor.score || 0) * 100))}%</strong></div><div class="factor-bar"><span style="width:${Math.max(3, Math.min(100, (factor.score || 0) * 100))}%"></span></div><p>${esc(factorNote(factor))}</p></div>`; }
  function scoreRing(score) { const value = score.risk_score ?? 0; const color = score.verdict === 'red' ? 'var(--red)' : score.verdict === 'yellow' ? 'var(--amber)' : 'var(--green)'; return `<div class="score-ring" style="--score:${value};--ring-color:${color}"><strong>${value === null || value === undefined ? '—' : Math.round(value)}</strong><small>/ 100</small></div><p class="subtitle" style="text-align:center">${t('confidence', 'Confidence')} ${score.confidence == null ? '—' : pct(score.confidence)} · ${score.samples_used || 0} ${t('observations', 'наблюдений')} · ${({ green: t('normal', 'норма'), yellow: t('warning', 'внимание'), red: t('high_risk', 'высокий риск') }[score.verdict]) || t('provisional', 'предварительно')}</p>`; }

  function sparkline(points) {
    const values = points.map((p) => Number(p.total ?? p.viewers ?? 0)).filter((value) => Number.isFinite(value));
    if (!values.length) return '<span class="muted">—</span>';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const coords = values.length === 1 ? '0,12 80,12' : values.map((value, index) => `${(index / (values.length - 1)) * 80},${23 - ((value - min) / range) * 20}`).join(' ');
    return `<svg class="sparkline" viewBox="0 0 80 24" aria-label="${esc(t('trend_aria', 'Динамика канала'))}"><polyline points="${coords}"></polyline></svg>`;
  }

  function downsampleSeries(points, max) {
    if (!Array.isArray(points) || points.length <= max || max < 2) return points;
    const step = (points.length - 1) / (max - 1);
    const result = [];
    for (let index = 0; index < max; index += 1) result.push(points[Math.round(index * step)]);
    return result;
  }
  // Event layers: WHEN things happened, not just the curve. Everything comes
  // from data the report already carries (findings, ad-break estimates, the
  // points themselves) -- no new endpoint. An empty list renders no bars and
  // the chart looks exactly as it did before.
  const EVENT_KINDS = {
    spike: { cls: 'event-spike', label: () => t('event_spike', 'Скачок онлайна') },
    ad: { cls: 'event-ad', label: () => t('event_ad', 'Признак рекламы (прокси)') },
    change: { cls: 'event-change', label: () => t('event_change', 'Смена названия или категории') },
    stream: { cls: 'event-stream', label: () => t('event_stream', 'Граница эфира') },
  };
  const MAX_EVENTS = 25;

  function collectChartEvents(report, points) {
    const rows = Array.isArray(points) ? points : [];
    const stamps = rows.map((point) => new Date(point.ts || point.observed_at).getTime()).filter((value) => Number.isFinite(value));
    if (!stamps.length) return { events: [], thinned: false };
    const first = Math.min(...stamps);
    const last = Math.max(...stamps);
    const inside = (moment) => {
      const value = new Date(moment).getTime();
      return Number.isFinite(value) && value >= first && value <= last;
    };
    const events = [];
    const add = (moment, kind, detail) => { if (inside(moment)) events.push({ ts: moment, kind, detail: detail || '' }); };

    for (const item of (report?.ad_vs_nonad?.breaks || [])) add(item.ts, 'change', breakKindLabel(item.kind));
    for (const factor of (report?.factors || [])) {
      const observed = factor.observed || {};
      if (observed.peak_ts) add(observed.peak_ts, 'spike', factorLabel(factor.code));
      else if (observed.start_ts) add(observed.start_ts, 'spike', factorLabel(factor.code));
    }

    // Stream boundaries: a live->offline->live transition in the series, i.e.
    // a value of 0 between two positive runs. The first and last observed point
    // are NOT boundaries: the window simply starts and ends there.
    const live = rows.map((point) => Number(point.total ?? point.viewers));
    for (let index = 1; index < live.length; index += 1) {
      const before = live[index - 1];
      const after = live[index];
      const moment = rows[index].ts || rows[index].observed_at;
      if (before > 0 && after === 0) add(moment, 'stream', t('event_stream_end', 'эфир закончился'));
      else if (before === 0 && after > 0) add(moment, 'stream', t('event_stream_start', 'эфир начался'));
    }

    const unique = new Map();
    for (const item of events) {
      const key = `${new Date(item.ts).toISOString()}|${item.kind}`;
      if (!unique.has(key)) unique.set(key, item);
    }
    const ordered = [...unique.values()].sort((left, right) => new Date(left.ts) - new Date(right.ts));
    if (ordered.length <= MAX_EVENTS) return { events: ordered, thinned: false };
    // Past the cap, thin the list out and say so in the UI rather than
    // rendering an unreadable picket fence.
    const step = ordered.length / MAX_EVENTS;
    const kept = Array.from({ length: MAX_EVENTS }, (_, index) => ordered[Math.floor(index * step)]);
    return { events: kept, thinned: true };
  }

  function eventLegendHtml(events) {
    if (!events.length) return '';
    const kinds = [...new Set(events.map((item) => item.kind))].filter((kind) => EVENT_KINDS[kind]);
    const items = kinds.map((kind) => `<span class="key-${kind}"><i class="event-key"></i>${esc(EVENT_KINDS[kind].label())}</span>`);
    return `<div class="legend legend-events">${items.join('')}</div>`;
  }


  function chartSvg(points, maxPoints = 30, events = []) {
    if (!Array.isArray(points) || !points.length) return `<div class="empty"><p>${t('no_history', 'История ещё не накопилась.')}</p></div>`;
    const hasNumericObservation = points.some((point) => point.total != null || point.viewers != null);
    if (!hasNumericObservation) return `<div class="chart-empty"><strong>${t('no_numeric', 'Нет числовых наблюдений')}</strong><span>${t('channel_offline_note', 'Канал сейчас офлайн. График появится после следующего live-наблюдения.')}</span></div>`;
    points = downsampleSeries(points, Math.max(2, Number(maxPoints) || 30));
    const totalValues = points.map((point) => Number(point.total ?? point.viewers ?? 0));
    const chatValues = points.map((point) => Number(point.authorized ?? point.chat ?? point.chatters ?? 0));
    const width = 860;
    const height = 270;
    const left = 56;
    const right = 66;
    const top = 24;
    const bottom = 38;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const chatPresent = chatValues.some((value) => Number.isFinite(value) && value > 0);
    // Both series share ONE scale. Previously each line was stretched to its own
    // min/max, so both always filled the plot height and the vertical distance
    // between them said nothing about the real difference in people.
    const axisValues = chatPresent ? totalValues.concat(chatValues) : totalValues;
    const axisMin = Math.min(...axisValues);
    const axisMax = Math.max(...axisValues);
    const axisRange = axisMax - axisMin || 1;
    const x = (index) => left + (index / Math.max(1, points.length - 1)) * plotWidth;
    const yAxis = (value) => top + plotHeight - ((value - axisMin) / axisRange) * plotHeight;
    const yTotal = yAxis;
    const yChat = yAxis;
    const totalCoords = totalValues.length === 1 ? `${left},${yTotal(totalValues[0])} ${left + plotWidth},${yTotal(totalValues[0])}` : totalValues.map((value, index) => `${x(index)},${yTotal(value)}`).join(' ');
    const area = `${left},${top + plotHeight} ${totalCoords} ${left + plotWidth},${top + plotHeight}`;
    const chatCoords = chatValues.length === 1 ? `${left},${yChat(chatValues[0])} ${left + plotWidth},${yChat(chatValues[0])}` : chatValues.map((value, index) => `${x(index)},${yChat(value)}`).join(' ');
    const grid = [0, 1, 2, 3].map((index) => {
      const y = top + index * plotHeight / 3;
      const axisValue = axisMax - index * axisRange / 3;
      const label = esc(compact(axisValue));
      return `<line class="chart-grid" x1="${left}" y1="${y}" x2="${left + plotWidth}" y2="${y}"/><text class="chart-label" x="${left - 8}" y="${y + 4}" text-anchor="end">${label}</text>${chatPresent ? `<text class="chart-label chart-label-right" x="${left + plotWidth + 8}" y="${y + 4}">${label}</text>` : ''}`;
    }).join('');
    const totalDots = totalValues.map((value, index) => `<circle class="chart-point-total" cx="${x(index)}" cy="${yTotal(value)}" r="2.5"><title>${esc(date(points[index].ts || points[index].observed_at))}: ${fmt(value)} ${t('viewers', 'зрителей')}</title></circle>`).join('');
    const chatDots = chatPresent ? chatValues.map((value, index) => `<circle class="chart-point-chat" cx="${x(index)}" cy="${yChat(value)}" r="2.5"><title>${esc(date(points[index].ts || points[index].observed_at))}: ${fmt(value)} ${t('in_chat_word', 'в чате')}</title></circle>`).join('') : '';
    // The hover targets are drawn at BOTH series positions. They used to be
    // centred only on the viewers point, so the cyan "in chat" dots — which sit
    // at a different height whenever the two lines diverge — had no hit area
    // at all and showed nothing on hover. One target per point per line keeps
    // both dots hoverable; the viewer hit is painted first so it wins where
    // the lines cross.
    const chartHits = totalValues.map((value, index) => {
      const point = points[index];
      const chatValue = chatPresent ? chatValues[index] : null;
      const moment = esc(date(point.ts || point.observed_at));
      const viewers = esc(fmt(value));
      // chat_ratio is clamped to 1.0 upstream when Twitch reports more chatters
      // than viewers, so raw_chat_ratio > 1 tells us the number was capped.
      const capped = Number(point.raw_chat_ratio) > 1;
      const chat = esc(chatValue == null ? '—' : `${capped ? '≥ ' : ''}${fmt(chatValue)}`);
      const tip = `data-tip-time="${moment}" data-tip-viewers="${viewers}" data-tip-chat="${chat}" data-tip-capped="${capped ? '1' : '0'}"`;
      const title = `${moment}: ${viewers} ${t('viewers', 'зрителей')}, ${chat} ${t('in_chat_word', 'в чате')}`;
      const chatHit = chatPresent && chatValue != null
        ? `<circle class="chart-hit chart-hit-chat" cx="${x(index)}" cy="${yChat(chatValue)}" r="11" tabindex="0" role="img" ${tip}><title>${title}</title></circle>`
        : '';
      return `<circle class="chart-hit" cx="${x(index)}" cy="${yTotal(value)}" r="11" tabindex="0" role="img" ${tip}><title>${title}</title></circle>${chatHit}`;
    }).join('');
    // Event bars span the plot height and sit BEHIND the series lines. The
    // transparent hit line is a separate element so the bar itself can stay
    // thin while the hover target stays finger-wide.
    const stamps = points.map((point) => new Date(point.ts || point.observed_at).getTime()).filter((value) => Number.isFinite(value));
    const spanStart = stamps.length ? Math.min(...stamps) : 0;
    const spanEnd = stamps.length ? Math.max(...stamps) : 1;
    const eventBars = (Array.isArray(events) ? events : []).map((item) => {
      const moment = new Date(item.ts).getTime();
      if (!Number.isFinite(moment)) return '';
      const share = spanEnd > spanStart ? (moment - spanStart) / (spanEnd - spanStart) : 0;
      const cx = left + Math.max(0, Math.min(1, share)) * plotWidth;
      const kind = EVENT_KINDS[item.kind] ? item.kind : 'change';
      const title = `${EVENT_KINDS[kind].label()}${item.detail ? ` · ${item.detail}` : ''} · ${date(item.ts)}`;
      return `<g><line class="chart-event-hit" x1="${cx}" y1="${top}" x2="${cx}" y2="${top + plotHeight}" tabindex="0" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title></line><line class="chart-event ${EVENT_KINDS[kind].cls}" x1="${cx}" y1="${top}" x2="${cx}" y2="${top + plotHeight}"/></g>`;
    }).join('');
    const lastTotalY = yTotal(totalValues[totalValues.length - 1]);
    const lastChatY = yChat(chatValues[chatValues.length - 1]);
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(t('chart_aria', 'История зрителей и людей в чате'))}"><defs><linearGradient id="chartGradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#a875ff"/><stop offset="1" stop-color="#a875ff" stop-opacity="0"/></linearGradient></defs>${grid}${eventBars}<line class="chart-last-line chart-last-total" x1="${left}" y1="${lastTotalY}" x2="${left + plotWidth}" y2="${lastTotalY}"/>${chatPresent ? `<line class="chart-last-line chart-last-chat" x1="${left}" y1="${lastChatY}" x2="${left + plotWidth}" y2="${lastChatY}"/>` : ''}<text class="chart-axis-title" x="${left - 8}" y="${top - 8}" text-anchor="end">${t('viewers', 'зрители')}</text>${chatPresent ? `<text class="chart-axis-title" x="${left + plotWidth + 8}" y="${top - 8}">${t('in_chat_word', 'в чате')}</text>` : ''}<polygon class="chart-area" points="${area}"/><polyline class="chart-line" points="${totalCoords}"/>${chatPresent ? `<polyline class="chart-chat" points="${chatCoords}"/>` : ''}${totalDots}${chatDots}${chartHits}<text class="chart-label" x="${left}" y="${height - 10}">${esc(date(points[0].ts || points[0].observed_at))}</text><text class="chart-label" text-anchor="end" x="${left + plotWidth}" y="${height - 10}">${esc(date(points[points.length - 1].ts || points[points.length - 1].observed_at))}</text></svg>`;
  }

  async function selectChannel(login) { state.selected = login; state.view = 'portfolio'; renderView(); try { const result = await api(`/api/profile/channels/${encodeURIComponent(login)}/history?hours=24`); state.history = result.data.points || []; } catch (err) { toast(err.message, 'bad'); } renderView(); }

  function verdictBadge(verdict) {
    const map = {
      green: ['badge-good', t('normal', 'норма')],
      yellow: ['badge-warn', t('warning', 'внимание')],
      red: ['badge-bad', t('flag', 'флаг')],
      nd: ['badge-neutral', t('provisional', 'предварительно')],
    };
    const [cls, label] = map[verdict] || map.nd;
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }

  // Some `observed` VALUES are codes too, not just the keys: `source` is a
  // data-source name and `triggered_by` is a list of factor codes. Both are
  // rendered as labels here, so a raw `chatters_proxy` never reaches the page.
  const OBSERVED_VALUE_LABEL = {
    source: (value) => t(`src_${value}`, humanize(value)),
    triggered_by: (value) => (Array.isArray(value) ? value : [value]).map((code) => factorLabel(code)).join(', '),
  };

  function observedValueText(key, value) {
    const label = OBSERVED_VALUE_LABEL[key];
    if (label) return label(value);
    return Array.isArray(value) ? value.join(', ') : (typeof value === 'object' ? JSON.stringify(value) : value);
  }

  function observedHtml(observed) {
    const entries = Object.entries(observed || {}).filter(([, value]) => value !== null && value !== undefined && value !== '');
    if (!entries.length) return '';
    const cells = entries.map(([key, value]) => {
      const text = observedValueText(key, value);
      return `<div class="observed-cell"><dt>${esc(observedLabel(key))}</dt><dd>${esc(fmt(text))}</dd></div>`;
    }).join('');
    return `<dl class="observed-grid">${cells}</dl>`;
  }

  // The caveat note interpolates `triggered_by` into a sentence, so the args
  // carry translated factor labels rather than raw codes.
  function detectionFactorHtml(factor) {
    const args = { ...(factor.note_args || {}) };
    if (Array.isArray(args.triggered_by)) args.triggered_by = args.triggered_by.map((code) => factorLabel(code)).join(', ');
    const localised = args.triggered_by ? { ...factor, note_args: args } : factor;
    return factorHtml(localised) + observedHtml(factor.observed);
  }


  function adComparisonHtml(comparison) {
    const head = `<div class="panel-head"><div><h2>${t('detection_ad_title', 'Реклама: сравнение окон')}</h2><small>${t('detection_ad_proxy', 'Анонимный клиент не читает adBreak, поэтому это инференциальная оценка по косвенным признакам.')}</small></div></div>`;
    if (!comparison || !comparison.available) {
      const reason = comparison?.reason || t('detection_ad_none', 'Рекламные паузы не обнаружены, сравнение недоступно.');
      return `<section class="panel-card">${head}<div class="callout">${esc(reason)}</div></section>`;
    }
    const windowRow = (label, window) => {
      if (!window) return '';
      return `<div class="list-row"><div><strong>${esc(label)}</strong><small>${fmt(window.minutes)} ${t('detection_minutes', 'минут')} · ${fmt(window.points)} ${t('detection_points', 'точек')}</small></div><span class="num">${t('detection_growth', 'рост')} ${fmt(window.viewer_growth_ratio)} · ${t('in_chat_word', 'в чате')} ${pct(window.chat_ratio_median)} · ${fmt(window.followers_per_hour)} ${t('followers_label', 'подписчиков')}/ч</span></div>`;
    };
    const breaks = (comparison.breaks || []).slice(0, 8).map((item) => `<span class="badge badge-neutral">${esc(breakKindLabel(item.kind))} · ${esc(date(item.ts))}</span>`).join(' ');
    return `<section class="panel-card">${head}<div class="list">${windowRow(t('detection_ad_window', 'Окна рекламных пауз'), comparison.ad_window)}${windowRow(t('detection_ad_rest', 'Остальное время'), comparison.rest_window)}</div><p class="helper">${esc(comparison.note || '')}</p><div class="score-tags">${breaks || `<span class="badge badge-neutral">${t('detection_no_breaks', 'перерывов не найдено')}</span>`}</div></section>`;
  }

  function chattersEvidenceHtml(roster) {
    const sample = roster?.sample;
    if (!sample) return `<div class="callout">${esc(roster?.note || t('detection_no_sample', 'Выборка чаттеров ещё не собрана.') )}</div>`;
    const accounts = roster.accounts || [];
    const rows = accounts.slice(0, 100).map((item) => `<tr><td><a class="channel-link" href="https://twitch.tv/${encodeURIComponent(item.login)}" target="_blank" rel="noopener noreferrer">${esc(item.login)}</a></td><td class="num">${item.account_age_days == null ? '—' : fmt(item.account_age_days)}</td><td class="num">${fmt(item.followers)}</td><td>${esc(date(item.created_at))}</td></tr>`).join('');
    const roles = Object.entries(sample.roles || {}).map(([role, logins]) => `${esc(role)}: ${logins.length}`).join(' · ');
    return `<div class="callout">${esc(roster.note || '')}</div><p class="helper">${t('detection_sampled', 'сэмпл')} ${fmt(sample.sampled)} / count ${fmt(sample.count)} · ${t('detection_enriched', 'обогащено')} ${fmt(roster.enrichment?.enriched)} ${t('detection_accounts', 'аккаунтов')} · ${esc(date(sample.observed_at))}${roles ? ` · ${esc(roles)}` : ''}</p>${rows ? `<div class="table-wrap"><table><thead><tr><th>${t('chatter_col', 'Аккаунт')}</th><th>${t('age_days_col', 'Возраст, дней')}</th><th>${t('followers_col', 'Подписчиков')}</th><th>${t('created_col', 'Создан')}</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="subtitle">${t('detection_enrich_pending', 'Обогащение аккаунтов появится после следующего цикла poller.')}</p>`}`;
  }

  async function loadDetectionPage() {
    if (!state.overview) {
      try { state.overview = (await api('/api/profile/overview')).data; }
      catch (err) { if (err.status === 401) return renderLogin(t('session_expired', 'Сессия истекла. Введите ключ снова.')); return toast(err.message, 'bad'); }
    }
    const channels = state.overview.channels || [];
    if (!channels.length) { shell(emptyHtml()); return; }
    if (!state.detectionChannel || !channels.some((item) => item.login === state.detectionChannel)) state.detectionChannel = channels[0].login;
    shell(`<div class="loading">${t('loading_detection', 'Считаем детекцию накрутки')}</div>`);
    try {
      const [report, roster] = await Promise.all([
        api(`/api/profile/channels/${encodeURIComponent(state.detectionChannel)}/detection?hours=${state.detectionHours}`),
        api(`/api/profile/channels/${encodeURIComponent(state.detectionChannel)}/chatters`),
      ]);
      state.detection = report.data;
      state.detectionRoster = roster.data;
    } catch (err) {
      state.detection = null;
      state.detectionRoster = null;
      toast(err.message, 'bad');
    }
    renderDetectionPage();
  }

  function renderDetectionPage() {
    if (!state.overview) return loadDetectionPage();
    const channels = state.overview.channels || [];
    if (!channels.length) { shell(emptyHtml()); return; }
    const selected = state.detectionChannel || channels[0].login;
    const picker = channels.map((item) => `<button class="history-channel ${item.login === selected ? 'active' : ''}" data-detect-channel="${esc(item.login)}"><span class="channel-avatar">${esc(initials(item.login))}</span><span><strong>#${esc(item.login)}</strong><small class="${item.is_live ? 'status-live' : 'status-offline'}">${item.is_live ? t('live_status', 'в сети') : t('offline_status', 'офлайн')}</small></span></button>`).join('');
    const rangeButtons = [[24, t('hours_24', '24 часа')], [168, t('days_7', '7 дней')], [720, t('days_30', '30 дней')]].map(([hours, label]) => `<button class="${state.detectionHours === hours ? 'active' : ''}" data-detect-range="${hours}">${label}</button>`).join('');
    const head = `${pageHead('Detection lab', t('detection', 'Детекция накрутки'), t('detection_sub', 'Форма кривой, поведение чата и выборка аккаунтов. Индекс описывает необычность, а не вероятность ботов.'))}<div class="history-toolbar"><div class="history-picker" tabindex="0" aria-label="${esc(t('picker_hint', 'Каналы истории. Используйте Shift и колесо мыши'))}">${picker}</div><div class="history-range">${rangeButtons}</div></div>`;
    const report = state.detection;
    if (!report) {
      shell(`${head}<div class="callout">${t('detection_unavailable', 'Отчёт детекции недоступен. Проверьте данные канала и повторите позже.')}</div>`);
      bindDetectionControls();
      return;
    }
    const factors = report.factors || [];
    const series = report.series || {};
    const score = { ...report, samples_used: series.samples_used };
    const parts = report.confidence_parts || {};
    const meta = `${fmt(series.expanded_points)} ${t('detection_points', 'точек')} · ${fmt(series.live_points)} live · ${fmt(series.gap_points)} ${t('detection_gaps', 'пропусков')} · ${esc(date(series.from))} → ${esc(date(series.to))}`;
    const summary = `<section class="panel-card score-panel"><div class="panel-head"><div><h2>${t('detection_verdict', 'Вердикт')} ${verdictBadge(report.verdict)}</h2><small>${t('detection_series', 'Развёрнутый по минутам ряд')}: ${esc(meta)}</small></div></div>${scoreRing(score)}<div class="list"><div class="list-row"><strong>${t('detection_confidence_parts', 'Из чего сложилась уверенность')}</strong><span class="num">data ${fmt(parts.data_factor)} · samples ${fmt(parts.sample_factor)} · ${t('detection_availability', 'доступность')} ${pct(parts.available_ratio)}</span></div><div class="list-row"><strong>${t('detection_window', 'Окно')}</strong><span class="num">${fmt(report.window_hours)} ${t('detection_hours', 'часов')}</span></div></div></section>`;
    const factorPanel = `<section class="panel-card score-panel"><div class="panel-head"><div><h2>${t('detection_factors', 'Сработавшие признаки')}</h2><small>${factors.length ? `${factors.length} ${t('detection_signals', 'сигналов')}` : t('detection_quiet', 'Ни один признак не сработал.')}</small></div></div>${factors.length ? factors.map(detectionFactorHtml).join('') : `<div class="callout">${t('detection_quiet_detail', 'Это не гарантия честного онлайна: часть метрик зависит от выборки и объёма наблюдений.')}</div>`}</section>`;
    const { events, thinned } = collectChartEvents(report, report.points || []);
    const chartPanel = `<section class="panel-card"><div class="panel-head"><div><h2>${esc(selected)} — ${t('detection_chart_title', 'кривая онлайна по минутам')}</h2><small>${esc(windowCaption(state.detectionHours, report.points))}</small></div></div><div class="chart-wrap" id="channel-chart"></div><div class="legend"><span><i></i>${t('total_viewers_chart', 'Всего зрителей')}</span><span><i class="chat-legend"></i>${t('in_chat_approx', 'В чате (примерно)')}</span></div>${eventLegendHtml(events)}${thinned ? `<p class="helper">${t('events_thinned', 'Событий больше 25: показаны не все.')}</p>` : ''}<p class="helper chart-note">${t('detection_chart_note', 'Ряд развёрнут по минутам: значения держатся до следующего изменения, пропуски poller показаны разрывом.')}</p></section>`;
    const problems = `${(report.unavailable || []).length ? `<section class="panel-card"><div class="panel-head"><div><h2>${t('detection_unavailable_title', 'Недоступные метрики')}</h2><small>${t('detection_unavailable_sub', 'Отсутствие данных понижает уверенность, а не саму оценку.')}</small></div></div><div class="list">${(report.unavailable || []).map((item) => `<div class="list-row"><strong>${esc(metricLabel(item.metric))}</strong><small>${esc(unavailableDetail(item))}</small></div>`).join('')}</div></section>` : ''}<section class="panel-card"><div class="panel-head"><div><h2>${t('detection_warnings', 'Ограничения и предупреждения')}</h2></div></div><div class="callout">${warningList(report).map((item) => esc(item)).join('<br>')}</div></section>`;
    const evidence = `<section class="panel-card"><div class="panel-head"><div><h2>${t('detection_evidence', 'Доказательства: выборка чаттеров')}</h2><small>${t('detection_evidence_sub', 'До 100 логинов из CommunityTab, обогащённых users(logins:)')}</small></div></div>${chattersEvidenceHtml(state.detectionRoster)}</section>`;
    shell(`${head}<div class="detail-grid">${summary}${chatRatePanelHtml(report)}${factorPanel}${chartPanel}${adComparisonHtml(report.ad_vs_nonad)}${problems}${evidence}</div>`);
    bindDetectionControls();
    const chart = document.getElementById('channel-chart');
    if (chart) { chart.innerHTML = chartSvg(report.points || [], 60, events); bindChartTooltip(); }
  }

  function bindDetectionControls() {
    document.querySelectorAll('[data-detect-channel]').forEach((node) => node.addEventListener('click', () => { state.detectionChannel = node.dataset.detectChannel; state.detection = null; state.detectionRoster = null; loadDetectionPage(); }));
    document.querySelectorAll('[data-detect-range]').forEach((node) => node.addEventListener('click', () => { state.detectionHours = Number(node.dataset.detectRange); state.detection = null; loadDetectionPage(); }));
  }

  function modalShell(title, subtitle, body) { const backdrop = document.createElement('div'); backdrop.className = 'modal-backdrop'; backdrop.innerHTML = `<section class="modal" role="dialog" aria-modal="true"><div class="modal-head"><div><h2>${esc(title)}</h2><p class="subtitle">${esc(subtitle)}</p></div><button class="icon-btn" data-close aria-label="${esc(t('modal_close', 'Закрыть'))}">×</button></div>${body}</section>`; document.body.appendChild(backdrop); const close = () => backdrop.remove(); backdrop.querySelector('[data-close]').addEventListener('click', close); backdrop.addEventListener('click', (event) => { if (event.target === backdrop || event.target.closest('[data-close]')) close(); }); document.addEventListener('keydown', function onKey(event) { if (event.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } }); return { root: backdrop, close }; }

  function openAddModal() {
    const modal = modalShell(t('add_channels_modal', 'Добавить каналы'), t('add_channels_desc', 'Вставьте ссылки или логины Twitch. Они могут быть разделены пробелами и переводами строк.'), `<form id="add-form"><label class="form-label" for="channel-text">${t('streamer_links', 'Ссылки на стримеров')}</label><textarea class="textarea" id="channel-text" autofocus placeholder="https://twitch.tv/tumblurr\nhttps://twitch.tv/pesh"></textarea><p class="helper">${t('restricted_profile_note', 'Профиль с ограничением пропустит только разрешённые администратором каналы.')}</p><p class="form-error" id="add-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('add_and_start', 'Добавить и запустить')}</button></div></form>`);
    modal.root.querySelector('[data-close]').addEventListener('click', modal.close);
    modal.root.querySelector('#add-form').addEventListener('submit', async (event) => { event.preventDefault(); const button = event.submitter; button.disabled = true; button.textContent = t('adding', 'Добавляем…'); try { const result = await api('/api/profile/channels', { method: 'POST', body: JSON.stringify({ text: modal.root.querySelector('#channel-text').value }) }); const d = result.data; modal.close(); toast(tp('added_summary', { added: d.added.length, duplicates: d.duplicates.length, rejected: d.rejected.length ? tp('rejected_summary', { rejected: d.rejected.length }) : '' }), d.rejected.length ? 'bad' : 'good'); await loadOverview(); } catch (err) { modal.root.querySelector('#add-error').textContent = err.message; button.disabled = false; button.textContent = t('add_and_start_short', 'Добавить и запустить'); } });
  }

  async function removeChannel(login) { if (!window.confirm(`${t('remove_confirm_prefix', 'Убрать #')}${login}${t('remove_confirm_suffix', ' из портфеля?')}`)) return; try { await api(`/api/profile/channels/${encodeURIComponent(login)}`, { method: 'DELETE' }); if (state.selected === login) { state.selected = null; state.history = null; } toast(tp('channel_removed', { login })); await loadOverview(); } catch (err) { toast(err.message, 'bad'); } }

  async function loadApiPage() { app.innerHTML = `<div class="loading">${t('loading_api', 'Загружаем API-ключи')}</div>`; try { const result = await api('/api/profile/api-keys'); const keys = result.data || []; const content = `${pageHead('Developer surface', t('webhooks_and_api', 'Вебхуки и API'), t('api_sub', 'Создавайте машинные ключи из профиля. Они живут, пока действует TVS.'), `<button class="btn" data-action="new-webhook">＋ Webhook</button><button class="btn btn-primary" data-action="new-key">${t('new_api_key_btn', '＋ Новый API-ключ')}</button>`)}<div class="detail-grid"><section class="panel-card"><div class="panel-head"><div><h2>${t('your_keys', 'Ваши ключи')}</h2><small>Parent TVS: ${esc(state.user?.prefix || '')}</small></div><a class="btn btn-sm" href="/docs" target="_blank">OpenAPI /docs ↗</a></div>${keys.length ? `<div class="list">${keys.map(apiKeyRow).join('')}</div>` : `<div class="empty"><h2>${t('no_api_keys_yet', 'API-ключей пока нет')}</h2><p>${t('create_readonly_key', 'Создайте read-only ключ для интеграции.')}</p></div>`}</section><section class="panel-card"><div class="panel-head"><div><h2>${t('how_to_use', 'Как использовать')}</h2><small>${t('same_access', 'Один и тот же доступ, другой интерфейс')}</small></div></div><div class="callout">${t('api_inheritance', 'Ключ <span class="inline-code">tvs_…</span> наследует список стримеров и историю родительского профиля. Передавайте его только в заголовке <span class="inline-code">Authorization: Bearer</span>.')}</div><p class="helper">${t('api_expiry', 'Срок API-ключа ограничен сроком TVS. Отзыв родителя автоматически отключает все дочерние ключи.')}</p><pre class="inline-code" style="display:block;padding:12px;white-space:pre-wrap;line-height:1.7">${t('api_example', 'GET /api/v1/channels/tumblurr/snapshot\nAuthorization: Bearer tvs_…')}</pre></section></div>`; shell(content); document.querySelector('[data-action="new-key"]')?.addEventListener('click', openApiKeyModal); document.querySelector('[data-action="new-webhook"]')?.addEventListener('click', openWebhookModal); document.querySelectorAll('[data-revoke-key]').forEach((node) => node.addEventListener('click', () => revokeApiKey(node.dataset.revokeKey))); document.querySelectorAll('[data-reveal-key]').forEach((node) => node.addEventListener('click', () => revealApiKey(node.dataset.revealKey))); } catch (err) { toast(err.message, 'bad'); } }
  function apiKeyRow(row) { return `<div class="list-row"><div><strong>${esc(row.label)}</strong><small>${esc(row.prefix)}… · ${row.requests_used} ${t('requests_used', 'запросов')} · ${t('created_label', 'создан')} ${esc(date(row.created_at))}</small></div><span class="badge badge-good">${row.status === 'active' ? t('status_active', 'активен') : esc(row.status)}</span><div class="toolbar-right"><button class="btn btn-sm" data-reveal-key="${esc(row.id)}">${t('reveal', 'Показать')}</button><button class="btn btn-sm btn-danger" data-revoke-key="${esc(row.id)}">${t('revoke', 'Отозвать')}</button></div></div>`; }
  function openApiKeyModal() { const modal = modalShell(t('new_api_key_title', 'Новый API-ключ'), t('new_api_key_desc', 'Он получит доступ только к данным текущего профиля.'), `<form id="key-form"><label class="form-label" for="key-label">${t('key_name_label', 'Название')}</label><input class="input" id="key-label" value="${t('key_name_default', 'Интеграция')}" required><p class="helper">${t('key_created_once', 'Ключ показывается один раз после создания. Сохраните его в менеджере секретов.')}</p><p class="form-error" id="key-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('create_btn', 'Создать ключ')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#key-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const result = await api('/api/profile/api-keys', { method: 'POST', body: JSON.stringify({ label: modal.root.querySelector('#key-label').value }) }); modal.root.querySelector('#key-form').innerHTML = `<h3>${t('created_heading', 'Ключ создан')}</h3><div class="secret-box"><code id="new-secret">${esc(result.data.key)}</code><button class="btn btn-sm" data-copy>${t('copy_btn', 'Копировать')}</button></div><p class="helper">${t('secret_hidden', 'Это значение больше не показывается в списке.')}</p><div class="modal-actions"><button class="btn btn-primary" data-close>${t('done_btn', 'Готово')}</button></div>`; modal.root.querySelector('[data-copy]').addEventListener('click', () => copyText(result.data.key)); modal.root.querySelectorAll('[data-close]').forEach((node) => node.addEventListener('click', () => { modal.close(); loadApiPage(); })); } catch (err) { modal.root.querySelector('#key-error').textContent = err.message; } }); }
  async function revokeApiKey(id) { if (!window.confirm(t('revoke_confirm', 'Отозвать этот API-ключ?'))) return; try { await api(`/api/profile/api-keys/${encodeURIComponent(id)}/revoke`, { method: 'POST' }); toast(t('api_key_revoked', 'API-ключ отозван')); loadApiPage(); } catch (err) { toast(err.message, 'bad'); } }

  async function loadAlertsPage() {
    shell(`${pageHead('Signal delivery', t('alerts', 'Алерты'), t('alerts_sub', 'Понятные правила и события наблюдения.')) }<div class="loading">${t('loading_alerts', 'Загружаем правила')}</div>`);
    try {
      const result = await api('/api/profile/alerts');
      const rules = result.data?.rules || [];
      const events = result.data?.events || [];
      const guide = `<section class="panel-card alert-guide"><div class="panel-head"><div><h2>${t('guide_title', 'Как работают алерты')}</h2><small>${t('guide_sub', 'Это сигналы для проверки, а не автоматический бан')}</small></div><span class="badge badge-neutral">${t('lang_badge', 'Русский')}</span></div><div class="alert-guide-grid"><div><strong>${t('guide_spike', 'Всплеск зрителей')}</strong><p>${t('guide_spike_desc', 'Сравниваем новый пик с предыдущим наблюдением.')}</p></div><div><strong>${t('guide_ratio', 'Падение доли чата')}</strong><p>${t('guide_ratio_desc', 'Смотрим, не остались ли зрители без людей в чате.')}</p></div><div><strong>${t('guide_stale', 'Нет данных')}</strong><p>${t('guide_stale_desc', 'Предупреждаем, если poller не обновлял канал.')}</p></div><div><strong>${t('guide_offline', 'Офлайн')}</strong><p>${t('guide_offline_desc', 'Фиксируем переход канала из эфира в офлайн.')}</p></div></div><p class="helper">${t('guide_footer', 'Cooldown не позволяет одному и тому же правилу создавать много одинаковых событий. Красный знак у канала означает высокий индекс; наведите курсор или нажмите знак, чтобы увидеть причины.')}</p></section>`;
      const content = `${pageHead('Signal delivery', t('alerts', 'Алерты'), t('alerts_sub', 'Понятные правила и события наблюдения.'), `<button class="btn btn-primary" data-action="new-rule">${t('new_rule', '＋ Новое правило')}</button>`)}${guide}<div class="detail-grid"><section class="panel-card"><div class="panel-head"><div><h2>${t('portfolio_rules', 'Правила')}</h2><small>${rules.length} ${t('rules_count', 'активно')}</small></div></div>${rules.length ? `<div class="list">${rules.map(ruleRow).join('')}</div>` : `<div class="empty"><h2>${t('no_events_yet', 'Пока нет правил')}</h2><p>${t('create_api_key_desc', 'Добавьте порог всплеска или отсутствия данных, чтобы получать события.')}</p></div>`}</section><section class="panel-card"><div class="panel-head"><div><h2>${t('event_feed', 'Последние события')}</h2><small>${events.length} ${t('events', 'событий')}</small></div></div>${events.length ? `<div class="list">${events.map(eventRow).join('')}</div>` : `<p class="subtitle">${t('obs_after_poller', 'События появятся после следующего цикла poller.')}</p>`}</section></div>`;
      shell(content);
      document.querySelector('[data-action="new-rule"]')?.addEventListener('click', openRuleModal);
    } catch (err) { toast(err.message, 'bad'); }
  }
  function ruleRow(row) { return `<div class="list-row"><div><strong>${esc(alertLabels[row.type] || row.type)}</strong><small>${row.channels?.length ? esc(row.channels.join(', ')) : t('all_channels', 'Все каналы')} · ${row.cooldown_seconds} ${t('sec_ago', 'сек')}</small></div><span class="badge ${row.enabled ? 'badge-good' : 'badge-neutral'}">${row.enabled ? t('rule_enabled', 'включено') : t('rule_disabled', 'выключено')}</span></div>`; }
  function eventRow(row) { return `<div class="list-row"><div><strong>${esc(alertLabels[row.type] || row.type)} ${row.channel_login ? `#${esc(row.channel_login)}` : ''}</strong><small>${esc(date(row.created_at))}</small></div><span class="badge ${row.severity === 'high' ? 'badge-bad' : 'badge-warn'}">${esc(severityLabels[row.severity] || row.severity)}</span></div>`; }
  function openRuleModal() { const modal = modalShell(t('new_rule_title', 'Новое правило'), t('new_rule_desc', 'Событие будет сохранено в ленте алертов профиля.'), `<form id="rule-form"><label class="form-label" for="rule-type">${t('rule_type_label', 'Тип')}</label><select class="select input" id="rule-type"><option value="viewer_spike">${t('rule_type_spike', 'Всплеск зрителей')}</option><option value="ratio_collapse">${t('rule_type_ratio', 'Падение доли чата')}</option><option value="stale_data">${t('rule_type_stale', 'Нет свежих данных')}</option><option value="stream_offline">${t('rule_type_offline', 'Канал ушёл офлайн')}</option></select><label class="form-label" for="rule-threshold" style="margin-top:12px">${t('threshold_label', 'Порог')}</label><input class="input" id="rule-threshold" type="number" value="2" step="0.1"><p class="helper">${t('threshold_hint', 'Для «Всплеск зрителей» укажите, во сколько раз выросло значение. Для «Падение доли чата» — минимальный порог доли.')}</p><p class="form-error" id="rule-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('create_btn', 'Создать')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#rule-form').addEventListener('submit', async (event) => { event.preventDefault(); try { await api('/api/profile/alerts', { method: 'POST', body: JSON.stringify({ type: modal.root.querySelector('#rule-type').value, threshold: Number(modal.root.querySelector('#rule-threshold').value) }) }); modal.close(); toast(t('rule_created', 'Правило создано')); loadAlertsPage(); } catch (err) { modal.root.querySelector('#rule-error').textContent = err.message; } }); }

  function renderSettings() { const profile = state.user?.profile || {}; const content = `${pageHead('Account surface', t('settings', 'Настройки'), t('settings_sub', 'Профиль, доступ и документация.'))}<div class="detail-grid"><section class="panel-card"><div class="panel-head"><div><h2>${t('profile', 'Профиль')}</h2><small>${t('profile_tvs_details', 'Данные текущего TVS-ключа')}</small></div></div><div class="list"><div class="list-row"><div><strong>${t('label', 'Название')}</strong><small>${esc(profile.label || '—')}</small></div></div><div class="list-row"><div><strong>${t('channel_mode', 'Режим каналов')}</strong><small>${profile.unlimited ? t('unlimited', 'Без ограничений') : `Allowlist: ${(profile.allowed_channels || []).length}`}</small></div><span class="badge ${profile.unlimited ? 'badge-good' : 'badge-neutral'}">${profile.unlimited ? 'unlimited' : 'restricted'}</span></div><div class="list-row"><div><strong>${t('expiry_date', 'Срок действия')}</strong><small>${esc(date(state.user?.expires_at))}</small></div></div></div></section><section class="panel-card"><div class="panel-head"><div><h2>${t('docs', 'Документация')}</h2><small>${t('for_devs', 'Для разработчиков')}</small></div></div><p class="subtitle">${t('docs_desc', 'Полный OpenAPI доступен на сервере. Там есть схемы, ошибки, лимиты и примеры curl/Python/JavaScript.')}</p><a class="btn btn-primary" href="/docs" target="_blank">${t('open_api_docs', 'Открыть /docs ↗')}</a></section></div>`; shell(content); }

  async function loadAdmin() { shell(`${pageHead('Operations', t('admin', 'Админ-панель'), t('admin_sub', 'Токены, политики, аудит и нагрузка сервера.')) }<div class="loading">${t('loading_admin', 'Загружаем операции')}</div>`); try { const [overview, tokens, profiles, audit, load] = await Promise.all(['/api/admin/overview', `/api/admin/tokens?include_revoked=${state.showRevoked}`, '/api/admin/profiles', '/api/admin/audit?limit=30', '/api/admin/load'].map((path) => api(path))); state.adminData = { overview: overview.data, tokens: tokens.data, profiles: profiles.data, audit: audit.data, load: load.data }; renderAdmin(); } catch (err) { if (err.status === 401) return renderLogin(t('session_expired', 'Админская сессия истекла.')); toast(err.message, 'bad'); } }
  function renderAdmin() { const data = state.adminData; if (!data) return loadAdmin(); const load = data.load || {}; const appMetrics = load.application || {}; const poller = load.poller || {}; const content = `${pageHead('Operations', t('admin', 'Админ-панель'), t('admin_sub', 'Токены, политики, аудит и нагрузка сервера.'), `<button class="btn btn-primary" data-action="new-token">${t('create_key', '＋ Создать ключ')}</button>`)}<div class="admin-grid">${kpi(t('admin_tvs_keys', 'Ключи TVS'), fmt(data.overview.tokens), `${data.overview.profiles} ${t('profiles_count', 'профилей')}`)}${kpi(t('active_channels', 'Активные каналы'), fmt(data.overview.active_channels), 'poller queue')}${kpi(t('api_requests', 'API запросы'), fmt(appMetrics.api_requests), `p95 ${fmt(appMetrics.p95_ms)} ms`)}${kpi(t('poller_status', 'Статус poller'), fmt(poller.errors), `${t('last_cycle', 'последний цикл')} ${poller.last_run_at ? date(poller.last_run_at) : '—'}`, (poller.errors || 0) > 0 ? 'bad' : 'good')}</div><div class="tabs"><button data-admin-tab="tokens" class="${state.adminTab === 'tokens' ? 'active' : ''}">${t('tokens', 'Токены')}</button><button data-admin-tab="profiles" class="${state.adminTab === 'profiles' ? 'active' : ''}">${t('policies', 'Политики')}</button><button data-admin-tab="audit" class="${state.adminTab === 'audit' ? 'active' : ''}">${t('audit', 'Аудит')}</button><button data-admin-tab="load" class="${state.adminTab === 'load' ? 'active' : ''}">${t('load', 'Нагрузка')}</button></div><div id="admin-panel">${adminTabsEnhanced(data)}</div>`; shell(content); document.querySelector('[data-action="new-token"]')?.addEventListener('click', openTokenModal); document.querySelectorAll('[data-admin-tab]').forEach((node) => node.addEventListener('click', () => { state.adminTab = node.dataset.adminTab; renderAdmin(); })); document.querySelectorAll('[data-reveal-token]').forEach((node) => node.addEventListener('click', () => revealToken(node.dataset.revealToken))); document.querySelectorAll('[data-revoke-token]').forEach((node) => node.addEventListener('click', () => patchToken(node.dataset.revokeToken, { revoked: true }))); document.querySelectorAll('[data-edit-token]').forEach((node) => node.addEventListener('click', () => openTokenEditModal(node.dataset.editToken))); document.querySelectorAll('[data-rotate-token]').forEach((node) => node.addEventListener('click', () => openRotateModal(node.dataset.rotateToken))); document.querySelectorAll('[data-policy-profile]').forEach((node) => node.addEventListener('click', () => openPolicyModal(Number(node.dataset.policyProfile)))); document.querySelector('[data-toggle-revoked]')?.addEventListener('click', () => { state.showRevoked = !state.showRevoked; loadAdmin(); }); }

  function adminBarChart(entries, color) {
    const rows = (entries || []).filter(([, value]) => Number(value) > 0);
    if (!rows.length) return `<div class="admin-bar-empty">${t('no_chart_data', 'Нет данных для графика')}</div>`;
    const max = Math.max(...rows.map(([, value]) => Number(value)));
    const limit = 12;
    const shown = rows.slice(0, limit);
    return `<div class="admin-bar-chart">${shown.map(([label, value]) => {
      const pctWidth = Math.max(2, Math.round((Number(value) / max) * 100));
      return `<div class="admin-bar-row" title="${esc(label)}: ${esc(fmt(value))}"><span class="admin-bar-label">${esc(label)}</span><span class="admin-bar-track"><i style="width:${pctWidth}%;background:${esc(color)}"></i></span><span class="admin-bar-value">${esc(fmt(value))}</span></div>`;
    }).join('')}${rows.length > limit ? `<p class="helper">${t('chart_top_n', 'Показаны первые')} ${limit} ${t('chart_of_total', 'из')} ${rows.length}</p>` : ''}</div>`;
  }

  function adminCharts(load) { const app = load.application || {}; const statuses = Object.entries(app.statuses || {}); const routes = Object.entries(app.routes || {}); const poller = load.poller || {}; return `<div class="admin-mini-chart admin-load-summary"><div><strong>${fmt(load.active_sessions || 0)}</strong><span>${t('admin_sessions', 'активных сессий')}</span></div><div><strong>${fmt(load.active_profiles || 0)}</strong><span>${t('admin_profiles', 'активных профилей')}</span></div><div><strong>${fmt(load.active_channels || 0)}</strong><span>${t('admin_channels', 'активных каналов')}</span></div><div><strong>${fmt(load.api_keys || 0)}</strong><span>${t('admin_api_keys', 'API-ключей')}</span></div></div><div class="admin-charts-grid"><section class="panel-card admin-chart-card"><div class="panel-head"><div><h2>${t('statuses_title', 'Статусы ответов')}</h2><small>${t('statuses_sub', 'Распределение HTTP-кодов текущего процесса')}</small></div></div>${adminBarChart(statuses, '#59cfe8')}</section><section class="panel-card admin-chart-card"><div class="panel-head"><div><h2>${t('routes_title', 'Топ маршрутов')}</h2><small>${t('routes_sub', 'Количество запросов по endpoint')}</small></div></div>${adminBarChart(routes, '#a875ff')}</section><section class="panel-card admin-chart-card"><div class="panel-head"><div><h2>${t('poller_title', 'Poller и задержка')}</h2><small>${t('poller_sub', 'Состояние фонового сбора')}</small></div></div><div class="admin-mini-chart"><div><strong>${fmt(poller.polls || 0)}</strong><span>${t('polls_count', 'опросов')}</span></div><div><strong>${fmt(poller.errors || 0)}</strong><span>${t('errors_count', 'ошибок')}</span></div><div><strong>${fmt(app.p95_ms || 0)} ms</strong><span>${t('p95_latency', 'p95 latency')}</span></div></div><div class="admin-progress"><i style="width:${Math.min(100, Math.max(3, (Number(poller.polls || 0) / Math.max(Number(poller.polls || 0) + Number(poller.errors || 0), 1)) * 100))}%"></i></div><p class="helper">${t('poller_success_hint', 'Зелёная доля — успешные циклы; красная — ошибки poller.')}</p></section></div>`; }

  function adminTabsEnhanced(data) { if (state.adminTab !== 'load') return adminTabs(data); return adminCharts(data.load || {}); }

  function adminTabs(data) { if (state.adminTab === 'tokens') return `<section class="table-card"><div class="toolbar"><div class="toolbar-left"><h2>${t('tokens_tab', 'Токены')}</h2></div><div class="toolbar-right"><button class="btn btn-sm" data-toggle-revoked>${state.showRevoked ? t('hide_revoked', 'Скрыть отозванные') : t('show_revoked', 'Показать отозванные')}</button></div></div><div class="table-wrap"><table><thead><tr><th>${t('key_col', 'Ключ')}</th><th>${t('type_col', 'Тип')}</th><th>${t('profile_col', 'Профиль')}</th><th>${t('mode_col', 'Режим')}</th><th>${t('expiry_col', 'Срок')}</th><th>${t('status_col', 'Статус')}</th><th>${t('actions_col', 'Действия')}</th></tr></thead><tbody>${(data.tokens || []).map(adminTokenRow).join('')}</tbody></table></div></section>`; if (state.adminTab === 'profiles') return `<section class="table-card"><div class="table-wrap"><table><thead><tr><th>${t('profile_name_col', 'Профиль')}</th><th>${t('channels_col', 'Каналы')}</th><th>${t('mode_col_short', 'Режим')}</th><th>${t('last_activity_col', 'Последняя активность')}</th></tr></thead><tbody>${(data.profiles || []).map(profileRow).join('')}</tbody></table></div></section>`; if (state.adminTab === 'audit') return `<section class="table-card"><div class="table-wrap"><table><thead><tr><th>${t('time_col', 'Время')}</th><th>${t('actor_col', 'Actor')}</th><th>${t('action_col', 'Действие')}</th><th>${t('object_col', 'Объект')}</th><th>${t('request_col', 'Request')}</th></tr></thead><tbody>${(data.audit || []).map(row => `<tr><td>${esc(date(row.created_at))}</td><td class="num">${esc(row.actor)}</td><td>${esc(row.action)}</td><td class="num">${esc(row.object_id || '—')}</td><td class="num">${esc(row.request_id || '—')}</td></tr>`).join('')}</tbody></table></div></section>`; const l = data.load || {}, a = l.application || {}; return `<div class="detail-grid"><section class="panel-card"><div class="panel-head"><div><h2>${t('load_title', 'Нагрузка приложения')}</h2><small>${t('load_sub', 'Последние')} ${fmt(a.requests)} ${t('requests_used', 'запросов')}</small></div></div><div class="list">${[[t('active_sessions_label', 'Активные сессии'), l.active_sessions],[t('active_profiles_label', 'Активные профили'), l.active_profiles],[t('active_channels_label', 'Активные каналы'), l.active_channels],[t('api_keys_label', 'API ключи'), l.api_keys],[t('p50_latency', 'p50 latency'), `${a.p50_ms} ms`],[t('p95_latency', 'p95 latency'), `${a.p95_ms} ms`],[t('error_rate', 'Error rate'), a.error_rate]].map(([label, value]) => `<div class="list-row"><strong>${esc(label)}</strong><span class="num">${esc(fmt(value))}</span></div>`).join('')}</div></section><section class="panel-card"><div class="panel-head"><div><h2>Poller</h2><small>${l.database?.dialect || 'database'}</small></div></div><div class="list">${Object.entries(l.poller || {}).map(([key, value]) => `<div class="list-row"><strong>${esc(key)}</strong><span class="num">${esc(fmt(value))}</span></div>`).join('') || `<p class="subtitle">${t('poller_off', 'Poller выключен.')}</p>`}</div></section></div>`; }
  function adminTokenRow(row) { return `<tr><td><strong>${esc(row.label)}</strong><small class="channel-sub">${esc(row.prefix)}…</small></td><td>${esc(row.kind)}</td><td>${esc(row.profile_label || '—')}</td><td>${row.unlimited ? `<span class="badge badge-good">${t('mode_unlimited', 'unlimited')}</span>` : `${t('mode_allowlist', 'allowlist')} ${(row.allowed_channels || []).length}`}</td><td>${esc(date(row.expires_at))}</td><td><span class="badge ${row.status === 'active' ? 'badge-good' : 'badge-bad'}">${esc(row.status)}</span></td><td><div class="toolbar-right"><button class="btn btn-sm" data-edit-token="${esc(row.id)}">${t('change', 'Изменить')}</button><button class="btn btn-sm" data-reveal-token="${esc(row.id)}">${t('show', 'Показать')}</button><button class="btn btn-sm" data-rotate-token="${esc(row.id)}">${t('rotate', 'Перевыпустить')}</button><button class="btn btn-sm btn-danger" data-revoke-token="${esc(row.id)}">${t('revoke', 'Отозвать')}</button></div></td></tr>`; }
  function profileRow(row) { return `<tr><td><strong>${esc(row.label)}</strong><small class="channel-sub">#${row.id}</small></td><td class="num">${row.channels.length}</td><td>${row.unlimited ? `<span class="badge badge-good">${t('mode_unlimited', 'unlimited')}</span>` : `<span class="badge badge-neutral">${t('mode_allowlist', 'allowlist')}</span>`}</td><td>${esc(age(row.last_seen_at))}</td><td><button class="btn btn-sm" data-policy-profile="${row.id}">${t('change', 'Изменить')}</button></td></tr>`; }
  function openPolicyModal(profileId) { const profile = (state.adminData?.profiles || []).find((item) => item.id === profileId); if (!profile) return; const modal = modalShell(t('policy_title', 'Политика профиля'), `#${profile.id} · ${profile.label}`, `<form id="policy-form"><label class="form-label" style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="policy-unlimited" ${profile.unlimited ? 'checked' : ''}> ${t('policy_unlimited', 'Разрешить любые публичные Twitch-каналы')}</label><label class="form-label" for="policy-channels" style="display:block;margin-top:14px">${t('allowlist_label', 'Allowlist каналов')}</label><textarea class="textarea" id="policy-channels" placeholder="${t('allowlist_placeholder', 'tumblurr pesh')}">${esc((profile.allowed_channels || []).join('\n'))}</textarea><p class="helper">${t('allowlist_hint', 'При включённом unlimited список можно оставить пустым.')}</p><p class="form-error" id="policy-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('save_policy_btn', 'Сохранить политику')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#policy-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const raw = modal.root.querySelector('#policy-channels').value; const channels = raw.split(/\\s+/).map((item) => item.trim()).filter(Boolean); await api(`/api/admin/profiles/${profileId}/policy`, { method: 'PATCH', body: JSON.stringify({ unlimited: modal.root.querySelector('#policy-unlimited').checked, allowed_channels: channels }) }); modal.close(); toast(t('policy_updated', 'Политика профиля обновлена')); loadAdmin(); } catch (err) { modal.root.querySelector('#policy-error').textContent = err.message; } }); }
  function openTokenEditModal(tokenId) { const row = (state.adminData?.tokens || []).find((item) => item.id === tokenId); if (!row) return; const modal = modalShell(t('edit_key_title', 'Изменить ключ'), `${row.label} · ${row.prefix}…`, `<form id="token-edit-form"><label class="form-label" for="edit-label">${t('edit_label', 'Название')}</label><input class="input" id="edit-label" value="${esc(row.label)}"><label class="form-label" for="edit-expiry" style="display:block;margin-top:12px">${t('edit_expiry', 'Новый срок (пусто = бессрочный)')}</label><input class="input" id="edit-expiry" type="datetime-local"><p class="form-error" id="token-edit-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('save_btn', 'Сохранить')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#token-edit-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const value = modal.root.querySelector('#edit-expiry').value; await api(`/api/admin/tokens/${tokenId}`, { method: 'PATCH', body: JSON.stringify({ label: modal.root.querySelector('#edit-label').value, expires_at: value ? new Date(value).toISOString() : null }) }); modal.close(); toast(t('key_updated', 'Срок и название обновлены')); loadAdmin(); } catch (err) { modal.root.querySelector('#token-edit-error').textContent = err.message; } }); }
  function openTokenModal() { const modal = modalShell(t('create_token_title', 'Создать TVS-ключ'), t('create_token_desc', 'Ключ можно открыть в портфеле или выдать администратору.'), `<form id="token-form"><label class="form-label" for="token-kind">${t('token_kind_label', 'Тип ключа')}</label><select class="select input" id="token-kind"><option value="profile">${t('token_kind_profile', 'Профиль')}</option><option value="admin">${t('token_kind_admin', 'Администратор')}</option></select><label class="form-label" for="token-label" style="margin-top:12px">${t('token_label', 'Название')}</label><input class="input" id="token-label" value="${t('token_label_default', 'Новый профиль')}" required><label class="form-label" for="token-expiry" style="margin-top:12px">${t('token_expiry', 'Срок (пусто = бессрочный)')}</label><input class="input" id="token-expiry" type="datetime-local"><label class="form-label" style="display:flex;align-items:center;gap:8px;margin-top:12px"><input type="checkbox" id="token-unlimited"> ${t('token_unlimited', 'Без ограничений по каналам')}</label><p class="form-error" id="token-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('create_btn', 'Создать')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#token-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const kind = modal.root.querySelector('#token-kind').value; const expiry = modal.root.querySelector('#token-expiry').value; const result = await api('/api/admin/tokens', { method: 'POST', body: JSON.stringify({ kind, label: modal.root.querySelector('#token-label').value, expires_at: expiry ? new Date(expiry).toISOString() : null, unlimited: modal.root.querySelector('#token-unlimited').checked, allowed_channels: [] }) }); modal.root.querySelector('#token-form').innerHTML = `<h3>${t('created_heading', 'Ключ создан')}</h3><div class="secret-box"><code>${esc(result.data.key)}</code><button class="btn btn-sm" data-copy>${t('copy_btn', 'Копировать')}</button></div><p class="helper">${t('token_created_note', 'Секрет можно снова показать в таблице токенов; действие попадёт в аудит.')}</p><div class="modal-actions"><button class="btn btn-primary" data-close>${t('done_btn', 'Готово')}</button></div>`; modal.root.querySelector('[data-copy]').addEventListener('click', () => copyText(result.data.key)); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); loadAdmin(); } catch (err) { modal.root.querySelector('#token-error').textContent = err.message; } }); }
  async function revealApiKey(id) { try { const result = await api(`/api/profile/api-keys/${encodeURIComponent(id)}/reveal`, { method: 'POST' }); const modal = modalShell(t('reveal_api_title', 'Показать API-ключ'), t('audit_event', 'Событие записано в аудит.'), `<div class="secret-box"><code>${esc(result.data.key)}</code><button class="btn btn-sm" data-copy>${t('copy_btn', 'Копировать')}</button></div><p class="helper">${t('secret_security', 'Не отправляйте секрет в URL или сторонний чат.')}</p><div class="modal-actions"><button class="btn btn-primary" data-close>${t('done_btn', 'Готово')}</button></div>`); modal.root.querySelector('[data-copy]').addEventListener('click', () => copyText(result.data.key)); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); } catch (err) { toast(err.message, 'bad'); } }
  async function revealToken(id) { try { const result = await api(`/api/admin/tokens/${encodeURIComponent(id)}/reveal`, { method: 'POST' }); const modal = modalShell(t('reveal_token_title', 'Показать секрет'), t('audit_event', 'Событие записано в аудит.'), `<div class="secret-box"><code>${esc(result.data.key)}</code><button class="btn btn-sm" data-copy>${t('copy_btn', 'Копировать')}</button></div><p class="helper">${t('secret_security', 'Не отправляйте секрет в URL, Referer или сторонний чат.')}</p><div class="modal-actions"><button class="btn btn-primary" data-close>${t('done_btn', 'Готово')}</button></div>`); modal.root.querySelector('[data-copy]').addEventListener('click', () => copyText(result.data.key)); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); } catch (err) { if (err.payload?.error?.code === 'secret_rotation_required') return openRotateModal(id); toast(err.message, 'bad'); } }

  function openRotateModal(id) { const row = (state.adminData?.tokens || []).find((item) => item.id === id); const label = row?.label || t('rotated_label', 'этот ключ'); const modal = modalShell(t('rotate_title', 'Перевыпустить ключ'), `${label} · ${t('rotate_note', 'старый секрет нельзя восстановить')}`, `<div class="callout">${t('rotate_warning', 'Старый ключ будет отозван, а вместо него будет создан новый TVS-ключ с тем же профилем и настройками. Дочерние API-ключи старого TVS также перестанут работать.')}</div><p class="form-error" id="rotate-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" data-rotate>${t('rotate_btn', 'Перевыпустить')}</button></div>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('[data-rotate]').addEventListener('click', async (event) => { event.target.disabled = true; try { const result = await api(`/api/admin/tokens/${encodeURIComponent(id)}/rotate`, { method: 'POST' }); modal.root.innerHTML = `<div class="secret-box"><code>${esc(result.data.key)}</code><button class="btn btn-sm" data-copy>${t('copy_btn', 'Копировать')}</button></div><p class="helper">${t('rotate_done', 'Новый ключ показывается один раз. Старый ключ уже отозван.')}</p><div class="modal-actions"><button class="btn btn-primary" data-close>${t('done_btn', 'Готово')}</button></div>`; modal.root.querySelector('[data-copy]').addEventListener('click', () => copyText(result.data.key)); modal.root.querySelector('[data-close]').addEventListener('click', () => { modal.close(); loadAdmin(); }); } catch (error) { modal.root.querySelector('#rotate-error').textContent = error.message; event.target.disabled = false; } }); }
  async function patchToken(id, payload) { try { await api(`/api/admin/tokens/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(payload) }); toast(t('key_updated', 'Ключ обновлён')); loadAdmin(); } catch (err) { toast(err.message, 'bad'); } }

  function openWebhookModal() { const modal = modalShell(t('webhook_title', 'Добавить webhook'), t('webhook_desc', 'События будут подписываться HMAC и отправляться на HTTPS endpoint.'), `<form id="webhook-form"><label class="form-label" for="webhook-url">${t('webhook_url_label', 'HTTPS URL')}</label><input class="input" id="webhook-url" type="url" placeholder="${t('webhook_url_placeholder', 'https://example.com/tvs-hook')}" required><label class="form-label" for="webhook-secret" style="margin-top:12px">${t('webhook_secret_label', 'Подпись secret (минимум 16 символов)')}</label><input class="input" id="webhook-secret" type="password" minlength="16" required><p class="helper">${t('webhook_hint', 'Приватные IP, localhost и не-HTTPS адреса запрещены.')}</p><p class="form-error" id="webhook-error"></p><div class="modal-actions"><button class="btn" type="button" data-close>${t('cancel_btn', 'Отмена')}</button><button class="btn btn-primary" type="submit">${t('add_btn', 'Добавить')}</button></div></form>`); modal.root.querySelector('[data-close]').addEventListener('click', modal.close); modal.root.querySelector('#webhook-form').addEventListener('submit', async (event) => { event.preventDefault(); try { const result = await api('/api/profile/webhooks', { method: 'POST', body: JSON.stringify({ url: modal.root.querySelector('#webhook-url').value, secret: modal.root.querySelector('#webhook-secret').value, events: ['anomaly.detected'] }) }); modal.close(); toast(`${t('webhook_added', 'Webhook добавлен')}: ${result.data.url}`); } catch (err) { modal.root.querySelector('#webhook-error').textContent = err.message; } }); }
  async function logout() { try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {} clearInterval(state.refreshTimer); state.user = null; state.overview = null; renderLogin(); }
  async function copyText(text) { try { await navigator.clipboard.writeText(text); toast(t('copied', 'Скопировано')); } catch (_) { toast(t('copy_manual', 'Скопируйте текст вручную'), 'bad'); } }

  async function boot() { try { const result = await api('/api/auth/me'); if (!result.user) return renderLogin(); try { state.config = (await api('/api/config')).data; } catch (_) { state.config = null; } state.user = result.user; state.view = state.user.is_admin ? 'admin' : viewFromLocation(); renderApp(); if (state.user.is_admin) await loadAdmin(); else await loadOverview(); clearInterval(state.refreshTimer); state.refreshTimer = setInterval(() => { if (state.user && state.view === 'portfolio') loadOverview(); if (state.user && state.view === 'history') loadHistoryPage(); if (state.user?.is_admin && state.view === 'admin') loadAdmin(); }, 30000); } catch (err) { if (err.status === 401) renderLogin(); else setAppError(err.message); } }
  boot();
})();
