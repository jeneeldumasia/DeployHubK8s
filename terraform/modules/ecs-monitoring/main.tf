# ═══════════════════════════════════════════════════════════════════════════════
# ECS Monitoring Stack — Production-grade observability on Fargate
#
# Components:
#   Prometheus  — scrapes EKS backend /metrics, remote-writes to Mimir
#   Mimir       — scalable long-term metrics storage backed by S3
#   Loki        — log aggregation backend backed by S3
#   Grafana     — unified UI: queries Mimir (metrics) + Loki (logs)
#                 pre-provisioned datasources + DeployHub dashboard
#
# All services run on ECS Fargate (serverless — no EC2 to manage).
# Persistent data lives in S3 (survives task restarts, scales infinitely).
# EFS is NOT used — S3 backend is simpler and cheaper for this workload.
# ═══════════════════════════════════════════════════════════════════════════════

# ── ECS Cluster ───────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "monitoring" {
  name = "${var.project}-monitoring"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecs_cluster_capacity_providers" "monitoring" {
  cluster_name       = aws_ecs_cluster.monitoring.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "monitoring" {
  name              = "/ecs/${var.project}-monitoring"
  retention_in_days = 7
  tags              = var.tags
}

# ── S3 Bucket — Mimir + Loki object storage ───────────────────────────────────
resource "aws_s3_bucket" "observability" {
  bucket        = "${var.project}-observability-${var.aws_account_id}"
  force_destroy = true   # allow destroy without emptying first
  tags          = merge(var.tags, { Name = "${var.project}-observability" })
}

resource "aws_s3_bucket_versioning" "observability" {
  bucket = aws_s3_bucket.observability.id
  versioning_configuration { status = "Disabled" }  # not needed for metrics/logs
}

resource "aws_s3_bucket_server_side_encryption_configuration" "observability" {
  bucket = aws_s3_bucket.observability.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "observability" {
  bucket                  = aws_s3_bucket.observability.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── IAM — ECS Task Execution Role ────────────────────────────────────────────
resource "aws_iam_role" "ecs_execution" {
  name = "${var.project}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ── IAM — ECS Task Role (S3 access for Mimir + Loki) ─────────────────────────
resource "aws_iam_role" "ecs_task" {
  name = "${var.project}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.project}-ecs-task-s3"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
        "s3:ListBucket", "s3:GetBucketLocation"
      ]
      Resource = [
        aws_s3_bucket.observability.arn,
        "${aws_s3_bucket.observability.arn}/*"
      ]
    }]
  })
}

