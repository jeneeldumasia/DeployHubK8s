from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DeployHub"
    backend_version: str = "2.0.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mongo_uri: str = ""
    mongo_root_user: str = "root"
    mongo_root_password: str = ""
    mongo_db_name: str = "deployhub"
    data_root: str = "/data"
    repo_root: str = "/data/repos"
    generated_dockerfile_root: str = "/data/generated-dockerfiles"
    deployment_network: str | None = None
    deployment_mode: str = "docker"
    public_base_url: str = "http://localhost"
    allowed_repo_hosts: str = "github.com"
    docker_build_timeout_seconds: int = 1800
    docker_run_retry_count: int = 5
    port_range_start: int = 3100
    port_range_end: int = 3999
    cors_origins: str = "*"
    aws_region: str = "us-east-1"
    base_domain: str = "jeneeldumasia.codes"

    k8s_namespace: str = "deployhub"
    apps_namespace: str = "deployhub-apps"
    buildkit_addr: str = "tcp://buildkitd:1234"
    buildkit_timeout_seconds: int = 1800
    build_timeout_seconds: int = 600
    max_concurrent_builds: int = 3
    registry_addr: str = "registry:5000"
    registry_insecure: bool = False
    ecr_registry: str = ""

    github_webhook_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def resolved_mongo_uri(self) -> str:
        if self.mongo_uri.strip():
            return self.mongo_uri.strip()
        if self.mongo_root_password:
            user = quote_plus(self.mongo_root_user)
            password = quote_plus(self.mongo_root_password)
            return (
                f"mongodb://{user}:{password}@mongodb-service:27017/"
                f"{self.mongo_db_name}?authSource=admin"
            )
        return f"mongodb://mongodb-service:27017/{self.mongo_db_name}"

    @property
    def allowed_repo_host_list(self) -> list[str]:
        return [host.strip().lower() for host in self.allowed_repo_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
