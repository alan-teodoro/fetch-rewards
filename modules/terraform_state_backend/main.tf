terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  # Attachments need role names rather than full ARNs. Splitting at the last
  # slash also handles roles created under an IAM path. Sets remove duplicates.
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

  # OIDC selection: newly created provider, explicitly supplied ARN, then the
  # standard provider ARN in the current AWS account/partition. The fallback
  # refers to an existing provider; it does not create one.
  github_oidc_provider_arn = coalesce(
    try(aws_iam_openid_connect_provider.github[0].arn, null),
    var.github_oidc_provider_arn,
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
  )

  # Plan jobs have branch subjects; approved apply jobs have environment
  # subjects. Both identities must be trusted for the two-job workflow to work.
  branch_subjects = var.create_github_actions_roles ? [
    for branch in var.github_allowed_branches : "repo:${var.github_repository_owner}/${var.github_repository_name}:ref:refs/heads/${branch}"
  ] : []
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

# Ownership is explicit and stable across runs. Detecting existence here would
# remove a previously created bucket from configuration on the next apply.
resource "aws_s3_bucket" "this" {
  count = var.create_bucket ? 1 : 0

  bucket        = var.bucket_name
  force_destroy = var.force_destroy
  tags          = var.tags
}

# Reuse verifies the bucket exists without adopting the bucket resource.
# Encryption, versioning, policy and ownership controls below are still managed.
data "aws_s3_bucket" "existing" {
  count  = var.create_bucket ? 0 : 1
  bucket = var.bucket_name
}

locals {
  backend_bucket_id = var.create_bucket ? aws_s3_bucket.this[0].id : data.aws_s3_bucket.existing[0].id
}

# Versioning retains previous state versions for recovery. Suspending it does
# not remove older versions; retention remains an operating-policy decision.
resource "aws_s3_bucket_versioning" "this" {
  bucket = local.backend_bucket_id

  depends_on = [aws_s3_bucket.this]

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = local.backend_bucket_id

  depends_on = [aws_s3_bucket.this]

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = local.backend_bucket_id

  depends_on = [aws_s3_bucket.this]

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = local.backend_bucket_id

  depends_on = [aws_s3_bucket.this]

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# This deny requires HTTPS even for otherwise authorized principals. S3 bucket
# and object permissions use different ARN forms, so both are listed.
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
  bucket = local.backend_bucket_id
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

    # aud restricts token use to AWS STS; sub restricts who may assume the role.
    # An environment subject must match REDISCLOUD_ENVIRONMENT exactly. The
    # destroy-<environment> subject also supports a separately gated destroy job.
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

# Bucket-level listing and object-level state access are separate permissions.
# Object prefixes must include .tfstate, S3 .tflock objects and reviewed plan
# bundles. DeleteObject is also needed to release locks and clean current bundles.
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

# A stable bucket-derived suffix keeps this account-scoped policy name distinct
# without including an arbitrarily long bucket name in the IAM policy name.
resource "aws_iam_policy" "backend_access" {
  name        = "terraform-state-${substr(sha1(var.bucket_name), 0, 12)}"
  description = "Terraform state access for ${var.bucket_name}."
  policy      = data.aws_iam_policy_document.backend_access.json

  tags = merge(
    var.tags,
    {
      component = "terraform-state-access-policy"
    }
  )
}

resource "aws_iam_role_policy_attachment" "backend_access" {
  for_each = local.role_names

  role       = each.value
  policy_arn = aws_iam_policy.backend_access.arn
}
