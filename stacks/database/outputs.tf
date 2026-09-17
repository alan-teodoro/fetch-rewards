output "subscription_name" {
  description = "Redis Cloud subscription name."
  value       = data.rediscloud_subscription.target.name
}

output "subscription_id" {
  description = "Redis Cloud subscription id."
  value       = data.rediscloud_subscription.target.id
}

output "database_name" {
  description = "Redis Cloud database name."
  value       = rediscloud_subscription_database.this.name
}

output "database_id" {
  description = "Redis Cloud database id."
  value       = rediscloud_subscription_database.this.db_id
}

output "redis_version_requested" {
  description = "Requested Redis version for the database."
  value       = rediscloud_subscription_database.this.redis_version
}

output "redis_version_actual" {
  description = "Actual Redis version used by Redis Cloud."
  value       = rediscloud_subscription_database.this.redis_version_actual
}

output "private_endpoint" {
  description = "Redis Cloud private endpoint."
  value       = rediscloud_subscription_database.this.private_endpoint
}

output "public_endpoint" {
  description = "Redis Cloud public endpoint, if subscription public endpoint access is enabled."
  value       = rediscloud_subscription_database.this.public_endpoint
}

output "acl_rule_name" {
  description = "Redis Cloud ACL rule name."
  value       = rediscloud_acl_rule.this.name
}

output "acl_role_name" {
  description = "Redis Cloud ACL role name."
  value       = rediscloud_acl_role.this.name
}

output "acl_user_name" {
  description = "Redis Cloud ACL user name."
  value       = rediscloud_acl_user.this.name
}

output "acl_user_password" {
  description = "Redis Cloud ACL user password."
  value       = local.acl_user_password
  sensitive   = true
}
