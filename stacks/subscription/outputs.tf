output "subscription_id" {
  description = "Redis Cloud subscription id."
  value       = rediscloud_subscription.this.id
}

output "subscription_name" {
  description = "Redis Cloud subscription name."
  value       = rediscloud_subscription.this.name
}

output "region" {
  description = "Redis Cloud AWS region."
  value       = local.region
}

output "public_endpoint_access" {
  description = "Whether public endpoint access is enabled for this subscription."
  value       = local.public_endpoint_access
}