# ── Secrets Manager — Grafana credentials ────────────────────────────────────
resource "aws_secretsmanager_secret" "grafana" {
  name                    = "${var.project}/grafana-credentials"
  recovery_window_in_days = 0
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "grafana" {
  secret_id = aws_secretsmanager_secret.grafana.id
  secret_string = jsonencode({
    "admin-user"     = var.grafana_admin_user
    "admin-password" = var.grafana_admin_password
  })
}

# ── Mimir config ─────────────────────────────────────────────────────────────
# Stored in SSM Parameter Store so the Fargate task can read it at startup
resource "aws_ssm_parameter" "mimir_config" {
  name  = "/${var.project}/mimir/config"
  type  = "String"
  value = <<-YAML
    target: all
    auth_enabled: false

    server:
      http_listen_port: 9009
      grpc_listen_port: 9095
      log_level: warn

    ingester:
      ring:
        replication_factor: 1
        kvstore:
          store: memberlist

    blocks_storage:
      backend: s3
      s3:
        bucket_name: ${aws_s3_bucket.observability.bucket}
        region: ${var.aws_region}
        endpoint: s3.${var.aws_region}.amazonaws.com
      tsdb:
        dir: /tmp/mimir/tsdb
      bucket_store:
        sync_dir: /tmp/mimir/tsdb-sync

    compactor:
      data_dir: /tmp/mimir/compactor
      sharding_ring:
        kvstore:
          store: memberlist

    store_gateway:
      sharding_ring:
        replication_factor: 1
        kvstore:
          store: memberlist

    ruler_storage:
      backend: s3
      s3:
        bucket_name: ${aws_s3_bucket.observability.bucket}
        region: ${var.aws_region}
        endpoint: s3.${var.aws_region}.amazonaws.com

    memberlist:
      join_members: []

    limits:
      ingestion_rate: 10000
      max_global_series_per_user: 100000
      compactor_blocks_retention_period: 30d
  YAML
  tags  = var.tags
}

# ── Loki config ───────────────────────────────────────────────────────────────
resource "aws_ssm_parameter" "loki_config" {
  name  = "/${var.project}/loki/config"
  type  = "String"
  value = <<-YAML
    auth_enabled: false

    server:
      http_listen_port: 3100
      grpc_listen_port: 9096
      log_level: warn

    common:
      replication_factor: 1
      ring:
        kvstore:
          store: inmemory

    schema_config:
      configs:
        - from: "2024-01-01"
          store: tsdb
          object_store: s3
          schema: v13
          index:
            prefix: loki_index_
            period: 24h

    storage_config:
      tsdb_shipper:
        active_index_directory: /tmp/loki/index
        cache_location: /tmp/loki/cache
      aws:
        s3: s3://${var.aws_region}/${aws_s3_bucket.observability.bucket}
        region: ${var.aws_region}
        s3forcepathstyle: true

    limits_config:
      retention_period: 168h
      ingestion_rate_mb: 16
      ingestion_burst_size_mb: 32

    compactor:
      working_directory: /tmp/loki/compactor
      retention_enabled: true
      retention_delete_delay: 2h
      delete_request_store: s3
  YAML
  tags  = var.tags
}

# ── Prometheus config ─────────────────────────────────────────────────────────
resource "aws_ssm_parameter" "prometheus_config" {
  name  = "/${var.project}/prometheus/config"
  type  = "String"
  value = <<-YAML
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
      external_labels:
        cluster: deployhub-eks
        env: prod

    # Remote write to Mimir for long-term storage
    remote_write:
      - url: http://mimir.${var.project}.local:9009/api/v1/push
        queue_config:
          max_samples_per_send: 1000
          max_shards: 5
          capacity: 2500

    scrape_configs:
      - job_name: deployhub-backend
        static_configs:
          - targets: ['${var.eks_metrics_endpoint_host}:${var.eks_metrics_endpoint_port}']
        metrics_path: /metrics

      - job_name: prometheus
        static_configs:
          - targets: ['localhost:9090']

    rule_files:
      - /etc/prometheus/alerts.yml
  YAML
  tags  = var.tags
}

resource "aws_ssm_parameter" "prometheus_alerts" {
  name  = "/${var.project}/prometheus/alerts"
  type  = "String"
  value = <<-YAML
    groups:
      - name: deployhub
        rules:
          - alert: BackendDown
            expr: up{job="deployhub-backend"} == 0
            for: 1m
            labels:
              severity: critical
            annotations:
              summary: "DeployHub backend is unreachable"

          - alert: HighDeploymentFailureRate
            expr: rate(deployhub_deployment_failures_total[5m]) > 0.1
            for: 2m
            labels:
              severity: warning
            annotations:
              summary: "High deployment failure rate"

          - alert: HealthCheckFailures
            expr: increase(deployhub_health_check_failures_total[10m]) > 2
            for: 1m
            labels:
              severity: warning
            annotations:
              summary: "Multiple health check failures"

          - alert: PodRestartingFrequently
            expr: deployhub_pod_restarts_total > 5
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Pod restarting frequently"
  YAML
  tags  = var.tags
}

# ── Grafana datasources + dashboard provisioning ──────────────────────────────
resource "aws_ssm_parameter" "grafana_datasources" {
  name  = "/${var.project}/grafana/datasources"
  type  = "String"
  value = <<-YAML
    apiVersion: 1
    datasources:
      - name: Mimir
        type: prometheus
        url: http://mimir.${var.project}.local:9009/prometheus
        access: proxy
        isDefault: true
        editable: false
        jsonData:
          httpMethod: POST
          prometheusType: Mimir

      - name: Prometheus
        type: prometheus
        url: http://prometheus.${var.project}.local:9090
        access: proxy
        isDefault: false
        editable: false

      - name: Loki
        type: loki
        url: http://loki.${var.project}.local:3100
        access: proxy
        isDefault: false
        editable: false
  YAML
  tags  = var.tags
}

# ── Service Discovery via Cloud Map ──────────────────────────────────────────
# Allows ECS services to find each other by DNS name within the VPC
resource "aws_service_discovery_private_dns_namespace" "monitoring" {
  name        = "${var.project}.local"
  description = "Private DNS for DeployHub monitoring services"
  vpc         = var.vpc_id
  tags        = var.tags
}

resource "aws_service_discovery_service" "mimir" {
  name = "mimir"
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.monitoring.id
    routing_policy = "MULTIVALUE"
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

resource "aws_service_discovery_service" "loki" {
  name = "loki"
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.monitoring.id
    routing_policy = "MULTIVALUE"
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

resource "aws_service_discovery_service" "prometheus" {
  name = "prometheus"
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.monitoring.id
    routing_policy = "MULTIVALUE"
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
  health_check_custom_config { failure_threshold = 1 }
}

# ── Mimir Task Definition ─────────────────────────────────────────────────────
resource "aws_ecs_task_definition" "mimir" {
  family                   = "${var.project}-mimir"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "mimir"
    image     = "grafana/mimir:2.12.0"
    essential = true

    command = [
      "-config.file=/etc/mimir/mimir.yaml",
      "-target=all"
    ]

    portMappings = [
      { containerPort = 9009, protocol = "tcp", name = "http" },
      { containerPort = 9095, protocol = "tcp", name = "grpc" }
    ]

    environment = [
      { name = "AWS_DEFAULT_REGION", value = var.aws_region }
    ]

    # Fetch config from SSM at startup via entrypoint wrapper
    entryPoint = ["sh", "-c"]
    command = [
      "mkdir -p /etc/mimir && aws ssm get-parameter --name /${var.project}/mimir/config --region ${var.aws_region} --query Parameter.Value --output text > /etc/mimir/mimir.yaml && /bin/mimir -config.file=/etc/mimir/mimir.yaml -target=all"
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.monitoring.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "mimir"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://localhost:9009/ready || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  tags = var.tags
}

# ── Loki Task Definition ──────────────────────────────────────────────────────
resource "aws_ecs_task_definition" "loki" {
  family                   = "${var.project}-loki"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "loki"
    image     = "grafana/loki:3.0.0"
    essential = true

    entryPoint = ["sh", "-c"]
    command = [
      "mkdir -p /etc/loki && aws ssm get-parameter --name /${var.project}/loki/config --region ${var.aws_region} --query Parameter.Value --output text > /etc/loki/loki.yaml && /usr/bin/loki -config.file=/etc/loki/loki.yaml"
    ]

    portMappings = [
      { containerPort = 3100, protocol = "tcp", name = "http" },
      { containerPort = 9096, protocol = "tcp", name = "grpc" }
    ]

    environment = [
      { name = "AWS_DEFAULT_REGION", value = var.aws_region }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.monitoring.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "loki"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://localhost:3100/ready || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }
  }])

  tags = var.tags
}

# ── Prometheus Task Definition ────────────────────────────────────────────────
resource "aws_ecs_task_definition" "prometheus" {
  family                   = "${var.project}-prometheus"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "prometheus"
    image     = "prom/prometheus:v2.52.0"
    essential = true

    entryPoint = ["sh", "-c"]
    command = [
      "mkdir -p /etc/prometheus && aws ssm get-parameter --name /${var.project}/prometheus/config --region ${var.aws_region} --query Parameter.Value --output text > /etc/prometheus/prometheus.yml && aws ssm get-parameter --name /${var.project}/prometheus/alerts --region ${var.aws_region} --query Parameter.Value --output text > /etc/prometheus/alerts.yml && /bin/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=2h --web.enable-lifecycle"
    ]

    portMappings = [
      { containerPort = 9090, protocol = "tcp", name = "http" }
    ]

    environment = [
      { name = "AWS_DEFAULT_REGION", value = var.aws_region }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.monitoring.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "prometheus"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://localhost:9090/-/healthy || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
  }])

  tags = var.tags
}

