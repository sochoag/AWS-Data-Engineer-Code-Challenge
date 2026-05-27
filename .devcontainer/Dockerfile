FROM python:3.11-slim-bullseye

# Suppress interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# ── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    git \
    make \
    groff \
    less \
    && rm -rf /var/lib/apt/lists/*

# ── AWS CLI v2 ────────────────────────────────────────────────────────────────
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# ── AWS SAM CLI ───────────────────────────────────────────────────────────────
RUN curl -fsSL "https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip" \
        -o /tmp/sam-cli.zip \
    && unzip -q /tmp/sam-cli.zip -d /tmp/sam-install \
    && /tmp/sam-install/install \
    && rm -rf /tmp/sam-cli.zip /tmp/sam-install

# ── Python dev dependencies ───────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    boto3 \
    pandas \
    pytest \
    awswrangler

# ── Docker CLI (allows SAM to use the host Docker socket for builds) ─────────
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-24.0.7.tgz \
        -o /tmp/docker.tgz \
    && tar -xz -C /tmp -f /tmp/docker.tgz \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker.tgz /tmp/docker

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /workspace

CMD ["bash"]
