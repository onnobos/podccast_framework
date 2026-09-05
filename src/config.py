import tempfile
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console

console = Console()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )

    OPENROUTER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    VOLLEYBRAINS_EMAIL: str
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    R2_PUBLIC_DOMAIN: str

    HOST_A_VOICE: str = "shimmer"
    HOST_B_VOICE: str = "ash"
    CURATOR_MODEL: str = "google/gemini-2.5-pro"
    SCRIPT_MODEL: str = "anthropic/claude-sonnet-4"
    AUDIT_MODEL: str = "google/gemini-2.5-flash"
    TTS_MODEL: str = "openai/gpt-audio"

    @property
    def effective_api_key(self) -> str:
        key = self.OPENROUTER_API_KEY or self.OPENAI_API_KEY
        if not key:
            raise ValueError("Neither OPENROUTER_API_KEY nor OPENAI_API_KEY is set in .env")
        return key

    @property
    def effective_base_url(self) -> str | None:
        if self.OPENROUTER_API_KEY:
            return self.OPENROUTER_BASE_URL
        return None

    @property
    def clean_r2_account_id(self) -> str:
        return self.R2_ACCOUNT_ID.strip().strip("'\"")

    @property
    def clean_r2_public_domain(self) -> str:
        domain = self.R2_PUBLIC_DOMAIN.strip()
        if "](" in domain:
            domain = domain.split("](")[-1].rstrip(")")
        elif domain.startswith("[") and "]" in domain:
            domain = domain.split("]")[0].lstrip("[")
        return domain.replace("https://", "").replace("http://", "").strip("/")

    @property
    def audio_cache_dir(self) -> Path:
        path = Path("output/audio_cache")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def temp_dir(self) -> Path:
        """Persistent project audio cache so Windows Temp never clears downloaded clips."""
        return self.audio_cache_dir

settings = Settings()

if __name__ == "__main__":
    console.print("[bold green]Configuration loaded successfully![/bold green]")
    console.print(f"Temp directory: [cyan]{settings.temp_dir}[/cyan]")
    console.print(f"R2 Bucket: [cyan]{settings.R2_BUCKET_NAME}[/cyan]")
