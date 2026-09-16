# Repository Guidelines

## Project Structure & Module Organization

This repository delivers Redis Cloud automation through Terraform and manually triggered GitHub Actions.

- `.github/workflows/rediscloud-manage.yml`: manual apply/destroy workflow for subscriptions and databases.
- `.github/workflows/terraform-validate.yml`: Terraform format and validation workflow.
- `stacks/state-backend`: one-time AWS S3 state bucket and GitHub OIDC bootstrap.
- `stacks/subscription`: Redis Cloud Pro subscription stack.
- `stacks/database`: Redis Cloud database, ACL rule, ACL role, and ACL user stack.
- `modules/terraform_state_backend`: reusable backend bootstrap module.
- `docs/customer-setup.md`: customer onboarding and operations guide.

Future resources, such as Agent Memory, should use a dedicated stack and state prefix.

## Build, Test, and Development Commands

Run from the repository root:

- `terraform fmt -recursive`: format all Terraform code.
- `terraform fmt -check -recursive`: verify formatting in CI style.
- `terraform -chdir=stacks/<stack> init -backend=false`: initialize a stack without remote state.
- `terraform -chdir=stacks/<stack> validate`: validate a stack after init.

Validate all current stacks:

```bash
for stack in stacks/state-backend stacks/subscription stacks/database; do
  terraform -chdir="$stack" init -backend=false
  terraform -chdir="$stack" validate
done
```

## Coding Style & Naming Conventions

Use Terraform `>= 1.10`. Keep stack files flat: `main.tf`, `variables.tf`, `locals.tf`, `outputs.tf`, `providers.tf`, `versions.tf`, and `terraform.tfvars.example`. Use snake_case for Terraform identifiers and lowercase, hyphen-separated values for Redis Cloud names, for example `customer-prod` or `rewards-cache`.

Keep customer-facing comments clear and operational. Avoid hardcoding secrets or customer-only values.

## Testing Guidelines

Required checks are Terraform formatting and validation. Add a plan summary to pull requests when behavior changes. Do not commit `.terraform/`, generated backend files, state files, plans, or runtime `*.auto.tfvars.json` files. Commit `.terraform.lock.hcl` files after provider initialization.

## Commit & Pull Request Guidelines

Use short, imperative commit messages such as `Add state backend bootstrap` or `Update Redis Cloud workflow inputs`. Pull requests should include the affected stacks, validation results, and any manual workflow behavior changes.

## Security & Configuration Tips

State contains sensitive values, including generated ACL passwords. Keep S3 state encrypted, versioned, private, and accessible only through approved GitHub Actions OIDC roles. Never print sensitive Terraform outputs in workflow summaries or logs.
