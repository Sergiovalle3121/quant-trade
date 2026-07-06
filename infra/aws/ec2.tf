# The 24/7 paper runtime: one t3.small in the default VPC, egress-only,
# managed via SSM (no SSH key, no inbound ports). Docker restarts the
# container on crash or reboot; the dead-man alarm catches everything else.

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023*-x86_64"]
  }
}

resource "aws_security_group" "paper_host" {
  name        = "${var.project_name}-${var.environment}-host"
  description = "Egress-only paper trading host"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "paper_host" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.paper_host.name
  vpc_security_group_ids = [aws_security_group.paper_host.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    aws ecr get-login-password --region ${var.aws_region} \
      | docker login --username AWS --password-stdin \
        $(echo ${var.image_uri} | cut -d/ -f1)
    docker pull ${var.image_uri}
    # Default command is the safe health check; operators switch the running
    # command to the paper loop after reviewing configs (see infra README).
    docker run -d --name quant-trade --restart unless-stopped \
      --log-driver awslogs \
      --log-opt awslogs-region=${var.aws_region} \
      --log-opt awslogs-group=${aws_cloudwatch_log_group.app.name} \
      --log-opt awslogs-create-group=false \
      ${var.image_uri}
  EOF

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Project     = var.project_name
    Environment = var.environment
  }
}
