output "instance_id" {
  value = aws_instance.node.id
}

output "public_ip" {
  description = "Add this address to the MongoDB Atlas network access list"
  value       = aws_eip.node.public_ip
}

output "deploy_bucket" {
  value = aws_s3_bucket.deploy.id
}

output "ecr_registry" {
  value = local.ecr_registry
}

output "alb_dns_name" {
  value = aws_lb.api.dns_name
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.api.domain_name
}

output "dns_records_to_add" {
  value = <<-EOT
    CNAME  ${replace(var.alb_domain, ".malahim.dev", "")}  ->  ${aws_lb.api.dns_name}
    CNAME  ${replace(var.cdn_domain, ".malahim.dev", "")}  ->  ${aws_cloudfront_distribution.api.domain_name}
  EOT
}
