"""Базовий клас ORM-моделей. Таблиці (quotes_1s, spread_events, ...) — Фаза 2."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
