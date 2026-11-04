output "subscription" {
  description = "Resolved subscription identity; ownership is explicit in mode."
  value       = { id = local.subscription_id, name = var.subscription.subscription_name, mode = var.subscription.mode }
}
output "databases" {
  description = "Managed database identities and endpoints by stable config key."
  value       = { for key, db in module.database : key => { id = db.database_id, name = db.database_name, public_endpoint = db.public_endpoint } }
}
output "database_passwords" {
  description = "Generated application ACL passwords. Store securely."
  value       = { for key, db in module.database : key => db.acl_user_password }
  sensitive   = true
}
output "agent_memory_stores" {
  description = "Store identities and endpoints by stable config key."
  value       = { for key, store in module.agent_memory : key => { id = store.agent_memory_store_id, name = store.agent_memory_name, database_id = store.database_id, endpoint = store.agent_memory_endpoint, endpoints = store.agent_memory_endpoints, api_key_ids = store.agent_memory_api_key_ids } }
}
output "agent_memory_api_keys" {
  description = "Sensitive runtime API keys by store key and API key key."
  value       = { for key, store in module.agent_memory : key => store.agent_memory_api_keys }
  sensitive   = true
}
