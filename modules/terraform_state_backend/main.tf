terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }

    external = {
      source = "hashicorp/external"
    }
  }
}

locals {
  existing_role_names = toset([
    for arn in var.github_actions_role_arns : element(reverse(split("/", arn)), 0)
  ])

  managed_role_definitions = var.create_github_actions_roles ? var.github_actions_role_names_by_environment : {}

  role_names = setunion(
    local.existing_role_names,
    toset(values(local.managed_role_definitions))
  )

  object_resource_arns = [
    for prefix in var.allowed_state_prefixes : "arn:aws:s3:::${var.bucket_name}/${prefix}"
  ]

  github_oidc_provider_arn = coalesce(
    try(aws_iam_openid_connect_provider.github[0].arn, null),
    var.github_oidc_provider_arn,
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
  )

  branch_subjects = var.create_github_actions_roles ? [
    for branch in var.github_allowed_branches : "repo:${var.github_repository_owner}/${var.github_repository_name}:ref:refs/heads/${branch}"
  ] : []
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

# The backend bucket is commonly created by a one-time bootstrap run. This check
# keeps the stack idempotent when the bucket already exists in the target account.
data "external" "bucket_check" {
  program = ["python3", "${path.module}/../../scripts/check_s3_bucket.py"]

  query = {
    bucket_name = var.bucket_name
  }
}

resource "aws_s3_bucket" "this" {
  count = data.external.bucket_check.result.exists == "true" ? 0 : 1

  bucket        = var.bucket_name
  force_destroy = var.force_destroy
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = var.bucket_name

  depends_on = [aws_s3_bucket.this]

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = var.bucket_name

  depends_on = [aws_s3_bucket.this]

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = var.bucket_name

  depends_on = [aws_s3_bucket.this]

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = var.bucket_name

  depends_on = [aws_s3_bucket.this]

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "bucket_policy" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      "arn:aws:s3:::${var.bucket_name}",
      "arn:aws:s3:::${var.bucket_name}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = var.bucket_name
  policy = data.aws_iam_policy_document.bucket_policy.json

  depends_on = [aws_s3_bucket.this]
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = []

  tags = merge(
    var.tags,
    {
      component = "github-oidc-provider"
    }
  )
}

data "aws_iam_policy_document" "github_oidc_trust" {
  for_each = local.managed_role_definitions

  statement {
    sid     = "GitHubActionsOIDC"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = concat(
        local.branch_subjects,
        [
          "repo:${var.github_repository_owner}/${var.github_repository_name}:environment:${each.key}",
          "repo:${var.github_repository_owner}/${var.github_repository_name}:environment:destroy-${each.key}"
        ]
      )
    }
  }
}

resource "aws_iam_role" "github_actions" {
  for_each = local.managed_role_definitions

  name               = each.value
  assume_role_policy = data.aws_iam_policy_document.github_oidc_trust[each.key].json

  tags = merge(
    var.tags,
    {
      component   = "github-actions-oidc-role"
      environment = each.key
    }
  )
}

data "aws_iam_policy_document" "backend_access" {
  statement {
    sid    = "TerraformStateBucket"
    effect = "Allow"

    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket"
    ]

    resources = ["arn:aws:s3:::${var.bucket_name}"]
  }

  statement {
    sid    = "TerraformStateObjects"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject"
    ]

    resources = local.object_resource_arns
  }
}

resource "aws_iam_role_policy" "backend_access" {
  for_each = local.role_names

  name   = "terraform-state-${substr(sha1(var.bucket_name), 0, 12)}"
  role   = each.value
  policy = data.aws_iam_policy_document.backend_access.json
}
