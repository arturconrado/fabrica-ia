from datetime import date, datetime
from typing import Any

from sqlalchemy.inspection import inspect


def _clean(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def model_to_dict(model: Any) -> dict:
    return {column.key: _clean(getattr(model, column.key)) for column in inspect(model).mapper.column_attrs}


def models_to_dict(models: list) -> list:
    return [model_to_dict(model) for model in models]
