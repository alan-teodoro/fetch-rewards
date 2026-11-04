terraform {
  required_version = ">= 1.16.7"
  required_providers {
    rediscloud = { source = "RedisLabs/rediscloud", version = "2.20.0" }
    random     = { source = "hashicorp/random", version = ">= 3.5.0, < 4.0.0" }
  }
}
