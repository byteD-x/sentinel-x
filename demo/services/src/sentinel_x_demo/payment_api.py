"""
Payment API — 支付服务。

端点:
  - GET  /health
  - POST /payments       处理支付
  - GET  /payments/{id}  查询支付状态
  - POST /fault/inject    注入故障
  - POST /fault/clear     清除故障
"""

import logging
import uuid
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from sentinel_x_demo.common import (
    FaultConfig,
    create_health_endpoint,
    create_fault_control_endpoint,
    add_request_logging,
    service_response,
)

logger = logging.getLogger("payment-api")

app = FastAPI(title="Payment API", version="0.1.0")
fault_config = FaultConfig()

# 模拟支付记录
payments: dict[str, dict] = {}


class PaymentCreate(BaseModel):
    order_id: str
    amount: float


@app.post("/payments", status_code=201)
async def process_payment(payment: PaymentCreate, request: Request):
    """处理支付。"""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    fault_error = await fault_config.apply_async()
    if fault_error:
        raise HTTPException(status_code=503, detail=f"[payment-api] {fault_error}")

    payment_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"

    payments[payment_id] = {
        "payment_id": payment_id,
        "order_id": payment.order_id,
        "amount": payment.amount,
        "status": "ok",
    }
    return service_response(
        "payment-api",
        {"payment_id": payment_id, "status": "ok"},
        request_id=request_id,
    )


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str, request: Request):
    """查询支付状态。"""
    request_id = request.headers.get("x-request-id", "")
    payment = payments.get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail=f"支付 {payment_id} 不存在")
    return service_response("payment-api", payment, request_id=request_id)


create_health_endpoint(app, "payment-api", fault_config)
create_fault_control_endpoint(app, "payment-api", fault_config)
add_request_logging(app, "payment-api")


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8084)


if __name__ == "__main__":
    main()
