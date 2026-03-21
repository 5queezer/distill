---
title: AWS Backend Setup
---

# AWS Backend (RDS + Bedrock)

The AWS setup uses Amazon RDS PostgreSQL with pgvector for storage and Amazon Bedrock Titan Embed v2 for embeddings.

## Prerequisites

- An AWS account
- AWS CLI configured (`aws configure`)
- An RDS PostgreSQL instance (version 15+ recommended for pgvector support)
- IAM permissions for Bedrock (`bedrock:InvokeModel`)

## Step 1: Create an RDS PostgreSQL instance

```bash
aws rds create-db-instance \
  --db-instance-identifier distill-db \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 15.7 \
  --master-username distill \
  --master-user-password <your-password> \
  --allocated-storage 20
```

Ensure your security group allows inbound connections on port 5432 from your machine.

## Step 2: Enable pgvector

Connect to the instance and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Step 3: Configure environment

```bash
export BACKEND=postgres
export DATABASE_URL="postgresql://distill:<your-password>@distill-db.<id>.<region>.rds.amazonaws.com:5432/distill"
export EMBEDDING_PROVIDER=bedrock
export AWS_REGION=us-east-1
```

Bedrock access uses the default AWS credential chain (environment variables, `~/.aws/credentials`, or instance role). No extra key configuration is needed.

## Step 4: Start Distill

```bash
python -m distill_mcp
```

The PostgreSQL store will automatically create the `memories` table, pgvector extension, full-text search indexes, and RLS policies.

## Cost

Varies by instance type. A `db.t4g.micro` instance costs approximately **$13/month** (on-demand). Bedrock Titan Embed v2 pricing is per input token and negligible at typical usage volumes.
