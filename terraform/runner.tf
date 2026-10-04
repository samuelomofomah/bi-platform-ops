# Linux host for the self-hosted GitHub Actions runner (and Jenkins later).
# It has no SSH key and no inbound ports: you connect through SSM Session
# Manager, and it reaches AWS through an instance role, so no keys are stored.

variable "runner_instance_type" {
  type    = string
  default = "t3.small"
}

# Latest Ubuntu 24.04 LTS image, published by Canonical as a public SSM parameter.
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_iam_role" "runner" {
  name = "bi-platform-ops-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

# S3 backup upload + SNS publish only (the policy defined in main.tf).
resource "aws_iam_role_policy_attachment" "runner_ci" {
  role       = aws_iam_role.runner.name
  policy_arn = aws_iam_policy.ci.arn
}

# Lets Session Manager open a shell on the instance.
resource "aws_iam_role_policy_attachment" "runner_ssm" {
  role       = aws_iam_role.runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "runner" {
  name = "bi-platform-ops-runner"
  role = aws_iam_role.runner.name
}

resource "aws_security_group" "runner" {
  name        = "bi-platform-ops-runner"
  description = "Outbound only. Access is through SSM Session Manager."
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "runner" {
  ami                    = data.aws_ssm_parameter.ubuntu.value
  instance_type          = var.runner_instance_type
  iam_instance_profile   = aws_iam_instance_profile.runner.name
  vpc_security_group_ids = [aws_security_group.runner.id]

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  # First-boot setup: tools the pipeline needs and a persistent data directory.
  user_data = <<-EOT
    #!/bin/bash
    apt-get update
    apt-get install -y python3-venv python3-pip git sqlite3 unzip docker.io
    usermod -aG docker ubuntu
    mkdir -p /var/lib/biops
    chown ubuntu:ubuntu /var/lib/biops
  EOT

  tags = {
    Name = "bi-platform-ops-runner"
  }

  lifecycle {
    ignore_changes = [ami] # a newer image should not replace a configured runner
  }
}

output "runner_instance_id" {
  value = aws_instance.runner.id
}
