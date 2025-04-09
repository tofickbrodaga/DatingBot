# DatingBot

## Планирование и проектирование
### Схема взаимодействия сервисов
![description](https://github.com/user-attachments/assets/a1a2049d-cc34-40c2-a76d-0a680314e7a0)

### Описание сервисов

#### User Bot Service
— Интеграция с Telegram Bot API

— Обрабатывает команды (/start, свайпы, анкеты, мэтчи и т.п.)

— Отправляет и получает данные от Backend API

#### Backend API Service
— REST API

— Обработка логики регистрации, анкет, мэтчинга, лайков

— Генерация рейтингов и выбор анкет
#### Profile Ranking Service
— Логика расчёта рейтингов (1, 2, 3 уровень)

— Периодический пересчет через Celery

— Кэширует результаты в Redis
#### Database (PostgreSQL)
— Хранит пользователей, анкеты, мэтчи, лайки, рейтинги
#### Redis
— Кэш популярных анкет

— Быстрый доступ для бота
#### Celery + Broker 
— Асинхронные задачи: расчет рейтинга, обновление кеша, рассылки
#### Object Storage (MinIO)
— Хранение фотографий профиля

### ER-diagram
![tg_image_1266537980](https://github.com/user-attachments/assets/ca9e37cd-446e-4f9c-9f10-8d0d2fe798dc)

