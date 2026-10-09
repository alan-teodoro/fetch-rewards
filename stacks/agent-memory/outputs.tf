output "subscription_name" {
  description = "Redis Cloud subscription name."
  value       = local.lookup_subscription ? data.rediscloud_subscription.target[0].name : local.subscription_name
}

output "subscription_id" {
  description = "Redis Cloud subscription ID."
  value       = local.lookup_database ? local.resolved_subscription_id : null
}

output "database_name" {
  description = "Redis Cloud database name backing the Agent Memory service."
  value       = local.lookup_database ? data.rediscloud_database.target[0].name : null
}

output "database_id" {
  description = "Redis Cloud database ID backing the Agent Memory service."
  value       = local.resolved_database_id
}

output "agent_memory_name" {
  description = "Agent Memory service name."
  value       = rediscloud_agent_memory.this.name
}

output "agent_memory_store_id" {
  description = "Agent Memory store ID."
  value       = rediscloud_agent_memory.this.id
}

output "agent_memory_endpoint" {
  description = "Agent Memory primary data-plane endpoint."
  value       = rediscloud_agent_memory.this.endpoint
}

output "agent_memory_endpoints" {
  description = "Agent Memory regional data-plane endpoints."
  value       = rediscloud_agent_memory.this.endpoints
}

output "agent_memory_api_key_ids" {
  description = "Agent Memory data-plane API key IDs by config key."
  value = {
    for key, api_key in rediscloud_agent_memory_api_key.this : key => api_key.id
  }
}

output "agent_memory_api_key_obfuscated_tokens" {
  description = "Agent Memory data-plane API key obfuscated tokens by config key."
  value = {
    for key, api_key in rediscloud_agent_memory_api_key.this : key => api_key.obfuscated_token
  }
}

output "agent_memory_api_keys" {
  description = "Generated Agent Memory data-plane API keys by config key. These values are returned only on creation and stored in Terraform state."
  value = {
    for key, api_key in rediscloud_agent_memory_api_key.this : key => api_key.api_key
  }
  sensitive = true
}
