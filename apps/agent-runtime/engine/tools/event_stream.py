"""Event Stream tools — consume events from Kafka, Redis Streams, or the built-in event buffer."""

from __future__ import annotations
import json
import time
from typing import Any
from engine.tools.base import BaseTool


class EventBufferTool(BaseTool):
    """Read buffered events from Redis — works with webhook triggers that accumulate events."""

    name = "event_buffer"
    description = "Read and consume buffered events from the platform event queue. Events arrive via webhook triggers and accumulate until consumed. Supports filtering by event type and time window."
    input_schema = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Event source identifier (trigger name or 'all')",
            },
            "event_type": {
                "type": "string",
                "description": "Filter by event type (optional)",
            },
            "limit": {
                "type": "integer",
                "default": 100,
                "description": "Max events to read",
            },
            "since_seconds": {
                "type": "integer",
                "default": 3600,
                "description": "Only events from last N seconds",
            },
            "consume": {
                "type": "boolean",
                "default": True,
                "description": "Mark events as consumed after reading",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        import redis.asyncio as aioredis
        import os

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        limit = min(arguments.get("limit", 100), 1000)
        since = arguments.get("since_seconds", 3600)
        consume = arguments.get("consume", True)
        event_type = arguments.get("event_type")
        source = arguments.get("source", "all")

        try:
            r = aioredis.from_url(redis_url, decode_responses=True)
            key = f"af:events:{source}"

            # Read from Redis sorted set (score = timestamp)
            cutoff = time.time() - since
            raw_events = await r.zrangebyscore(
                key, min=cutoff, max="+inf", start=0, num=limit
            )

            events = []
            for raw in raw_events:
                try:
                    evt = json.loads(raw) if isinstance(raw, str) else raw
                    if event_type and evt.get("type") != event_type:
                        continue
                    events.append(evt)
                except (json.JSONDecodeError, TypeError):
                    events.append({"raw": raw})

            # Consume (remove) read events
            if consume and raw_events:
                await r.zrem(key, *raw_events)

            await r.aclose()
            return {
                "events": events,
                "count": len(events),
                "source": source,
                "consumed": consume,
            }
        except Exception as e:
            return {"error": str(e), "events": [], "count": 0}


class RedisStreamConsumerTool(BaseTool):
    """Read messages from a Redis Stream — real-time event processing."""

    name = "redis_stream_consumer"
    description = "Consume messages from a Redis Stream. Ideal for real-time event processing, IoT sensor data, and inter-agent communication. Supports consumer groups for load balancing."
    input_schema = {
        "type": "object",
        "properties": {
            "stream": {
                "type": "string",
                "description": "Redis stream name (e.g., 'sensor:temperature', 'orders:new')",
            },
            "group": {
                "type": "string",
                "description": "Consumer group name (created if not exists)",
            },
            "consumer": {
                "type": "string",
                "description": "Consumer name within the group",
            },
            "count": {
                "type": "integer",
                "default": 10,
                "description": "Max messages to read",
            },
            "block_ms": {
                "type": "integer",
                "default": 0,
                "description": "Block for N ms waiting for messages (0 = no block)",
            },
            "acknowledge": {
                "type": "boolean",
                "default": True,
                "description": "Acknowledge messages after reading",
            },
        },
        "required": ["stream"],
    }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        import redis.asyncio as aioredis
        import os

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        stream = arguments["stream"]
        group = arguments.get("group", "abenix-default")
        consumer = arguments.get("consumer", "worker-1")
        count = min(arguments.get("count", 10), 1000)
        block_ms = min(arguments.get("block_ms", 0), 5000)
        ack = arguments.get("acknowledge", True)

        try:
            r = aioredis.from_url(redis_url, decode_responses=True)

            # Create consumer group if not exists
            try:
                await r.xgroup_create(stream, group, id="0", mkstream=True)
            except Exception as e:
                # BUSYGROUP = group already exists (expected)
                if "BUSYGROUP" not in str(e):
                    return {
                        "error": f"Failed to create consumer group: {e}",
                        "messages": [],
                        "count": 0,
                    }

            # Read new messages for this consumer
            results = await r.xreadgroup(
                group, consumer, {stream: ">"}, count=count, block=block_ms
            )

            messages = []
            msg_ids = []
            for stream_name, entries in results or []:
                for msg_id, fields in entries:
                    messages.append({"id": msg_id, "data": fields})
                    msg_ids.append(msg_id)

            # Acknowledge
            if ack and msg_ids:
                await r.xack(stream, group, *msg_ids)

            await r.aclose()
            return {
                "messages": messages,
                "count": len(messages),
                "stream": stream,
                "group": group,
            }
        except Exception as e:
            return {"error": str(e), "messages": [], "count": 0}


class RedisStreamPublisherTool(BaseTool):
    """Publish messages to a Redis Stream — for inter-agent and event-driven communication."""

    name = "redis_stream_publisher"
    description = "Publish messages to a Redis Stream. Use for inter-agent communication, event broadcasting, and IoT data ingestion pipelines."
    input_schema = {
        "type": "object",
        "properties": {
            "stream": {"type": "string", "description": "Redis stream name"},
            "data": {"type": "object", "description": "Message data (key-value pairs)"},
            "maxlen": {
                "type": "integer",
                "default": 10000,
                "description": "Max stream length (oldest trimmed)",
            },
        },
        "required": ["stream", "data"],
    }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        import redis.asyncio as aioredis
        import os

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        stream = arguments["stream"]
        data = arguments.get("data", {})
        maxlen = arguments.get("maxlen", 10000)

        # Flatten data to string values for Redis
        flat = {
            str(k): json.dumps(v) if not isinstance(v, str) else v
            for k, v in data.items()
        }

        try:
            r = aioredis.from_url(redis_url, decode_responses=True)
            msg_id = await r.xadd(stream, flat, maxlen=maxlen)
            await r.aclose()
            return {"message_id": msg_id, "stream": stream, "published": True}
        except Exception as e:
            return {"error": str(e), "published": False}


class KafkaConsumerTool(BaseTool):
    """Consume messages from Apache Kafka topics."""

    name = "kafka_consumer"
    description = "Consume messages from Kafka topics. For high-throughput event streaming: IoT telemetry, financial transactions, log aggregation. Requires KAFKA_BOOTSTRAP_SERVERS env var."
    input_schema = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Kafka topic to consume from"},
            "group_id": {
                "type": "string",
                "default": "abenix",
                "description": "Consumer group ID",
            },
            "max_messages": {
                "type": "integer",
                "default": 10,
                "description": "Max messages to consume",
            },
            "timeout_ms": {
                "type": "integer",
                "default": 5000,
                "description": "Poll timeout in milliseconds",
            },
            "from_beginning": {
                "type": "boolean",
                "default": False,
                "description": "Start from beginning of topic",
            },
        },
        "required": ["topic"],
    }

    async def execute(self, arguments: dict[str, Any]) -> Any:
        import os

        topic = arguments["topic"]
        group_id = arguments.get("group_id", "abenix")
        max_messages = min(arguments.get("max_messages", 10), 1000)
        timeout_ms = min(arguments.get("timeout_ms", 5000), 30000)
        from_beginning = arguments.get("from_beginning", False)

        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        if not bootstrap:
            return {
                "error": "KAFKA_BOOTSTRAP_SERVERS not configured",
                "messages": [],
                "count": 0,
            }

        try:
            from aiokafka import AIOKafkaConsumer

            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=bootstrap,
                group_id=group_id,
                auto_offset_reset="earliest" if from_beginning else "latest",
                enable_auto_commit=True,
                value_deserializer=lambda m: (
                    json.loads(m.decode("utf-8")) if m else None
                ),
            )
            await consumer.start()

            messages = []
            try:
                batch = await consumer.getmany(
                    timeout_ms=timeout_ms, max_records=max_messages
                )
                for tp, msgs in batch.items():
                    for msg in msgs:
                        messages.append(
                            {
                                "topic": msg.topic,
                                "partition": msg.partition,
                                "offset": msg.offset,
                                "key": msg.key.decode("utf-8") if msg.key else None,
                                "value": msg.value,
                                "timestamp": msg.timestamp,
                            }
                        )
            finally:
                await consumer.stop()

            return {"messages": messages, "count": len(messages), "topic": topic}
        except ImportError:
            return {
                "error": "aiokafka not installed. Run: pip install aiokafka",
                "messages": [],
                "count": 0,
            }
        except Exception as e:
            return {"error": str(e), "messages": [], "count": 0}
