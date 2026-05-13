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

# ── IAM — ECS Task Role (Prometheus needs to describe ECS tasks) ──────────────
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

# ── EFS for persistent storage (Prometheus + Grafana data) ───────────────────
resource "aws_efs_file_system" "monitoring" {
  creation_token   = "${var.project}-monitoring-efs"
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  encrypted        = true

  tags = merge(var.tags, { Name = "${var.project}-monitoring-efs" })
}

resource "aws_efs_mount_target" "monitoring" {
  count           = length(var.private_subnet_ids)
  file_system_id  = aws_efs_file_system.monitoring.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [var.ecs_tasks_security_group_id]
}

resource "aws_efs_access_point" "prometheus" {
  file_system_id = aws_efs_file_system.monitoring.id
  posix_user {
    uid = 65534
    gid = 65534
  }
  root_directory {
    path = "/prometheus"
    creation_info {
      owner_uid   = 65534
      owner_gid   = 65534
      permissions = "755"
    }
  }
  tags = merge(var.tags, { Name = "${var.project}-prometheus-ap" })
}

resource "aws_efs_access_point" "grafana" {
  file_system_id = aws_efs_file_system.monitoring.id
  posix_user {
    uid = 472
    gid = 472
  }
  root_directory {
    path = "/grafana"
    creation_info {
      owner_uid   = 472
      owner_gid   = 472
      permissions = "755"
    }
  }
  tags = merge(var.tags, { Name = "${var.project}-grafana-ap" })
}

resource "aws_efs_access_point" "loki" {
  file_system_id = aws_efs_file_system.monitoring.id
  posix_user {
    uid = 10001
    gid = 10001
  }
  root_directory {
    path = "/loki"
    creation_info {
      owner_uid   = 10001
      owner_gid   = 10001
      permissions = "755"
    }
  }
  tags = merge(var.tags, { Name = "${var.project}-loki-ap" })
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

    command = [
      "--config.file=/etc/prometheus/prometheus.yml",
      "--storage.tsdb.path=/prometheus",
      "--storage.tsdb.retention.time=15d",
      "--web.enable-lifecycle"
    ]

    portMappings = [{ containerPort = 9090, protocol = "tcp" }]

    mountPoints = [{
      sourceVolume  = "prometheus-data"
      containerPath = "/prometheus"
      readOnly      = false
    }]

    environment = [{
      name  = "EKS_METRICS_ENDPOINT"
      value = var.eks_metrics_endpoint
    }]

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

  volume {
    name = "prometheus-data"
    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.monitoring.id
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.prometheus.id
        iam             = "ENABLED"
      }
    }
  }

  tags = var.tags
}

# ── Grafana Task Definition ───────────────────────────────────────────────────
resource "aws_ecs_task_definition" "grafana" {
  family                   = "${var.project}-grafana"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "grafana"
    image     = "grafana/grafana:11.0.0"
    essential = true

    portMappings = [{ containerPort = 3000, protocol = "tcp" }]

    mountPoints = [{
      sourceVolume  = "grafana-data"
      containerPath = "/var/lib/grafana"
      readOnly      = false
    }]

    environment = [
      { name = "GF_USERS_ALLOW_SIGN_UP",    value = "false" },
      { name = "GF_SERVER_ROOT_URL",         value = "http://${var.alb_dns_name}/grafana" },
      { name = "GF_SERVER_SERVE_FROM_SUB_PATH", value = "true" }
    ]

    secrets = [
      { name = "GF_SECURITY_ADMIN_USER",     valueFrom = "${var.grafana_secret_arn}:admin-user::" },
      { name = "GF_SECURITY_ADMIN_PASSWORD", valueFrom = "${var.grafana_secret_arn}:admin-password::" }
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
      command     = ["CMD-SHELL", "wget -qO- http://localhost:3000/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  volume {
    name = "grafana-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.monitoring.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.grafana.id
        iam             = "ENABLED"
      }
    }
  }

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

    command = ["-config.file=/etc/loki/loki.yaml"]

    portMappings = [
      { containerPort = 3100, protocol = "tcp" },
      { containerPort = 9096, protocol = "tcp" }
    ]

    mountPoints = [{
      sourceVolume  = "loki-data"
      containerPath = "/loki"
      readOnly      = false
    }]

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
      startPeriod = 15
    }
  }])

  volume {
    name = "loki-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.monitoring.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.loki.id
        iam             = "ENABLED"
      }
    }
  }

  tags = var.tags
}

# ── ECS Services ──────────────────────────────────────────────────────────────
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

  # Allow in-place updates without downtime
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  tags = var.tags
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

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  tags = var.tags
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

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  tags = var.tags
}

# ── Secrets Manager — Grafana credentials ────────────────────────────────────
resource "aws_secretsmanager_secret" "grafana" {
  name                    = "${var.project}/grafana-credentials"
  recovery_window_in_days = 0   # immediate deletion (no 30-day window for playground)
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "grafana" {
  secret_id = aws_secretsmanager_secret.grafana.id
  secret_string = jsonencode({
    "admin-user"     = var.grafana_admin_user
    "admin-password" = var.grafana_admin_password
  })
}

# Allow ECS execution role to read the secret
resource "aws_iam_role_policy" "ecs_read_secrets" {
  name = "${var.project}-ecs-read-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.grafana.arn
    }]
  })
}
