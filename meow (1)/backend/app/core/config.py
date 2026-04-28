import os


class Settings:
    def __init__(self) -> None:
        self.app_title = os.getenv("APP_TITLE", "MISIS RUDN Low cortizol")
        self.app_host = os.getenv("APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("APP_PORT", "8000"))

        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.default_model = os.getenv("DEFAULT_MODEL", "qwen2.5-coder:7b")
        self.max_iterations = int(os.getenv("MAX_ITERATIONS", "3"))

        self.db_path = os.getenv("DB_PATH", "/data/app.db")
        self.uploads_dir = os.getenv("UPLOADS_DIR", "/data/uploads")


settings = Settings()