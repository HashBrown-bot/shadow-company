"""Reviewed adapter selection, never executable configuration."""

from adapters.http.refund import RefundAdapter as RESTAdapter
from adapters.http.refund import validate_example as validate_rest
from packages.transport.http import BoundaryError


def validate_example(config):
    if config.product.adapter == "http_refund_v1":
        return validate_rest(config)
    from adapters.http.credit import validate_credit

    return validate_credit(config)


def RefundAdapter(db, scope, config):
    if config.product.adapter == "http_refund_v1":
        return RESTAdapter(db, scope, config)
    if config.product.adapter == "rpc_credit_v1":
        from adapters.http.credit import CreditAdapter

        return CreditAdapter(db, scope, config)
    raise BoundaryError("未注册适配器")
