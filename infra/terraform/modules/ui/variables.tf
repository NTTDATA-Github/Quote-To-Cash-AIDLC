variable "prefix" {
  type = string
}

variable "account_id" {
  description = "Used to make the globally-unique S3 bucket name predictable (prefix alone is not globally unique)."
  type        = string
}

variable "alb_dns_name" {
  description = "The app ALB's DNS name. Added as a second CloudFront origin at /graphql* so the HTTPS UI can call the HTTP-only ALB same-origin (browsers block HTTPS pages fetching plain HTTP, and this sidesteps CORS too)."
  type        = string
}
