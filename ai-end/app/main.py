from contextlib import asynccontextmanager
from contextvars import ContextVar
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.routers import router, start_token_cleanup_task, stop_token_cleanup_task
from app.config import settings
from app.tools.db import close_global_pool, get_cursor
import logging
import uuid

_request_id_var = ContextVar("request_id", default="-")


class _SafeFormatter(logging.Formatter):
    """format 时若 record 缺 request_id，自动用 '-' 兜底"""
    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


_fmt = "%(asctime)s [%(levelname)s] [%(name)s] [%(request_id)s] [%(filename)s:%(lineno)d] %(message)s"
logging.basicConfig(level=logging.INFO, format=_fmt)
for h in logging.getLogger().handlers:
    h.setFormatter(_SafeFormatter(_fmt))

# 给所有现有 logger 都装上 safe formatter
for name in list(logging.root.manager.loggerDict.keys()):
    sub = logging.getLogger(name)
    for h in sub.handlers:
        h.setFormatter(_SafeFormatter(_fmt))

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求注入唯一 request_id，并贯穿到所有日志。"""
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
        request.state.request_id = rid
        token = _request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.tools.tool_registry import init_registry
    from app.tools.db import init_agent_tables
    from app.routers import start_token_cleanup_task, stop_token_cleanup_task
    init_registry()
    init_agent_tables()
    start_token_cleanup_task()

    # 预热 Embedding 模型（避免首请求冷启动 5-15s）
    # 在线程池里跑，不阻塞 event loop
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    def _warmup_embed():
        try:
            from app.tools.llm_tools import LLM_tools
            LLM_tools.warmup_embedding()
        except Exception as e:
            logger.warning(f"Embedding 预热失败: {e}")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="warmup") as ex:
        await loop.run_in_executor(ex, _warmup_embed)
        # 顺便预热 tiktoken（compact 上下文压缩用）
        def _warmup_tiktoken():
            try:
                from app.tools.compact_service import warmup_tokenizer
                warmup_tokenizer()
            except Exception as e:
                logger.warning(f"tiktoken 预热失败: {e}")
        await loop.run_in_executor(ex, _warmup_tiktoken)

    logger.info("=" * 50)
    logger.info(f"{settings.app_name} 服务已启动")
    logger.info("=" * 50)
    yield
    # Graceful shutdown：清理连接池和后台 executor
    logger.info("服务关闭中...")
    close_global_pool()
    from app.harness.checkpoint import CheckpointManager
    from app.harness.tool_governor import ToolGovernor
    try:
        CheckpointManager().shutdown()
    except Exception:
        pass
    try:
        ToolGovernor().shutdown()
    except Exception:
        pass
    try:
        from app.tools.llm_tools import aclose_async_client, close_http_clients
        await aclose_async_client()
        close_http_clients()
    except Exception:
        pass
    try:
        stop_token_cleanup_task()
    except Exception:
        pass
    try:
        from app.agents.workflows import shutdown_executor
        shutdown_executor()
    except Exception:
        pass
    try:
        from app.tools.ranker import shutdown as shutdown_ranker
        shutdown_ranker()
    except Exception:
        pass
    try:
        from app.agents.workflows.chat_graph import shutdown_recall_executor
        shutdown_recall_executor()
    except Exception:
        pass
    logger.info("服务已关闭")


app = FastAPI(
    title=settings.app_name,
    description="Multi-Agent 智能助手系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)


@app.middleware("http")
async def metrics_middleware(request, call_next):
    """HTTP 请求指标中间件：每个请求都记录 method/path/status/duration"""
    import time
    start = time.time()
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        try:
            from app.utils.metrics import http_requests_total, http_request_duration_seconds
            duration = time.time() - start
            # 路径模板化（去掉动态 ID，避免指标维度爆炸）
            path = request.url.path
            for prefix in ("/ai/chat/session/", "/ai/chat/checkpoints"):
                if path.startswith(prefix):
                    path = prefix + "{id}"
                    break
            http_requests_total.labels(
                method=request.method,
                path=path,
                status=str(status),
            ).inc()
            http_request_duration_seconds.labels(
                method=request.method,
                path=path,
            ).observe(duration)
        except Exception:
            pass
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # 白名单，不用 *
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Prometheus 指标端点（/ai/metrics）
from app.utils.metrics import metrics_router
app.include_router(metrics_router)


@app.get("/")
async def root():
    return {"message": "ViewHub AI Agent is running", "version": "1.0.0"}


@app.get("/favicon.ico")
async def favicon():
    return {"status": "not found"}


@app.get("/health")
async def health():
    """Liveness: 进程是否存活（不查依赖）"""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness: 依赖（DB、Redis、LLM provider）是否健康"""
    from fastapi.concurrency import run_in_threadpool

    checks = {"db": False, "redis": False, "llm": False}

    # DB（同步 psycopg2 走线程池，避免阻塞 event loop）
    def _check_db() -> bool:
        with get_cursor(cursor_factory=None) as cursor:
            if cursor is None:
                return False
            try:
                cursor.execute("SELECT 1")
                return True
            except Exception:
                return False
    checks["db"] = await run_in_threadpool(_check_db)

    # Redis
    def _check_redis() -> bool:
        try:
            from app.tools.context_tools import _get_redis
            r = _get_redis()
            if r is not None:
                r.ping()
                return True
        except Exception:
            # ping 失败（熔断或连接异常），不冒到顶层
            pass
        return False
    checks["redis"] = await run_in_threadpool(_check_redis)

    # LLM provider
    if settings.deepseek_api_key or settings.minimax_api_key:
        checks["llm"] = True

    ok = all(checks.values())
    return {"status": "ready" if ok else "degraded", "checks": checks}


@app.get("/metrics")
async def metrics():
    """Prometheus 指标端点"""
    from app.utils.metrics import get_metrics, get_metrics_content_type
    metrics_data = get_metrics()
    if metrics_data is None:
        return Response(
            content="# prometheus_client not installed\n",
            media_type="text/plain",
        )
    return Response(
        content=metrics_data,
        media_type=get_metrics_content_type(),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
