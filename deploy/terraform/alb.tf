locals {
  routes = {
    execution_memory = {
      priority = 10
      service  = "execution"
      paths    = ["/workflows/*/memory"]
    }
    execution = {
      priority = 20
      service  = "execution"
      paths    = ["/runs", "/runs/*"]
    }
    workflow = {
      priority = 30
      service  = "workflow"
      paths    = ["/workflows", "/workflows/*", "/nodes", "/nodes/*"]
    }
    auth = {
      priority = 40
      service  = "auth"
      paths    = ["/auth/*", "/health"]
    }
  }
}

resource "aws_lb" "api" {
  name                       = "${local.name}-alb"
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = data.aws_subnets.default.ids
  idle_timeout               = 60
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "service" {
  for_each             = local.node_ports
  name                 = "${local.name}-${each.key}"
  port                 = each.value
  protocol             = "HTTP"
  vpc_id               = data.aws_vpc.default.id
  target_type          = "instance"
  deregistration_delay = 15

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group_attachment" "service" {
  for_each         = local.node_ports
  target_group_arn = aws_lb_target_group.service[each.key].arn
  target_id        = aws_instance.node.id
  port             = each.value
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.alb_certificate_arn

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      message_body = jsonencode({ success = false, message = "Forbidden", data = null, error = { code = "FORBIDDEN", details = null } })
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "route" {
  for_each     = local.routes
  listener_arn = aws_lb_listener.https.arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service[each.value.service].arn
  }

  condition {
    path_pattern {
      values = each.value.paths
    }
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_secret.result]
    }
  }
}