# ── Grafana Task Definition ───────────────────────────────────────────────────
resource "aws_ecs_task_definition" "grafana" {
  family                   = "${var.project}-grafana"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "grafana"
    image     = "grafana/grafana:11.0.0"
    essential = true

    entryPoint = ["sh", "-c"]
    command = [
      "mkdir -p /etc/grafana/provisioning/datasources && aws ssm get-parameter --name /${var.project}/grafana/datasources --region ${var.aws_region} --query Parameter.Value --output text > /etc/grafana/provisioning/datasources/datasources.yaml && /run.sh"
    ]

    portMappings = [
      { containerPort = 3000, protocol = "tcp", name = "http" }
    ]

    environment = [
      { name = "GF_USERS_ALLOW_SIGN_UP",           value = "false" },
      { name = "GF_SERVER_ROOT_URL",                value = "http://${var.alb_dns_name}/grafana" },
      { name = "GF_SERVER_SERVE_FROM_SUB_PATH",     value = "true" },
      { name = "GF_AUTH_ANONYMOUS_ENABLED",         value = "false" },
      { name = "GF_FEATURE_TOGGLES_ENABLE",         value = "lokiExploreLogsDefaultRange" },
      { name = "AWS_DEFAULT_REGION",                value = var.aws_region }
    ]

    secrets = [
      { name = "GF_SECURITY_ADMIN_USER",     valueFrom = "${aws_secretsmanager_secret.grafana.arn}:admin-user::" },
      { name = "GF_SECURITY_ADMIN_PASSWORD", valueFrom = "${aws_secretsmanager_secret.grafana.arn}:admin-password::" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.monitoring.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "grafana"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "wget -qO- http://localhost:3000/grafana/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  tags = var.tags
}

# ── ECS Services ──────────────────────────────────────────────────────────────

resource "aws_ecs_service" "mimir" {
  name            = "${var.project}-mimir"
  cluster         = aws_ecs_cluster.monitoring.id
  task_definition = aws_ecs_task_definition.mimir.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.mimir.arn
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  tags                               = var.tags
}

resource "aws_ecs_service" "loki" {
  name            = "${var.project}-loki"
  cluster         = aws_ecs_cluster.monitoring.id
  task_definition = aws_ecs_task_definition.loki.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.loki.arn
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  tags                               = var.tags
}

resource "aws_ecs_service" "prometheus" {
  name            = "${var.project}-prometheus"
  cluster         = aws_ecs_cluster.monitoring.id
  task_definition = aws_ecs_task_definition.prometheus.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.prometheus.arn
  }

  # Prometheus depends on Mimir being up for remote_write
  depends_on = [aws_ecs_service.mimir]

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  tags                               = var.tags
}

resource "aws_ecs_service" "grafana" {
  name            = "${var.project}-grafana"
  cluster         = aws_ecs_cluster.monitoring.id
  task_definition = aws_ecs_task_definition.grafana.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.grafana_target_group_arn
    container_name   = "grafana"
    container_port   = 3000
  }

  # Grafana depends on both Mimir and Loki being registered in service discovery
  depends_on = [aws_ecs_service.mimir, aws_ecs_service.loki]

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  tags                               = var.tags
}

# ── SSM read permission for ECS task execution role ───────────────────────────
# Tasks fetch their configs from SSM Parameter Store at startup
resource "aws_iam_role_policy" "ecs_execution_ssm" {
  name = "${var.project}-ecs-execution-ssm"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:${var.aws_region}:${var.aws_account_id}:parameter/${var.project}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.grafana.arn
      }
    ]
  })
}
