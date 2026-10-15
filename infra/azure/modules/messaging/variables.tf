variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "topic_name" {
  type = string
}

variable "subscription_filters" {
  description = "Subscription name => list of eventType values to match, or null for no filter (receive everything)."
  type        = map(list(string))
}

variable "max_delivery_count" {
  type = number
}
