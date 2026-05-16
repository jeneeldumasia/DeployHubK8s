from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DeployHub"
    backend_version: str = "2.0.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mongo_uri: str = "mongodb://mongo:27017/deployhub"
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
    deployment_mode: str = "k8s"

    # Kubernetes & BuildKit settings
    k8s_namespace: str = "deployhub"
    buildkit_addr: str = "tcp://buildkitd:1234"
    registry_addr: str = "registry:5000"
    # Set to true only for local insecure registries; ECR and DockerHub are always secure
    registry_insecure: bool = False
    # Optional: set to an ECR registry URL (e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com)
    # when deploying to AWS. If empty, falls back to registry_addr (local in-cluster registry).
    ecr_registry: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def allowed_repo_host_list(self) -> list[str]:
        return [host.strip().lower() for host in self.allowed_repo_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
