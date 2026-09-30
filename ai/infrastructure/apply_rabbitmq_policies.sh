#!/usr/bin/env bash
# ==============================================================================
# RabbitMQ Infrastructure Policies (IaC)
# Наложение поведенческих параметров на очереди без риска 406 PRECONDITION_FAILED
# ==============================================================================

set -euo pipefail

EXCHANGE="ai.content.exchange"

echo "🔧 Наложение политик RabbitMQ для контура AI..."

# 1. Маршрутизация битых задач в DLQ при nack(requeue=False)
rabbitmqctl set_policy Policy_Requested "^ai\.content\.generate\.requested$" \
  "{\"dead-letter-exchange\":\"${EXCHANGE}\",\"dead-letter-routing-key\":\"ai.content.generate.dlq\"}" \
  --apply-to queues

# 2. Аппаратный троттлинг In-Flight (TTL 5000ms -> Возврат в основную очередь requested)
rabbitmqctl set_policy Policy_Delay_5s "^ai\.content\.generate\.delay_5s$" \
  "{\"message-ttl\":5000,\"dead-letter-exchange\":\"${EXCHANGE}\",\"dead-letter-routing-key\":\"ai.content.generate.requested\"}" \
  --apply-to queues

# 3. Кольцевой буфер DLQ (Max 10000 -> drop-head вытесняет старые инциденты, сохраняя свежие)
rabbitmqctl set_policy Policy_DLQ "^ai\.content\.generate\.dlq$" \
  '{"max-length":10000,"overflow":"drop-head"}' \
  --apply-to queues

echo "✅ Политики RabbitMQ успешно применены."
