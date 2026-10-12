variable "topic_name" {
  type = string
}

variable "queue_filters" {
  description = "queue name => eventType filter list (null = receive everything)."
  type        = map(list(string))
}

variable "max_receive_count" {
  type    = number
  default = 5
}
