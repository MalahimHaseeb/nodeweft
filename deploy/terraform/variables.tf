variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "project" {
  type    = string
  default = "nodeweft"
}

variable "alb_domain" {
  type        = string
  description = "Origin name that points to the load balancer"
}

variable "cdn_domain" {
  type        = string
  description = "Public name that points to CloudFront"
}

variable "alb_certificate_arn" {
  type        = string
  description = "ACM certificate for alb_domain, in the same region as the load balancer"
}

variable "cloudfront_certificate_arn" {
  type        = string
  description = "ACM certificate for cdn_domain, in us-east-1"
}

variable "files_bucket_name" {
  type        = string
  description = "Existing S3 bucket that holds the workflow input files"
}

variable "sqs_queue_arn" {
  type        = string
  description = "Existing SQS queue used for workflow runs"
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "root_volume_gb" {
  type    = number
  default = 30
}

variable "k3s_channel" {
  type    = string
  default = "stable"
}

variable "cloudfront_price_class" {
  type    = string
  default = "PriceClass_All"
}

variable "enable_waf" {
  type    = bool
  default = false
}

variable "waf_global_limit" {
  type    = number
  default = 600
}

variable "waf_auth_limit" {
  type    = number
  default = 40
}
