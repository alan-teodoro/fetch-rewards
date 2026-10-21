terraform {
  required_version = ">= 1.11.1"

  required_providers {
    rediscloud = {
      source  = "RedisLabs/rediscloud"
      version = ">= 2.19.0, < 3.0.0"
    }
  }
}
