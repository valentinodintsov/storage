class ServiceError(Exception):
    """Нарушение бизнес-правила; сообщение показывается пользователю."""

    status_code = 400

    def __init__(self, message: str = "Ошибка"):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404

    def __init__(self, message: str = "Объект не найден"):
        super().__init__(message)


class Forbidden(ServiceError):
    status_code = 403

    def __init__(self, message: str = "Недостаточно прав для выполнения операции"):
        super().__init__(message)


class NotAuthenticated(ServiceError):
    status_code = 401

    def __init__(self, message: str = "Требуется вход в систему"):
        super().__init__(message)
