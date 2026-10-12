variable "prefix" {
  type = string
}

variable "callback_urls" {
  type    = list(string)
  default = ["http://localhost:5173"]
}
