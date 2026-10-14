"""Настройки приложения.

Несекретные параметры имеют значения по умолчанию. Секреты (ключ подписи, пароли, строка
подключения к БД) значений по умолчанию не имеют и читаются только из окружения или файла .env,
который не хранится в репозитории (шаблон — .env.example).
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Склад"
    token_ttl_minutes: int = 480
    cookie_secure: bool = False

    # Провайдер электронной подписи для менеджера и руководителя:
    #   simple — простая ЭП (повторный ввод пароля + серверный HMAC);
    #   cades  — усиленная ЭП (CAdES-BES), подпись формируется в браузере через КриптоПро ЭЦП Browser plug-in.
    signature_provider: str = "simple"

    # Проверка усиленной ЭП на сервере средствами КриптоПро CSP (утилита cryptcp). Корневые сертификаты
    # УЦ должны быть установлены в доверенные у пользователя, от имени которого работает сервис.
    cryptcp_path: str = "/opt/cprocsp/bin/amd64/cryptcp"
    # Проверять отзыв сертификатов (CRL/OCSP); в закрытой сети без доступа к спискам отзыва — false
    cades_check_revocation: bool = True
    cades_verify_timeout: int = 30

    # Учётная запись администратора, создаётся при первом запуске
    admin_username: str = "admin"

    # --- Секреты ---
    database_url: SecretStr
    secret_key: SecretStr = Field(min_length=32)
    admin_password: SecretStr = Field(min_length=8)


settings = Settings()
